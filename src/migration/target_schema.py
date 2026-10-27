"""New PostgreSQL model used by the applications, plus the tables that control the migration.

``core``      clean relational model with real constraints (keys, foreign keys, checks).
``migration`` run log, watermarks, id mapping, rejected records and reconciliation results.
"""

from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    MetaData,
    Numeric,
    String,
    Table,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

metadata = MetaData()
TS = DateTime(timezone=True)

# --- core: what the applications use ----------------------------------------------------

customer = Table(
    "customer",
    metadata,
    Column("customer_id", UUID(as_uuid=True), primary_key=True),
    Column("cpf", String(11), nullable=False, unique=True),
    Column("full_name", Text, nullable=False),
    Column("email", Text),
    Column("birth_date", Date),
    Column("status", Text, nullable=False),
    Column("source_updated_at", TS, nullable=False),
    Column("migrated_at", TS, nullable=False, server_default=text("now()")),
    CheckConstraint("status in ('active', 'inactive', 'blocked')", name="ck_customer_status"),
    schema="core",
)

account = Table(
    "account",
    metadata,
    Column("account_id", UUID(as_uuid=True), primary_key=True),
    Column("customer_id", UUID(as_uuid=True), ForeignKey("core.customer.customer_id"), nullable=False),
    Column("legacy_account_id", Integer, nullable=False, unique=True),
    Column("branch", String(4), nullable=False),
    Column("account_number", String(10), nullable=False),
    Column("check_digit", String(1), nullable=False),
    Column("account_type", Text, nullable=False),
    Column("status", Text, nullable=False),
    Column("opened_at", TS),
    Column("source_updated_at", TS, nullable=False),
    Column("migrated_at", TS, nullable=False, server_default=text("now()")),
    CheckConstraint("account_type in ('checking', 'savings')", name="ck_account_type"),
    CheckConstraint("status in ('active', 'closed')", name="ck_account_status"),
    schema="core",
)

transaction = Table(
    "transaction",
    metadata,
    Column("transaction_id", BigInteger, primary_key=True),  # same id as the legacy system
    Column("account_id", UUID(as_uuid=True), ForeignKey("core.account.account_id"), nullable=False, index=True),
    Column("amount", Numeric(15, 2), nullable=False),  # signed: credits > 0, debits < 0
    Column("direction", Text, nullable=False),
    Column("posted_at", TS, nullable=False),
    Column("description", Text),
    Column("source_updated_at", TS, nullable=False),
    Column("migrated_at", TS, nullable=False, server_default=text("now()")),
    CheckConstraint("direction in ('credit', 'debit')", name="ck_transaction_direction"),
    CheckConstraint(
        "(direction = 'credit' and amount > 0) or (direction = 'debit' and amount < 0)",
        name="ck_transaction_sign",
    ),
    schema="core",
)

# --- migration: control tables ----------------------------------------------------------

run = Table(
    "run",
    metadata,
    Column("run_id", Integer, primary_key=True, autoincrement=True),
    Column("mode", Text, nullable=False),  # full | incremental
    Column("status", Text, nullable=False),  # running | passed | failed | error
    Column("started_at", TS, nullable=False, server_default=text("now()")),
    Column("finished_at", TS),
    Column("stats", JSONB),
    Column("error", Text),
    schema="migration",
)

# Legacy customer id -> new customer. Two legacy ids can point to the same customer
# (duplicate registrations of the same CPF are merged).
customer_key_map = Table(
    "customer_key_map",
    metadata,
    Column("legacy_customer_id", Integer, primary_key=True),
    Column("customer_id", UUID(as_uuid=True), ForeignKey("core.customer.customer_id"), nullable=False),
    Column("run_id", Integer, nullable=False),
    schema="migration",
)

# Records that could not be migrated, with the reason. Retried on every run until fixed.
rejected_record = Table(
    "rejected_record",
    metadata,
    Column("source_table", Text, primary_key=True),
    Column("source_id", BigInteger, primary_key=True),
    Column("reason", Text, nullable=False),
    Column("payload", JSONB),
    Column("run_id", Integer, nullable=False),
    Column("rejected_at", TS, nullable=False, server_default=text("now()")),
    schema="migration",
)

# Last "changed at" value read from each legacy table (incremental sync)
watermark = Table(
    "watermark",
    metadata,
    Column("source_table", Text, primary_key=True),
    Column("last_modified", DateTime, nullable=False),
    Column("run_id", Integer, nullable=False),
    schema="migration",
)

reconciliation_check = Table(
    "reconciliation_check",
    metadata,
    Column("run_id", Integer, primary_key=True),
    Column("check_name", Text, primary_key=True),
    Column("severity", Text, nullable=False),
    Column("passed", Boolean, nullable=False),
    Column("source_value", Text),
    Column("target_value", Text),
    Column("detail", Text),
    schema="migration",
)


def create_all(engine) -> None:
    with engine.begin() as conn:
        conn.execute(text("create schema if not exists core"))
        conn.execute(text("create schema if not exists migration"))
    metadata.create_all(engine)
