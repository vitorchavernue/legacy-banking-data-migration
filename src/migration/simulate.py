"""Cut-over rehearsal: two weeks of daily runs, as they happen before the systems are switched.

Day 1 is the full load. Every following business day:

* the legacy system keeps running (new customers, transactions, corrections)
* the business fixes part of the rejected records at the source, and a few new defects appear
* an incremental run moves the changes and the fixed records, then the reconciliation gate runs

On one day someone edits a value directly in the new database: the gate fails, the alert goes
out, and the next day a full run repairs it. The run history feeds the monitoring dashboard.
"""

from __future__ import annotations

import random
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select, text
from sqlalchemy.engine import make_url

from migration.config import Settings, get_settings
from migration.db import legacy_engine, mongo_db, target_engine
from migration.legacy import seed
from migration.legacy.schema import accounts, transactions
from migration.runner import run


def business_days(start: date, count: int) -> list[date]:
    days, day = [], start
    while len(days) < count:
        if day.weekday() < 5:
            days.append(day)
        day += timedelta(days=1)
    return days


def add_new_defects(engine, count: int, seed_: int) -> int:
    """New problems keep arriving while the old ones are fixed (zero amounts, typing errors)."""
    rng = random.Random(seed_)
    now = datetime.now().replace(microsecond=0)
    with engine.begin() as conn:
        account_ids = [r[0] for r in conn.execute(select(accounts.c.CD_CONTA))]
        next_id = conn.execute(select(func.max(transactions.c.CD_LANCAMENTO))).scalar_one()
        for i in range(1, count + 1):
            conn.execute(
                transactions.insert(),
                {
                    "CD_LANCAMENTO": next_id + i,
                    "CD_CONTA": rng.choice(account_ids),
                    "VL_LANCAMENTO": Decimal("0.00"),
                    "TP_LANCAMENTO": "D",
                    "DT_LANCAMENTO": now - timedelta(hours=rng.randint(1, 48)),
                    "DS_HISTORICO": "TARIFA",
                    "DT_ULTIMA_ALTERACAO": now,
                },
            )
    return count


def simulate(
    days: int = 10,
    start: date = date(2026, 11, 2),
    tamper_day: int | None = 6,
    fix_share: float = 0.3,
    scale: float = 1.0,
    settings: Settings | None = None,
) -> list[dict]:
    settings = settings or get_settings()
    # Runs follow each other in seconds here, so no re-read window is needed between them
    sim = settings.model_copy(update={"watermark_overlap_minutes": 0})
    legacy, target = legacy_engine(sim), target_engine(sim)

    # 1. Fresh start: legacy database with synthetic data, empty new systems
    url = make_url(sim.legacy_db_url)
    if url.get_backend_name() == "mssql":
        seed.create_database_if_missing(url.set(database="master"), url.database)
    seed.load(legacy, seed.generate(scale=scale))
    with target.begin() as conn:
        conn.execute(text("drop schema if exists core cascade"))
        conn.execute(text("drop schema if exists migration cascade"))
    mongo_db(sim).customer_profiles.drop()

    # 2. One run per business day
    results = []
    for number, day in enumerate(business_days(start, days), start=1):
        mode = "full"
        if number > 1:
            seed.apply_changes(legacy, seed=number, fix_cpfs=False)
            seed.fix_some_defects(legacy, fix_share, seed=number)
            add_new_defects(legacy, 3, seed_=number)
            mode = "incremental"
        if tamper_day and number == tamper_day:
            with target.begin() as conn:  # a manual "fix" straight in the new database
                conn.execute(
                    text(
                        "update core.transaction set amount = amount + 0.01 where transaction_id = "
                        "(select transaction_id from core.transaction order by transaction_id offset 500 limit 1)"
                    )
                )
        if tamper_day and number == tamper_day + 1:
            mode = "full"  # the repair: a full run rewrites the edited row from the legacy system
        results.append(run(mode, sim, business_date=day))
    return results
