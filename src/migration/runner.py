"""One migration run, from extraction to the reconciliation gate.

Order matters: customers -> accounts -> transactions (each step needs the previous one to
attach the records), then the MongoDB profiles, then reconciliation, report and alert.

* ``full``        reads every legacy row (initial load; safe to repeat).
* ``incremental`` reads only rows changed since the last watermark, plus every record that
                  was rejected before (it may have been fixed in the legacy system).
"""

from __future__ import annotations

import logging
import time
from collections.abc import Iterator
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import Engine, Table, insert, select, update
from sqlalchemy import func as sa_func

from migration import alerts, extract, load, reconcile, report
from migration import target_schema as t
from migration.config import Settings, get_settings
from migration.db import legacy_engine, mongo_db, target_engine
from migration.legacy.schema import accounts, customers, transactions
from migration.transform import transform_accounts, transform_customers, transform_transactions

log = logging.getLogger("migration.runner")


class NoFullLoadError(RuntimeError):
    """An incremental run needs the watermarks written by a full load."""


def _source_rows(
    legacy: Engine, table: Table, mode: str, since: datetime | None, retry: list[int], batch: int
) -> Iterator[list[dict]]:
    """Pages to process: everything (full) or changed rows + retried rejects (incremental)."""
    if mode == "full":
        yield from extract.read_all(legacy, table, batch)
        return
    seen: set[int] = set()
    key = extract.PRIMARY_KEYS[table.name]
    for page in extract.read_changed(legacy, table, since, batch):
        seen.update(r[key] for r in page)
        yield page
    retry = [i for i in retry if i not in seen]
    for start in range(0, len(retry), batch):
        page = extract.read_by_ids(legacy, table, retry[start : start + batch])
        if page:
            yield page


