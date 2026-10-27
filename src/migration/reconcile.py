"""Reconciliation: proves the new systems hold exactly what the legacy system holds.

Runs after every load. "Critical" checks are a release gate: if one fails, the run is marked
as failed, the alert is sent and the cut-over must not happen. "Info" checks document facts
the business needs to know (merged duplicates, money held in rejected records).
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from decimal import Decimal

from pymongo.database import Database
from sqlalchemy import Connection, Engine, select

from migration import rules
from migration import target_schema as t
from migration.legacy.schema import accounts as l_acc
from migration.legacy.schema import customers as l_cust
from migration.legacy.schema import transactions as l_txn
from migration.transform import localize


@dataclass
class Check:
    name: str
    severity: str  # critical | info
    passed: bool
    source_value: str = ""
    target_value: str = ""
    detail: str = ""


def _set(conn: Connection, column) -> set:
    return {r[0] for r in conn.execute(select(column))}


def _accounted(name: str, legacy: set, migrated: set, rejected: set) -> Check:
    """Every legacy id is either migrated or rejected, and nothing exists only in the target."""
    known = migrated | rejected
    missing, extra = legacy - known, known - legacy
    return Check(
        name,
        "critical",
        not missing and not extra,
        f"{len(legacy):,} legacy",
        f"{len(migrated):,} migrated + {len(rejected - migrated):,} rejected",
        f"missing {len(missing)}, only in target {len(extra)}" + (f" (e.g. {sorted(missing)[:5]})" if missing else ""),
    )


def run_checks(legacy: Engine, target: Connection, mongo: Database, tz: str) -> list[Check]:
    checks: list[Check] = []
    with legacy.connect() as src:
        legacy_customers = _set(src, l_cust.c.CD_CLIENTE)
        legacy_accounts = dict(src.execute(select(l_acc.c.CD_CONTA, l_acc.c.CD_CLIENTE)).all())
        legacy_txn = {
            r.CD_LANCAMENTO: r
            for r in src.execute(
                select(
                    l_txn.c.CD_LANCAMENTO, l_txn.c.CD_CONTA, l_txn.c.VL_LANCAMENTO, l_txn.c.TP_LANCAMENTO, l_txn.c.DT_LANCAMENTO
                )
            )
        }

    rejected = defaultdict(set)
    reasons: Counter = Counter()
    for table, source_id, reason in target.execute(
        select(t.rejected_record.c.source_table, t.rejected_record.c.source_id, t.rejected_record.c.reason)
    ):
        rejected[table].add(source_id)
        reasons[f"{table}: {reason}"] += 1

    key_map = dict(target.execute(select(t.customer_key_map.c.legacy_customer_id, t.customer_key_map.c.customer_id)).all())
    target_customers = _set(target, t.customer.c.customer_id)
    target_accounts = {
        r.legacy_account_id: r
        for r in target.execute(select(t.account.c.legacy_account_id, t.account.c.account_id, t.account.c.customer_id))
    }
    account_by_uuid = {r.account_id: legacy_id for legacy_id, r in target_accounts.items()}
    target_txn = {
        r.transaction_id: r
        for r in target.execute(
            select(t.transaction.c.transaction_id, t.transaction.c.account_id, t.transaction.c.amount, t.transaction.c.posted_at)
        )
    }

    # 1. Completeness: nothing lost, nothing invented
    checks.append(
        _accounted("Every legacy customer is migrated or rejected", legacy_customers, set(key_map), rejected["TB_CLIENTE"])
    )
    checks.append(
        _accounted(
            "Every legacy account is migrated or rejected", set(legacy_accounts), set(target_accounts), rejected["TB_CONTA"]
        )
    )
    checks.append(
        _accounted(
            "Every legacy transaction is migrated or rejected", set(legacy_txn), set(target_txn), rejected["TB_LANCAMENTO"]
        )
    )

    merged = len(key_map) - len(target_customers)
    checks.append(
        Check(
            "Duplicate registrations merged (same CPF)",
            "info",
            True,
            f"{len(key_map):,} registrations",
            f"{len(target_customers):,} customers",
            f"{merged:,} duplicates merged into existing customers",
        )
    )

    # 2. Relationships: each account belongs to the customer its legacy owner was mapped to
    wrong_owner = [
        legacy_id for legacy_id, acc in target_accounts.items() if key_map.get(legacy_accounts.get(legacy_id)) != acc.customer_id
    ]
    checks.append(
        Check(
            "Accounts belong to the right customer",
            "critical",
            not wrong_owner,
            detail=f"{len(wrong_owner)} accounts with a different owner",
        )
    )

    # 3. Row by row: amount (with sign), date and account of every migrated transaction
    mismatched = []
    source_total = target_total = Decimal("0")
    for txn_id, tgt in target_txn.items():
        src = legacy_txn.get(txn_id)
        if src is None:
            continue
        try:
            expected, _ = rules.signed_amount(src.VL_LANCAMENTO, src.TP_LANCAMENTO)
        except rules.RuleError:  # changed to an invalid value after it was migrated
            mismatched.append(txn_id)
            continue
        source_total += expected
        target_total += tgt.amount
        same = (
            expected == tgt.amount
            and localize(src.DT_LANCAMENTO, tz) == tgt.posted_at
            and src.CD_CONTA == account_by_uuid.get(tgt.account_id)
        )
        if not same:
            mismatched.append(txn_id)
    checks.append(
        Check(
            "Transactions match the legacy system field by field",
            "critical",
            not mismatched,
            f"{len(target_txn):,} compared",
            f"{len(mismatched)} different",
            f"e.g. {mismatched[:5]}" if mismatched else "amount, sign, date and account",
        )
    )
    checks.append(
        Check(
            "Net amount of migrated transactions matches",
            "critical",
            source_total == target_total,
            f"{source_total:,.2f}",
            f"{target_total:,.2f}",
        )
    )
    held = Decimal("0")
    for txn_id in rejected["TB_LANCAMENTO"] - set(target_txn):
        row = legacy_txn.get(txn_id)
        if row is not None and row.VL_LANCAMENTO is not None:
            held += abs(Decimal(row.VL_LANCAMENTO))
    checks.append(
        Check(
            "Money in rejected transactions (needs business review)",
            "info",
            True,
            f"{len(rejected['TB_LANCAMENTO']):,} transactions",
            f"{held:,.2f}",
        )
    )

    # 4. MongoDB read model: one profile per customer, balances equal to PostgreSQL
    balances: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    for tgt in target_txn.values():
        balances[str(tgt.account_id)] += tgt.amount
    profiles = list(mongo.customer_profiles.find({}, {"accounts.account_id": 1, "accounts.balance": 1}))
    profile_ids = {p["_id"] for p in profiles}
    checks.append(
        Check(
            "Every customer has an app profile (MongoDB)",
            "critical",
            profile_ids == {str(c) for c in target_customers},
            f"{len(target_customers):,} customers",
            f"{len(profile_ids):,} profiles",
        )
    )
    wrong_balance = [
        acc["account_id"]
        for p in profiles
        for acc in p.get("accounts", [])
        if Decimal(str(acc["balance"])) != balances[acc["account_id"]]
    ]
    checks.append(
        Check(
            "App balances match PostgreSQL",
            "critical",
            not wrong_balance,
            detail=f"{len(wrong_balance)} accounts with a different balance",
        )
    )

    # 5. What still needs fixing in the legacy system
    top = "; ".join(f"{k} = {v}" for k, v in reasons.most_common(6)) or "none"
    checks.append(Check("Rejected records by reason", "info", True, detail=top))
    return checks


def gate(checks: list[Check]) -> bool:
    return all(c.passed for c in checks if c.severity == "critical")
