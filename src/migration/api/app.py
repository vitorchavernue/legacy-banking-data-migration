"""Read-only API on top of the migrated data.

* Apps: customer profile (MongoDB) and account statement (PostgreSQL, paginated).
* Operations: migration runs and their reconciliation results.

Every endpoint except /health needs the ``X-API-Key`` header. Money is returned as text
(e.g. "1520.35") so no client ever rounds it through a float.
"""

from __future__ import annotations

import base64
import hmac
from datetime import datetime
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import and_, or_, select, text

from migration import rules
from migration import target_schema as t
from migration.config import get_settings
from migration.db import mongo_db, target_engine

app = FastAPI(title="Legacy banking migration API", version="1.0.0")


def require_api_key(x_api_key: Annotated[str | None, Header()] = None) -> None:
    # Constant-time comparison, so the key cannot be guessed by measuring response times
    if not x_api_key or not hmac.compare_digest(x_api_key, get_settings().api_key):
        raise HTTPException(status_code=401, detail="invalid or missing API key")


Auth = Depends(require_api_key)


# --- Response models ---------------------------------------------------------------------


class AccountSummary(BaseModel):
    account_id: str
    branch: str
    number: str
    type: str
    status: str
    balance: str
    last_transaction_at: datetime | None = None


class CustomerProfile(BaseModel):
    customer_id: str
    cpf_masked: str
    full_name: str
    email: str | None
    status: str
    total_balance: str
    accounts: list[AccountSummary]


class Transaction(BaseModel):
    transaction_id: int
    amount: str
    direction: str
    posted_at: datetime
    description: str | None


class Statement(BaseModel):
    account_id: UUID
    transactions: list[Transaction]
    next_cursor: str | None


class Check(BaseModel):
    check_name: str
    severity: str
    passed: bool
    source_value: str | None
    target_value: str | None
    detail: str | None


class Run(BaseModel):
    run_id: int
    mode: str
    status: str
    started_at: datetime
    finished_at: datetime | None
    stats: dict | None
    checks: list[Check] = []


# --- Endpoints ---------------------------------------------------------------------------


@app.get("/health")
def health() -> dict:
    """Both databases answer (used by the load balancer and monitoring)."""
    try:
        with target_engine().connect() as conn:
            conn.execute(text("select 1"))
        mongo_db().command("ping")
    except Exception as exc:  # noqa: BLE001 - any failure means unhealthy
        raise HTTPException(status_code=503, detail=f"unhealthy: {type(exc).__name__}") from exc
    return {"status": "ok"}


@app.get("/customers/{cpf}", response_model=CustomerProfile, dependencies=[Auth])
def customer_profile(cpf: str) -> CustomerProfile:
    try:
        clean = rules.normalize_cpf(cpf)
    except rules.RuleError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    doc = mongo_db().customer_profiles.find_one({"cpf": clean})
    if doc is None:
        raise HTTPException(status_code=404, detail="customer not found")
    return CustomerProfile(
        customer_id=doc["_id"],
        cpf_masked=f"***.{clean[3:6]}.{clean[6:9]}-**",  # never expose the full CPF
        full_name=doc["full_name"],
        email=doc.get("email"),
        status=doc["status"],
        total_balance=str(doc["total_balance"]),
        accounts=[AccountSummary(**{**a, "balance": str(a["balance"])}) for a in doc.get("accounts", [])],
    )


def _encode(posted_at: datetime, transaction_id: int) -> str:
    return base64.urlsafe_b64encode(f"{posted_at.isoformat()}|{transaction_id}".encode()).decode()


def _decode(cursor: str) -> tuple[datetime, int]:
    try:
        stamp, txn = base64.urlsafe_b64decode(cursor.encode()).decode().split("|")
        return datetime.fromisoformat(stamp), int(txn)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail="invalid cursor") from exc


@app.get("/accounts/{account_id}/transactions", response_model=Statement, dependencies=[Auth])
def statement(
    account_id: UUID,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: str | None = None,
) -> Statement:
    """Most recent first. ``next_cursor`` returns the following page (keyset pagination)."""
    tx = t.transaction
    query = select(tx).where(tx.c.account_id == account_id)
    if cursor:
        stamp, txn = _decode(cursor)
        query = query.where(or_(tx.c.posted_at < stamp, and_(tx.c.posted_at == stamp, tx.c.transaction_id < txn)))
    query = query.order_by(tx.c.posted_at.desc(), tx.c.transaction_id.desc()).limit(limit + 1)
    with target_engine().connect() as conn:
        exists = conn.execute(select(t.account.c.account_id).where(t.account.c.account_id == account_id)).first()
        if exists is None:
            raise HTTPException(status_code=404, detail="account not found")
        rows = conn.execute(query).mappings().all()
    page = rows[:limit]
    return Statement(
        account_id=account_id,
        transactions=[
            Transaction(
                transaction_id=r["transaction_id"],
                amount=str(Decimal(r["amount"])),
                direction=r["direction"],
                posted_at=r["posted_at"],
                description=r["description"],
            )
            for r in page
        ],
        next_cursor=_encode(page[-1]["posted_at"], page[-1]["transaction_id"]) if len(rows) > limit else None,
    )


@app.get("/migration/runs", response_model=list[Run], dependencies=[Auth])
def runs(limit: Annotated[int, Query(ge=1, le=100)] = 20) -> list[Run]:
    with target_engine().connect() as conn:
        rows = conn.execute(select(t.run).order_by(t.run.c.run_id.desc()).limit(limit)).mappings().all()
    return [Run(**r) for r in rows]


@app.get("/migration/runs/{run_id}", response_model=Run, dependencies=[Auth])
def run_detail(run_id: int) -> Run:
    with target_engine().connect() as conn:
        row = conn.execute(select(t.run).where(t.run.c.run_id == run_id)).mappings().first()
        if row is None:
            raise HTTPException(status_code=404, detail="run not found")
        checks = conn.execute(select(t.reconciliation_check).where(t.reconciliation_check.c.run_id == run_id)).mappings().all()
    return Run(**row, checks=[Check(**c) for c in checks])