def run(mode: str = "full", settings: Settings | None = None, business_date: date | None = None) -> dict:
    if mode not in ("full", "incremental"):
        raise ValueError("mode must be 'full' or 'incremental'")
    settings = settings or get_settings()
    legacy, target, mongo = legacy_engine(settings), target_engine(settings), mongo_db(settings)
    tz = settings.legacy_timezone
    clock = time.monotonic()
    started = datetime.now(ZoneInfo(tz)).replace(microsecond=0)

    t.create_all(target)
    with target.begin() as conn:
        values = {"mode": mode, "status": "running", "business_date": business_date or started.date()}
        run_id = conn.execute(insert(t.run).values(**values).returning(t.run.c.run_id)).scalar_one()
    log.info("run %s started (%s)", run_id, mode)
    stats: dict = {"tables": {}}

    try:
        # 1. Where to start from (incremental): last watermark minus a safety overlap
        since: dict[str, datetime | None] = {}
        if mode == "incremental":
            with target.connect() as conn:
                marks = dict(conn.execute(select(t.watermark.c.source_table, t.watermark.c.last_modified)).all())
            if not marks:
                raise NoFullLoadError("no watermark found: run a full load first")
            overlap = timedelta(minutes=settings.watermark_overlap_minutes)
            since = {name: (marks[name] - overlap if name in marks else datetime(1900, 1, 1)) for name in marks}
        new_marks: dict[str, datetime] = {}

        def track(table: Table, rows: list[dict]) -> None:
            stamp = max((r["DT_ULTIMA_ALTERACAO"] for r in rows), default=None)
            if stamp and (table.name not in new_marks or stamp > new_marks[table.name]):
                new_marks[table.name] = stamp

        with target.connect() as conn:
            retry = {name: load.rejected_ids(conn, name) for name in ("TB_CLIENTE", "TB_CONTA", "TB_LANCAMENTO")}
        touched_customers: set = set()
        touched_accounts: set = set()

        # 2. Customers (all pages together: duplicates are merged across the whole batch)
        rows = [
            r
            for page in _source_rows(legacy, customers, mode, since.get("TB_CLIENTE"), retry["TB_CLIENTE"], settings.batch_size)
            for r in page
        ]
        track(customers, rows)
        result = transform_customers(rows, tz)
        with target.begin() as conn:
            load.upsert(conn, t.customer, result.rows, ["customer_id"])
            load.upsert(
                conn,
                t.customer_key_map,
                [{**k, "run_id": run_id} for k in result.key_map],
                ["legacy_customer_id"],
                newer_only=False,
            )
            load.save_rejected(conn, result.rejected, run_id)
            load.clear_rejected(conn, "TB_CLIENTE", result.loaded_ids)
        touched_customers.update(r["customer_id"] for r in result.rows)
        stats["tables"]["TB_CLIENTE"] = {"read": len(rows), "loaded": len(result.loaded_ids), "rejected": len(result.rejected)}

        # 3. Accounts, attached to the migrated (merged) customer
        with target.connect() as conn:
            owners = load.customer_map(conn)
        read = loaded = rejected = 0
        for page in _source_rows(legacy, accounts, mode, since.get("TB_CONTA"), retry["TB_CONTA"], settings.batch_size):
            track(accounts, page)
            result = transform_accounts(page, owners, tz)
            with target.begin() as conn:
                load.upsert(conn, t.account, result.rows, ["account_id"])
                load.save_rejected(conn, result.rejected, run_id)
                load.clear_rejected(conn, "TB_CONTA", result.loaded_ids)
            touched_customers.update(r["customer_id"] for r in result.rows)
            read, loaded, rejected = read + len(page), loaded + len(result.loaded_ids), rejected + len(result.rejected)
        stats["tables"]["TB_CONTA"] = {"read": read, "loaded": loaded, "rejected": rejected}

        # 4. Transactions, page by page (the largest table never sits in memory at once)
        with target.connect() as conn:
            account_ids = load.account_map(conn)
        read = loaded = rejected = 0
        for page in _source_rows(
            legacy, transactions, mode, since.get("TB_LANCAMENTO"), retry["TB_LANCAMENTO"], settings.batch_size
        ):
            track(transactions, page)
            result = transform_transactions(page, account_ids, started, tz)
            with target.begin() as conn:
                load.upsert(conn, t.transaction, result.rows, ["transaction_id"])
                load.save_rejected(conn, result.rejected, run_id)
                load.clear_rejected(conn, "TB_LANCAMENTO", result.loaded_ids)
            touched_accounts.update(r["account_id"] for r in result.rows)
            read, loaded, rejected = read + len(page), loaded + len(result.loaded_ids), rejected + len(result.rejected)
        stats["tables"]["TB_LANCAMENTO"] = {"read": read, "loaded": loaded, "rejected": rejected}

        # 5. App profiles in MongoDB (all of them, or only customers touched by this run)
        with target.connect() as conn:
            if mode == "incremental" and touched_accounts:
                owners_of = select(t.account.c.customer_id).where(t.account.c.account_id.in_(list(touched_accounts)))
                touched_customers.update(r[0] for r in conn.execute(owners_of))
            stats["profiles_refreshed"] = load.refresh_profiles(conn, mongo, None if mode == "full" else touched_customers)

        # 6. Watermarks move forward only after the data is safely loaded
        with target.begin() as conn:
            rows = [{"source_table": k, "last_modified": v, "run_id": run_id} for k, v in new_marks.items()]
            if rows:
                load.upsert(conn, t.watermark, rows, ["source_table"], newer_only=False)

        # 7. Reconciliation gate
        with target.connect() as conn:
            checks, snapshot = reconcile.run_checks(legacy, conn, mongo, tz)
        status = "passed" if reconcile.gate(checks) else "failed"
        stats["duration_s"] = round(time.monotonic() - clock, 1)
        with target.begin() as conn:
            conn.execute(
                t.reconciliation_check.insert(),
                [
                    {
                        "run_id": run_id,
                        "check_name": c.name,
                        "severity": c.severity,
                        "passed": c.passed,
                        "source_value": c.source_value,
                        "target_value": c.target_value,
                        "detail": c.detail,
                    }
                    for c in checks
                ],
            )
            # history for the monitoring dashboard: coverage per table and the rejected backlog
            conn.execute(t.run_coverage.insert(), [{"run_id": run_id, **row} for row in snapshot.coverage])
            if snapshot.backlog:
                conn.execute(t.backlog_snapshot.insert(), [{"run_id": run_id, **row} for row in snapshot.backlog])
            conn.execute(
                update(t.run).where(t.run.c.run_id == run_id).values(status=status, stats=stats, finished_at=sa_func.now())
            )
        path = report.write(settings.reports_dir, run_id, mode, status, stats, checks)
        log.info("run %s %s — report %s", run_id, status, path)
        if status == "failed":
            failed = [f"{c.name}: {c.detail or c.target_value}" for c in checks if c.severity == "critical" and not c.passed]
            alerts.send(settings.alert_webhook_url, f"Migration run {run_id} FAILED reconciliation", failed)
        return {"run_id": run_id, "status": status, "stats": stats, "checks": checks}

    except Exception as exc:
        with target.begin() as conn:
            conn.execute(
                update(t.run)
                .where(t.run.c.run_id == run_id)
                .values(status="error", error=str(exc)[:2000], finished_at=sa_func.now())
            )
        alerts.send(settings.alert_webhook_url, f"Migration run {run_id} stopped with an error", [str(exc)[:500]])
        raise
