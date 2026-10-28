"""Cut-over rehearsal and dashboard export (runs last: it recreates the legacy data)."""

from __future__ import annotations

import pandas as pd

from migration.export import export
from migration.simulate import simulate


def test_rehearsal_burns_down_the_backlog_and_the_gate_catches_the_manual_edit(settings, tmp_path):
    results = simulate(days=5, tamper_day=3, fix_share=0.5, scale=0.1, settings=settings)
    assert [r["status"] for r in results] == ["passed", "passed", "failed", "passed", "passed"]

    counts = export(tmp_path, settings)
    assert counts["runs"] == 5
    for name in ("runs", "run_volumes", "checks", "coverage", "backlog", "rejected_records", "source_tables"):
        assert (tmp_path / f"{name}.parquet").exists()

    backlog = pd.read_parquet(tmp_path / "backlog.parquet").groupby("Run ID")["Records"].sum()
    assert backlog.iloc[-1] < backlog.iloc[0] / 2  # the business fixes records at the source every day

    coverage = pd.read_parquet(tmp_path / "coverage.parquet")
    last = coverage[coverage["Run ID"] == coverage["Run ID"].max()]
    # every legacy row is either migrated or waiting in the backlog
    assert (last["Migrated Rows"] + last["Rejected Rows"] == last["Legacy Rows"]).all()

    rejected = pd.read_parquet(tmp_path / "rejected_records.parquet")
    assert set(rejected.columns) == {"Source Table", "Source ID", "Reason", "Run ID", "Rejected At", "Amount"}
