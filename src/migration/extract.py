"""Reads from the legacy database in pages, without locking or overloading it.

Pages use the primary key ("keyset pagination": WHERE id > last id ORDER BY id), which keeps
every round trip fast however large the table is, unlike OFFSET.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime

from sqlalchemy import Engine, Table, func, select

from migration.legacy.schema import PRIMARY_KEYS


def _pages(engine: Engine, table: Table, batch: int, *conditions) -> Iterator[list[dict]]:
    key = table.c[PRIMARY_KEYS[table.name]]
    last = None
    while True:
        query = select(table).where(*conditions).order_by(key).limit(batch)
        if last is not None:
            query = query.where(key > last)
        with engine.connect() as conn:
            rows = [dict(r._mapping) for r in conn.execute(query)]
        if not rows:
            return
        yield rows
        last = rows[-1][key.name]


def read_all(engine: Engine, table: Table, batch: int) -> Iterator[list[dict]]:
    """Full load: every row of the table."""
    yield from _pages(engine, table, batch)


def read_changed(engine: Engine, table: Table, since: datetime, batch: int) -> Iterator[list[dict]]:
    """Incremental load: rows changed since the watermark."""
    yield from _pages(engine, table, batch, table.c.DT_ULTIMA_ALTERACAO >= since)


def read_by_ids(engine: Engine, table: Table, ids: list[int], chunk: int = 1_000) -> list[dict]:
    """Specific rows (records rejected earlier, retried on every run)."""
    key = table.c[PRIMARY_KEYS[table.name]]
    rows: list[dict] = []
    with engine.connect() as conn:
        for start in range(0, len(ids), chunk):
            part = ids[start : start + chunk]
            rows += [dict(r._mapping) for r in conn.execute(select(table).where(key.in_(part)))]
    return rows


def max_modified(engine: Engine, table: Table) -> datetime | None:
    with engine.connect() as conn:
        return conn.execute(select(func.max(table.c.DT_ULTIMA_ALTERACAO))).scalar_one()
