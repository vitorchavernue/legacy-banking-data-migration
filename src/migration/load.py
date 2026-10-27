"""Writes into PostgreSQL and MongoDB. Every write is an upsert, so any run can be repeated."""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from decimal import Decimal

from bson.decimal128 import Decimal128
from pymongo import ReplaceOne
from pymongo.database import Database
from sqlalchemy import Connection, Table, delete, func, select, tuple_
from sqlalchemy.dialects.postgresql import insert

from migration import target_schema as t
from migration.transform import Rejected


def upsert(conn: Connection, table: Table, rows: list[dict], keys: list[str], newer_only: bool = True) -> int:
    """Insert new rows, update existing ones.

    ``newer_only``: an existing row is only overwritten by a version changed at the same time
    or later in the legacy system, so replaying an old batch never undoes a recent change.
    """
    if not rows:
        return 0
    for start in range(0, len(rows), 2_000):
        stmt = insert(table).values(rows[start : start + 2_000])
        updates = {c: stmt.excluded[c] for c in rows[0] if c not in keys}
        if "migrated_at" in table.c:
            updates["migrated_at"] = func.now()
        where = (table.c.source_updated_at <= stmt.excluded.source_updated_at) if newer_only else None
        conn.execute(stmt.on_conflict_do_update(index_elements=keys, set_=updates, where=where))
    return len(rows)


def save_rejected(conn: Connection, rejected: list[Rejected], run_id: int) -> None:
    rows = [
        {"source_table": r.source_table, "source_id": r.source_id, "reason": r.reason, "payload": r.payload, "run_id": run_id}
        for r in rejected
    ]
    upsert(conn, t.rejected_record, rows, ["source_table", "source_id"], newer_only=False)


def clear_rejected(conn: Connection, source_table: str, ids: list[int]) -> None:
    """Records migrated now leave the rejected list (they were fixed in the legacy system)."""
    for start in range(0, len(ids), 5_000):
        part = ids[start : start + 5_000]
        conn.execute(
            delete(t.rejected_record).where(
                tuple_(t.rejected_record.c.source_table, t.rejected_record.c.source_id).in_([(source_table, i) for i in part])
            )
        )


def rejected_ids(conn: Connection, source_table: str) -> list[int]:
    query = select(t.rejected_record.c.source_id).where(t.rejected_record.c.source_table == source_table)
    return [r[0] for r in conn.execute(query)]


def customer_map(conn: Connection) -> dict[int, uuid.UUID]:
    return dict(conn.execute(select(t.customer_key_map.c.legacy_customer_id, t.customer_key_map.c.customer_id)).all())


def account_map(conn: Connection) -> dict[int, uuid.UUID]:
    return dict(conn.execute(select(t.account.c.legacy_account_id, t.account.c.account_id)).all())


# --- MongoDB read model ------------------------------------------------------------------


def refresh_profiles(conn: Connection, mongo: Database, customer_ids: Iterable[uuid.UUID] | None = None) -> int:
    """Rebuild the customer profile documents read by the apps (customer + accounts + balances).

    ``customer_ids=None`` rebuilds every profile (full load); otherwise only the customers
    touched by the run.
    """
    ids = None if customer_ids is None else list(set(customer_ids))
    if ids == []:
        return 0
    c, a, tx = t.customer, t.account, t.transaction
    balances = (
        select(tx.c.account_id, func.sum(tx.c.amount).label("balance"), func.max(tx.c.posted_at).label("last_at"))
        .group_by(tx.c.account_id)
        .subquery()
    )
    query = (
        select(
            c,
            a.c.account_id,
            a.c.branch,
            a.c.account_number,
            a.c.check_digit,
            a.c.account_type,
            a.c.status.label("account_status"),
            balances.c.balance,
            balances.c.last_at,
        )
        .select_from(
            c.outerjoin(a, a.c.customer_id == c.c.customer_id).outerjoin(balances, balances.c.account_id == a.c.account_id)
        )
        .order_by(c.c.customer_id, a.c.branch, a.c.account_number)
    )
    docs: dict[uuid.UUID, dict] = {}
    chunks = [None] if ids is None else [ids[i : i + 5_000] for i in range(0, len(ids), 5_000)]
    for chunk in chunks:
        q = query if chunk is None else query.where(c.c.customer_id.in_(chunk))
        for row in conn.execute(q).mappings():
            doc = docs.setdefault(
                row["customer_id"],
                {
                    "_id": str(row["customer_id"]),
                    "cpf": row["cpf"],
                    "full_name": row["full_name"],
                    "email": row["email"],
                    "status": row["status"],
                    "accounts": [],
                    "total_balance": Decimal("0.00"),
                },
            )
            if row["account_id"] is not None:
                balance = row["balance"] or Decimal("0.00")
                doc["accounts"].append(
                    {
                        "account_id": str(row["account_id"]),
                        "branch": row["branch"],
                        "number": f"{row['account_number']}-{row['check_digit']}",
                        "type": row["account_type"],
                        "status": row["account_status"],
                        "balance": balance,
                        "last_transaction_at": row["last_at"],
                    }
                )
                doc["total_balance"] += balance
    if not docs:
        return 0
    ops = [ReplaceOne({"_id": d["_id"]}, _decimals(d), upsert=True) for d in docs.values()]
    for start in range(0, len(ops), 1_000):
        mongo.customer_profiles.bulk_write(ops[start : start + 1_000], ordered=False)
    mongo.customer_profiles.create_index("cpf", unique=True)
    return len(docs)


def _decimals(doc: dict) -> dict:
    """Money as Decimal128 in MongoDB (never float)."""
    out = dict(doc)
    out["total_balance"] = Decimal128(doc["total_balance"])
    out["accounts"] = [{**acc, "balance": Decimal128(acc["balance"])} for acc in doc["accounts"]]
    return out
