"""Mapping from legacy rows to the new model (see docs/mapping.md).

Pure functions: rows in, clean rows plus rejected records out. No database access here,
so every rule is covered by fast unit tests.

New ids are deterministic (UUID v5): the same legacy record always gets the same new id,
so runs can be repeated safely and the two systems can be compared at any time.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from migration import rules
from migration.rules import RuleError

NAMESPACE = uuid.UUID("6f1c2b8e-4d3a-5e7f-9a1b-2c3d4e5f6a7b")


def customer_uuid(cpf: str) -> uuid.UUID:
    # Business key: one person (CPF) = one customer, however many legacy registrations
    return uuid.uuid5(NAMESPACE, f"customer:{cpf}")


def account_uuid(legacy_account_id: int) -> uuid.UUID:
    return uuid.uuid5(NAMESPACE, f"account:{legacy_account_id}")


@dataclass
class Rejected:
    source_table: str
    source_id: int
    reason: str
    payload: dict[str, Any]


@dataclass
class Result:
    rows: list[dict] = field(default_factory=list)
    rejected: list[Rejected] = field(default_factory=list)
    key_map: list[dict] = field(default_factory=list)  # customers only
    loaded_ids: list[int] = field(default_factory=list)  # legacy ids migrated in this batch


def to_json(row: dict) -> dict[str, Any]:
    """Legacy row as JSON (kept with the rejected record for analysis)."""
    return {k: (str(v) if isinstance(v, datetime | Decimal) else v) for k, v in row.items()}


def localize(value: datetime | None, tz: str) -> datetime | None:
    """Legacy timestamps have no offset: they are local time in the bank's time zone."""
    if value is None:
        return None
    return value.replace(tzinfo=ZoneInfo(tz)) if value.tzinfo is None else value


# 1. Customers ---------------------------------------------------------------------------


def transform_customers(rows: list[dict], tz: str) -> Result:
    """Clean customers and merge duplicate registrations of the same CPF.

    Rule: when a CPF appears more than once, the most recently changed registration wins
    and every legacy id is mapped to the same new customer (their accounts follow it).
    """
    result = Result()
    survivors: dict[str, dict] = {}
    for row in sorted(rows, key=lambda r: (r["DT_ULTIMA_ALTERACAO"], r["CD_CLIENTE"])):
        try:
            cpf = rules.normalize_cpf(row["NR_CPF"])
            clean = {
                "customer_id": customer_uuid(cpf),
                "cpf": cpf,
                "full_name": rules.normalize_name(row["NM_CLIENTE"]),
                "email": rules.normalize_email(row["DS_EMAIL"]),
                "birth_date": rules.parse_birth_date(row["DT_NASCIMENTO"]),
                "status": rules.map_code(row["CD_SITUACAO"], rules.CUSTOMER_STATUS, "customer status"),
                "source_updated_at": localize(row["DT_ULTIMA_ALTERACAO"], tz),
            }
        except RuleError as exc:
            result.rejected.append(Rejected("TB_CLIENTE", row["CD_CLIENTE"], str(exc), to_json(row)))
            continue
        survivors[cpf] = clean  # rows are sorted oldest -> newest, so the newest stays
        result.key_map.append({"legacy_customer_id": row["CD_CLIENTE"], "customer_id": clean["customer_id"]})
        result.loaded_ids.append(row["CD_CLIENTE"])
    result.rows = list(survivors.values())
    return result


# 2. Accounts ----------------------------------------------------------------------------


def transform_accounts(rows: list[dict], customer_by_legacy_id: dict[int, uuid.UUID], tz: str) -> Result:
    """Clean accounts and attach them to the migrated customer (after duplicate merge)."""
    result = Result()
    for row in rows:
        try:
            owner = customer_by_legacy_id.get(row["CD_CLIENTE"])
            if owner is None:
                raise RuleError("customer does not exist or was not migrated")
            number, digit = rules.split_account_number(row["NR_CONTA"])
            clean = {
                "account_id": account_uuid(row["CD_CONTA"]),
                "customer_id": owner,
                "legacy_account_id": row["CD_CONTA"],
                "branch": rules.normalize_branch(row["NR_AGENCIA"]),
                "account_number": number,
                "check_digit": digit,
                "account_type": rules.map_code(row["CD_TIPO"], rules.ACCOUNT_TYPE, "account type"),
                "status": rules.map_code(row["CD_SITUACAO"], rules.ACCOUNT_STATUS, "account status"),
                "opened_at": localize(row["DT_ABERTURA"], tz),
                "source_updated_at": localize(row["DT_ULTIMA_ALTERACAO"], tz),
            }
        except RuleError as exc:
            result.rejected.append(Rejected("TB_CONTA", row["CD_CONTA"], str(exc), to_json(row)))
            continue
        result.rows.append(clean)
        result.loaded_ids.append(row["CD_CONTA"])
    return result


# 3. Transactions ------------------------------------------------------------------------


def transform_transactions(
    rows: list[dict], account_by_legacy_id: dict[int, uuid.UUID], run_started_at: datetime, tz: str
) -> Result:
    """Signed amounts, valid account, no future dates, readable descriptions."""
    result = Result()
    for row in rows:
        try:
            account = account_by_legacy_id.get(row["CD_CONTA"])
            if account is None:
                raise RuleError("account does not exist or was not migrated")
            amount, direction = rules.signed_amount(row["VL_LANCAMENTO"], row["TP_LANCAMENTO"])
            posted_at = localize(row["DT_LANCAMENTO"], tz)
            if posted_at is None:
                raise RuleError("transaction date is missing")
            if posted_at > run_started_at:
                raise RuleError("transaction dated in the future")
            clean = {
                "transaction_id": row["CD_LANCAMENTO"],
                "account_id": account,
                "amount": amount,
                "direction": direction,
                "posted_at": posted_at,
                "description": rules.fix_encoding((row["DS_HISTORICO"] or "").strip()) or None,
                "source_updated_at": localize(row["DT_ULTIMA_ALTERACAO"], tz),
            }
        except RuleError as exc:
            result.rejected.append(Rejected("TB_LANCAMENTO", row["CD_LANCAMENTO"], str(exc), to_json(row)))
            continue
        result.rows.append(clean)
        result.loaded_ids.append(row["CD_LANCAMENTO"])
    return result
