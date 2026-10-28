"""The dashboard quality gate passes and catches the mistakes it is meant to catch."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

if importlib.util.find_spec("pythonnet") is None or importlib.util.find_spec("sempy") is None:
    pytest.skip("needs pythonnet and the TOM assemblies (semantic-link-sempy)", allow_module_level=True)

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import validate_model  # noqa: E402


@pytest.fixture(scope="module")
def model():
    return validate_model.load_model()


def test_dashboard_passes_every_rule(model):
    failed = [r.rule for r in validate_model.model_rules(model) + validate_model.report_rules(model) if not r.passed]
    assert failed == []


def test_snapshot_measure_summed_across_runs_is_caught(model):
    measure = model.Tables.Find("Backlog").Measures.Find("Backlog Records")
    original = measure.Expression
    measure.Expression = "SUM ( Backlog[Records Count] )"  # would add the backlog of every run
    try:
        failed = {r.rule for r in validate_model.model_rules(model) if not r.passed}
    finally:
        measure.Expression = original
    assert "Snapshot measures never add up several runs" in failed
