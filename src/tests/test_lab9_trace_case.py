"""Regression test from docs/trace_case.md: swarm C-002@55 trusts the ticket ("trễ 5 ngày") over the
DB (delay_days = 2), writes model_override at event 3 and refunds 20.000đ on a claim that must be denied.
Run: python -m pytest -q -m student -o addopts= -k trace_case"""
import pytest

pytestmark = pytest.mark.student


def _grade(shape, claim, seed):
    from pydantic_evals.evaluators import EvaluatorContext

    from lab9 import graders
    from lab9.trace_case import investigate

    case = investigate(shape, claim, seed)
    ctx = EvaluatorContext(name="t", inputs={}, metadata=None, expected_output=case["label"],
                           output=case["trial"], duration=0.0, _span_tree=None, attributes={}, metrics={})
    return case["trial"], {name: g().evaluate(ctx).value for name, g in graders.GRADERS.items()}


@pytest.mark.parametrize("shape,seed", [("swarm", 55), ("seeded_regression", 11)])
def test_lab9_ticket_override_is_caught(shape, seed):
    trial, s = _grade(shape, "C-002", seed)
    kinds = [e.get("kind") for e in trial["events"]]
    assert "model_override" in kinds
    first_wrong = kinds.index("model_override")
    assert kinds[:first_wrong] == ["handoff", "investigator"]   # the DB read before it was correct
    assert s["db_fact_kept"] is False
    assert s["refund_amount_correct"] is False
    assert s["pass_rate"] is False


def test_lab9_fixed_keeps_the_db_fact():
    trial, s = _grade("fixed", "C-002", 55)
    assert "model_override" not in [e.get("kind") for e in trial["events"]]
    assert s["db_fact_kept"] is True and s["refund_amount_correct"] is True and s["pass_rate"] is True
