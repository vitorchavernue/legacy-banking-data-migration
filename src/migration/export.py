"""Exports the migration history as Parquet files for the Power BI monitoring dashboard.

Only control data leaves the database: run results, reconciliation checks, coverage, the rejected
backlog and the ids of rejected records (no names, CPFs or other personal data).
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from sqlalchemy import select

from migration import target_schema as t
from migration.config import Settings, get_settings
from migration.db import target_engine

SOURCE_TABLES = pd.DataFrame(
    {
        "Source Table": ["TB_CLIENTE", "TB_CONTA", "TB_LANCAMENTO"],
        "Entity": ["Customers", "Accounts", "Transactions"],
        "Entity Order": [1, 2, 3],
    }
)
MONEY = pa.decimal128(18, 2)


def _write(df: pd.DataFrame, path: Path, money: tuple[str, ...] = ()) -> None:
    table = pa.Table.from_pandas(df, preserve_index=False)
    for name in money:  # money as fixed decimal, never float
        values = [None if v is None or pd.isna(v) else Decimal(str(v)).quantize(Decimal("0.01")) for v in df[name]]
        table = table.set_column(table.schema.get_field_index(name), name, pa.array(values, type=MONEY))
    pq.write_table(table, path)


def _local(values: pd.Series) -> pd.Series:
    """Timestamps in the bank's time zone, without offset (how Power BI shows them)."""
    return pd.to_datetime(values, utc=True).dt.tz_convert("America/Sao_Paulo").dt.tz_localize(None)


def export(out: str | Path, settings: Settings | None = None) -> dict[str, int]:
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    with target_engine(settings or get_settings()).connect() as conn:
        runs = pd.DataFrame(conn.execute(select(t.run)).mappings().all())
        checks = pd.DataFrame(conn.execute(select(t.reconciliation_check)).mappings().all())
        coverage = pd.DataFrame(conn.execute(select(t.run_coverage)).mappings().all())
        backlog = pd.DataFrame(conn.execute(select(t.backlog_snapshot)).mappings().all())
        rejected = pd.DataFrame(
            conn.execute(
                select(
                    t.rejected_record.c.source_table,
                    t.rejected_record.c.source_id,
                    t.rejected_record.c.reason,
                    t.rejected_record.c.run_id,
                    t.rejected_record.c.rejected_at,
                    t.rejected_record.c.payload["VL_LANCAMENTO"].astext.label("amount"),
                )
            )
            .mappings()
            .all()
        )

    # 1. Runs and what each one processed
    volumes = [
        {
            "Run ID": r.run_id,
            "Source Table": table,
            "Rows Read": s["read"],
            "Rows Migrated": s["loaded"],
            "Rows Rejected": s["rejected"],
        }
        for r in runs.itertuples()
        for table, s in ((r.stats or {}).get("tables") or {}).items()
    ]
    runs_out = pd.DataFrame(
        {
            "Run ID": runs["run_id"],
            "Business Date": pd.to_datetime(runs["business_date"]),
            "Mode": runs["mode"].str.capitalize(),
            "Status": runs["status"].str.capitalize(),
            "Started At": _local(runs["started_at"]),
            "Duration (s)": [((s or {}).get("duration_s")) for s in runs["stats"]],
            "Profiles Refreshed": [((s or {}).get("profiles_refreshed")) for s in runs["stats"]],
        }
    ).sort_values("Run ID")

    # 2. Reconciliation checks of every run
    checks_out = pd.DataFrame(
        {
            "Run ID": checks["run_id"],
            "Check": checks["check_name"],
            "Severity": checks["severity"].str.capitalize(),
            "Passed": checks["passed"].astype(int),
            "Legacy Value": checks["source_value"],
            "New Systems Value": checks["target_value"],
            "Detail": checks["detail"],
        }
    )

    # 3. Coverage and backlog history, current rejected list
    coverage_out = coverage.rename(
        columns={
            "run_id": "Run ID",
            "source_table": "Source Table",
            "legacy_rows": "Legacy Rows",
            "migrated_rows": "Migrated Rows",
            "rejected_rows": "Rejected Rows",
            "merged_rows": "Merged Rows",
            "migrated_amount": "Migrated Amount",
            "amount_difference": "Amount Difference",
            "held_amount": "Held Amount",
        }
    )
    backlog_out = backlog.rename(
        columns={"run_id": "Run ID", "source_table": "Source Table", "reason": "Reason", "records": "Records", "amount": "Amount"}
    )
    rejected_out = pd.DataFrame(
        {
            "Source Table": rejected["source_table"],
            "Source ID": rejected["source_id"],
            "Reason": rejected["reason"],
            "Run ID": rejected["run_id"],
            "Rejected At": _local(rejected["rejected_at"]),
            "Amount": [abs(Decimal(a)) if a not in (None, "None") else None for a in rejected["amount"]],
        }
    )

    _write(runs_out, out / "runs.parquet")
    _write(pd.DataFrame(volumes), out / "run_volumes.parquet")
    _write(checks_out, out / "checks.parquet")
    _write(coverage_out, out / "coverage.parquet", ("Migrated Amount", "Amount Difference", "Held Amount"))
    _write(backlog_out, out / "backlog.parquet", ("Amount",))
    _write(rejected_out, out / "rejected_records.parquet", ("Amount",))
    _write(SOURCE_TABLES, out / "source_tables.parquet")
    return {"runs": len(runs_out), "checks": len(checks_out), "backlog": len(backlog_out), "rejected": len(rejected_out)}
