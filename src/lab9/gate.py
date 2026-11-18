"""CI gate: compare a PR eval report with the main-branch baseline using the metric spec.

    python -m lab9.gate --pr reports/eval_workflow.json --baseline reports/baseline_v1.json

exit 0 = merge, exit 1 = blocked. Safety metrics: max 0, no averaging away.
Capability metrics: meet the floor AND the paired CI of (PR - main) is not entirely below 0.
Thresholds may only get stricter on the same eval-set version (ratchet).
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from lab8.console import utf8_stdio
from lab9 import stats
from lab9.eval import SPEC, aggregate, load_spec, per_item
from lab9.graders import GRADERS


def integrity_check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> list[str]:
    """M7 (Expert): refuse to compare reports that cannot be trusted. Return a list of problems
    (empty = trustworthy). A gate that passes a broken report is worse than no gate.
    Must catch at least:
      - any metric value in pr["metrics"] that is NaN or inf
      - len(pr["rows"]) != manifest items x len(manifest seeds)   (dropped / duplicated rows)
      - the (item_id, seed) set of PR differs from the baseline's (cherry-picked seeds/items)
      - pr["evaluator_failures"] non-empty, or a row whose value for a graded spec metric is
        None (a crashed grader silently scores as "missing" and drops out of the mean)
      - base_spec given and a threshold in spec is LOOSER than in base_spec for the same
        eval-set version (ratchet: max may not rise, min may not fall, a blocking metric may
        not become non-blocking, a metric may not disappear; the same for spec["slices"],
        including dropping no_significant_drop)
      - an item's slice tags in PR rows differ from the baseline's (relabelling an item out of a
        slice hides its regression from the slice gate)
    Also caught here: duplicated (item, seed) rows, rows whose seed/item is not in the manifest,
    a manifest that differs from the baseline's, non-boolean row values, and metrics that do not
    match what the rows add up to (a hand-edited or partially recomputed summary)."""
    problems: list[str] = []
    man, bman = pr.get("manifest") or {}, base.get("manifest") or {}
    rows, brows = pr.get("rows") or [], base.get("rows") or []

    # 1. every metric value must be a finite number (or None for an undefined pass@k)
    for k, v in (pr.get("metrics") or {}).items():
        if isinstance(v, bool) or v is None:
            continue
        if not isinstance(v, (int, float)) or not math.isfinite(v):
            problems.append(f"metric {k} = {v!r} is not a finite number")

    # 2. the row count and the (item, seed) grid must match the manifest and the baseline
    seeds = list(man.get("seeds") or [])
    want = (man.get("items") or 0) * len(seeds)
    if len(rows) != want:
        problems.append(f"{len(rows)} rows, manifest promises {man.get('items')} items x {len(seeds)} seeds = {want}")
    keys = [(r.get("item_id"), r.get("seed")) for r in rows]
    dups = sorted({k for k in keys if keys.count(k) > 1}, key=str)
    if dups:
        problems.append(f"duplicated (item, seed) rows: {dups[:5]}")
    stray = sorted({r.get("seed") for r in rows} - set(seeds), key=str)
    if stray:
        problems.append(f"rows use seeds {stray} that the manifest does not list")
    bkeys = {(r.get("item_id"), r.get("seed")) for r in brows}
    if set(keys) != bkeys:
        miss, extra = sorted(bkeys - set(keys), key=str), sorted(set(keys) - bkeys, key=str)
        problems.append(f"(item, seed) set differs from the baseline: {len(miss)} missing {miss[:3]}, "
                        f"{len(extra)} extra {extra[:3]}")
    for field in ("items", "seeds"):
        if bman and man.get(field) != bman.get(field):
            problems.append(f"manifest {field} {man.get(field)!r} != baseline {bman.get(field)!r}")

    # 3. graders must all have run: no evaluator failures, no None / non-boolean per-row value
    failures = pr.get("evaluator_failures")
    if not isinstance(failures, list):
        problems.append("evaluator_failures missing from the report")
    elif failures:
        problems.append(f"{len(failures)} evaluator failure(s), first: {str(failures[0])[:80]}")
    graded = [m["id"] for m in spec.get("metrics") or []
              if m["id"] in GRADERS or any(m["id"] in r for r in brows)]
    bad_cells = [(r.get("item_id"), r.get("seed"), m) for r in rows for m in graded
                 if not isinstance(r.get(m), bool)]
    if bad_cells:
        problems.append(f"{len(bad_cells)} row value(s) missing or not a boolean, first: {bad_cells[0]}")

    # 4. the summary must be what the rows add up to
    if rows and not bad_cells and not problems:
        ks = set(spec.get("pass_k") or [])
        ks |= {int(k.rsplit("_", 1)[1]) for k in (pr.get("metrics") or {})
               if k.startswith(("pass_at_", "pass_hat_")) and k.rsplit("_", 1)[1].isdigit()}
        has_cost = all("cost" in r for r in rows)
        calc_rows = rows if has_cost else [{**r, "cost": 0.0} for r in rows]
        try:
            calc = aggregate(calc_rows, [m for m in graded if m in rows[0]], k_values=sorted(ks))
        except (ValueError, TypeError, KeyError) as e:
            problems.append(f"cannot recompute metrics from rows: {e}")
            calc = {}
        for k, v in (pr.get("metrics") or {}).items():
            if k not in calc or (k == "cost_per_success" and not has_cost):
                continue
            c = calc[k]
            if (c is None) != (v is None) or (c is not None and abs(float(v) - float(c)) > 1e-6):
                problems.append(f"metric {k} = {v!r} but the rows give {c!r}")

    # 5. slice tags come from the label; an item may not leave (or join) a slice in the PR
    bslices = {r.get("item_id"): sorted(r.get("slices") or []) for r in brows}
    moved = sorted({r.get("item_id") for r in rows
                    if r.get("item_id") in bslices and sorted(r.get("slices") or []) != bslices[r.get("item_id")]},
                   key=str)
    if moved:
        problems.append(f"slice tags differ from the baseline for {moved[:5]}")

    # 6. ratchet: on the same eval-set version thresholds may only get stricter
    if base_spec is not None:
        problems += ratchet_problems(spec, base_spec)
    return problems


def _looser(old: dict, new: dict, where: str) -> list[str]:
    out = []
    if "max" in old and ("max" not in new or new["max"] > old["max"]):
        out.append(f"{where}: max {old['max']} -> {new.get('max')}")
    if "min" in old and ("min" not in new or new["min"] < old["min"]):
        out.append(f"{where}: min {old['min']} -> {new.get('min')}")
    if "max_increase" in old and ("max_increase" not in new or new["max_increase"] > old["max_increase"]):
        out.append(f"{where}: max_increase {old['max_increase']} -> {new.get('max_increase')}")
    if old.get("no_significant_drop") and not new.get("no_significant_drop"):
        out.append(f"{where}: no_significant_drop dropped")
    return out


def ratchet_problems(spec: dict, base_spec: dict) -> list[str]:
    """Thresholds in spec compared with base_spec. Only applies on the same eval-set version:
    a new version needs a new baseline, and its thresholds start over."""
    if spec.get("eval_set_version") != base_spec.get("eval_set_version"):
        return []
    out: list[str] = []
    for key in ("eval_set", "labels", "seeds", "adversarial_pack"):
        if base_spec.get(key) != spec.get(key):
            out.append(f"ratchet: {key} changed ({base_spec.get(key)!r} -> {spec.get(key)!r}) on the same eval-set version")
    new_m = {m["id"]: m for m in spec.get("metrics") or []}
    for m in base_spec.get("metrics") or []:
        n = new_m.get(m["id"])
        if n is None:
            out.append(f"ratchet: metric {m['id']} removed")
            continue
        out += [f"ratchet: {p}" for p in _looser(m.get("threshold") or {}, n.get("threshold") or {}, m["id"])]
        if m.get("blocking") and not n.get("blocking"):
            out.append(f"ratchet: {m['id']} no longer blocking")
    new_s = {(s["name"], s["metric"]): s for s in spec.get("slices") or []}
    for s in base_spec.get("slices") or []:
        where = f"slice:{s['name']}/{s['metric']}"
        n = new_s.get((s["name"], s["metric"]))
        if n is None:
            out.append(f"ratchet: {where} removed")
            continue
        out += [f"ratchet: {p}" for p in _looser(s, n, where)]
        if s.get("blocking") and not n.get("blocking"):
            out.append(f"ratchet: {where} no longer blocking")
    return out


def slice_check(pr: dict, base: dict, spec: dict) -> tuple[list[str], list[str]]:
    """M5 (Advanced): an average can hide a regression on a small, important slice.
    For each entry of spec["slices"] ({"name", "metric", "min"?, "no_significant_drop"?, "blocking"}):
      - value = mean of per_item(pr, metric, slice_name=name)
      - fail if below "min", or if no_significant_drop and the paired CI over the slice's items
        lies entirely below 0
    Return (blocked ids like "slice:money_movement/pass_rate", report lines)."""
    blocked: list[str] = []
    lines: list[str] = []
    bs = spec.get("bootstrap", {})
    for s in spec.get("slices") or []:
        name, metric = s["name"], s["metric"]
        sid = f"slice:{name}/{metric}"
        a, b = per_item(pr, metric, slice_name=name), per_item(base, metric, slice_name=name)
        verdict, note, value = "ok", "", None
        if not a:
            verdict = "missing"            # an empty slice cannot vouch for anything
        else:
            value = round(sum(a.values()) / len(a), 4)
            if "min" in s and value < s["min"]:
                verdict = "fail"
            if "max" in s and value > s["max"]:
                verdict = "fail"
            keys = sorted(set(a) & set(b))
            if s.get("no_significant_drop") and keys:
                d, lo, hi = stats.paired_bootstrap([a[k] for k in keys], [b[k] for k in keys],
                                                   n_resamples=bs.get("n_resamples", 1000), rng=bs.get("rng", 2027))
                note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
                if hi < 0:
                    verdict = "fail"
        if verdict != "ok" and s.get("blocking"):
            blocked.append(sid)
        label = {"ok": "ok", "missing": "MISSING"}.get(verdict, "BLOCK" if s.get("blocking") else "warn")
        th = {k: s[k] for k in ("min", "max", "no_significant_drop") if k in s}
        lines.append(f"  {sid:<34} {value!s:<8} n={len(a):<3} {json.dumps(th):<28} {note:<28} {label}")
    return blocked, lines


def check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> tuple[list[str], list[str]]:
    if pr["manifest"]["eval_set_sha"] != base["manifest"]["eval_set_sha"]:
        return ["eval_set_sha"], ["  EVAL SET differs from the baseline's: re-run the baseline on the same eval set"]
    problems = integrity_check(pr, base, spec, base_spec)
    if problems:
        return ["integrity"], [f"  INTEGRITY {p}" for p in problems]
    blocked, lines = [], []
    bs = spec.get("bootstrap", {})
    for m in spec["metrics"]:
        mid, th, val = m["id"], m.get("threshold", {}), pr["metrics"].get(m["id"])
        verdict, note = "ok", ""
        if val is None:
            verdict = "missing"
        elif "max" in th and val > th["max"]:
            verdict = "fail"
        elif "min" in th and val < th["min"]:
            verdict = "fail"
        elif "max_increase" in th and base["metrics"].get(mid):
            if val > base["metrics"][mid] * (1 + th["max_increase"]):
                verdict = "fail"
        if th.get("no_significant_drop") and val is not None:
            a, b = per_item(pr, mid), per_item(base, mid)
            keys = sorted(set(a) & set(b))
            d, lo, hi = stats.paired_bootstrap([a[k] for k in keys], [b[k] for k in keys],
                                               n_resamples=bs.get("n_resamples", 1000), rng=bs.get("rng", 2027))
            note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
            if hi < 0:
                verdict = "fail"
        if verdict != "ok" and m.get("blocking"):
            blocked.append(mid)
        label = {"ok": "ok", "missing": "MISSING"}.get(verdict, "BLOCK" if m.get("blocking") else "warn")
        lines.append(f"  {mid:<22} {val!s:<8} {json.dumps(th):<40} {note:<28} {label}")
    if spec.get("slices"):
        sb, sl = slice_check(pr, base, spec)
        blocked += sb
        lines += sl
    return blocked, lines


def main(argv: list[str] | None = None) -> int:
    utf8_stdio()
    ap = argparse.ArgumentParser(prog="lab9.gate")
    ap.add_argument("--pr", required=True)
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--spec", default=str(SPEC))
    ap.add_argument("--base-spec", help="metric spec on main, for the ratchet check (M7)")
    args = ap.parse_args(argv)
    pr = json.loads(Path(args.pr).read_text(encoding="utf-8"))
    base = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
    base_spec = load_spec(Path(args.base_spec)) if args.base_spec else None
    blocked, lines = check(pr, base, load_spec(Path(args.spec)), base_spec)
    print(f"gate: PR {pr['run_id']} vs main {base['run_id']} · eval set {pr['manifest']['eval_set_sha']}")
    print("\n".join(lines))
    if blocked:
        print(f"exit 1 — blocked: {', '.join(blocked)}")
        return 1
    print("exit 0 — merge")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
