"""End-to-end scenario, in order: full load -> repeat -> legacy changes -> incremental ->
someone edits the new database by hand -> the gate catches it -> a full run repairs it.
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select, text

from migration import alerts
from migration import target_schema as t
from migration.db import legacy_engine, mongo_db, target_engine
from migration.legacy.schema import accounts, customers, transactions
from migration.runner import run
from tests.integration.conftest import scalar


def critical_failures(result):
    return [c.name for c in result["checks"] if c.severity == "critical" and not c.passed]


def test_full_load_passes_the_reconciliation_gate(full_load, fresh_systems):
    assert full_load["status"] == "passed", critical_failures(full_load)
    stats = full_load["stats"]["tables"]
    for table, total in fresh_systems.items():
        assert stats[table]["read"] == total
        assert stats[table]["loaded"] + stats[table]["rejected"] == total


def test_duplicate_registrations_become_one_customer(full_load):
    registrations = scalar("select count(*) from migration.customer_key_map")
    people = scalar("select count(*) from core.customer")
    assert people < registrations
    assert scalar("select count(*) - count(distinct cpf) from core.customer") == 0


def test_every_customer_has_an_app_profile_with_matching_balances(full_load):
    mongo = mongo_db()
    assert mongo.customer_profiles.count_documents({}) == scalar("select count(*) from core.customer")
    doc = mongo.customer_profiles.find_one({"accounts.0": {"$exists": True}})
    account_id = doc["accounts"][0]["account_id"]
    expected = scalar("select coalesce(sum(amount), 0) from core.transaction where account_id = cast(:a as uuid)", a=account_id)
    assert Decimal(str(doc["accounts"][0]["balance"])) == expected


def test_running_the_full_load_again_changes_nothing(full_load, settings):
    before = scalar("select count(*) from core.transaction")
    again = run("full", settings)
    assert again["status"] == "passed"
    assert scalar("select count(*) from core.transaction") == before


def test_incremental_run_picks_up_legacy_changes(full_load, settings):
    from migration.legacy.seed import apply_changes

    rejected_customers = scalar("select count(*) from migration.rejected_record where source_table = 'TB_CLIENTE'")
    assert rejected_customers > 0  # customers with a wrong CPF were rejected by the full load
    changes = apply_changes(legacy_engine(settings))

    result = run("incremental", settings)
    assert result["status"] == "passed", critical_failures(result)
    # only the changed rows (plus earlier rejects) were read, not the whole legacy database
    assert result["stats"]["tables"]["TB_LANCAMENTO"]["read"] < 1_000
    # customers fixed by the branch are now migrated, and leave the rejected list
    assert scalar("select count(*) from migration.rejected_record where source_table = 'TB_CLIENTE'") == 0
    assert changes["new_customers"] == 10

    with legacy_engine(settings).connect() as conn:
        updated = conn.execute(
            select(customers.c.NR_CPF, customers.c.DS_EMAIL)
            .where(customers.c.DS_EMAIL.like("new.%"))
            .order_by(customers.c.CD_CLIENTE)
        ).first()
        closed = conn.execute(
            select(accounts.c.CD_CONTA).where(accounts.c.CD_SITUACAO == "E").order_by(accounts.c.CD_CONTA.desc())
        ).first()
        corrected = conn.execute(
            select(transactions.c.CD_LANCAMENTO, transactions.c.VL_LANCAMENTO, transactions.c.TP_LANCAMENTO)
            .where(transactions.c.VL_LANCAMENTO > 0)
            .order_by(transactions.c.CD_LANCAMENTO)
        ).first()
    from migration.rules import normalize_cpf, signed_amount

    profile = mongo_db().customer_profiles.find_one({"cpf": normalize_cpf(updated.NR_CPF)})
    assert profile["email"] == updated.DS_EMAIL
    assert scalar("select status from core.account where legacy_account_id = :a", a=closed.CD_CONTA) == "closed"
    expected, _ = signed_amount(corrected.VL_LANCAMENTO, corrected.TP_LANCAMENTO)
    assert scalar("select amount from core.transaction where transaction_id = :t", t=corrected.CD_LANCAMENTO) == expected


def test_the_gate_catches_a_manual_change_and_a_full_run_repairs_it(full_load, settings, monkeypatch):
    sent = []
    monkeypatch.setattr(alerts, "send", lambda url, title, lines: sent.append((title, lines)) or True)
    txn_id = scalar("select min(transaction_id) from core.transaction where source_updated_at < now() - interval '1 day'")
    with target_engine().begin() as conn:  # someone "fixes" a value directly in the new database
        conn.execute(text("update core.transaction set amount = amount + 0.01 where transaction_id = :t"), {"t": txn_id})

    result = run("incremental", settings)
    assert result["status"] == "failed"
    assert "Transactions match the legacy system field by field" in critical_failures(result)
    assert sent and "FAILED" in sent[0][0]

    repaired = run("full", settings)
    assert repaired["status"] == "passed", critical_failures(repaired)
    with target_engine().connect() as conn:
        runs = conn.execute(select(t.run.c.status).order_by(t.run.c.run_id)).scalars().all()
    assert runs[-2:] == ["failed", "passed"]
