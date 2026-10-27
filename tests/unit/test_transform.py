from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from migration.transform import (
    account_uuid,
    customer_uuid,
    transform_accounts,
    transform_customers,
    transform_transactions,
)

TZ = "America/Sao_Paulo"
NOW = datetime(2026, 10, 1, 12, 0, 0)


def customer(cid, cpf, changed, name="ANA SILVA", email="ana@example.com"):
    return {
        "CD_CLIENTE": cid,
        "NM_CLIENTE": name,
        "NR_CPF": cpf,
        "DS_EMAIL": email,
        "DT_NASCIMENTO": "01/01/1980",
        "CD_SITUACAO": "A",
        "DT_ULTIMA_ALTERACAO": changed,
    }


def test_duplicate_registrations_merge_and_the_newest_wins():
    rows = [
        customer(1, "529.982.247-25", NOW - timedelta(days=10), email="new@example.com"),
        customer(2, "52998224725", NOW - timedelta(days=200), email="old@example.com"),
    ]
    result = transform_customers(rows, TZ)
    assert len(result.rows) == 1
    assert result.rows[0]["email"] == "new@example.com"
    # both legacy registrations point to the same new customer
    assert {m["customer_id"] for m in result.key_map} == {customer_uuid("52998224725")}
    assert sorted(result.loaded_ids) == [1, 2]


def test_invalid_customer_is_rejected_with_the_original_row():
    result = transform_customers([customer(3, "529.982.247-26", NOW)], TZ)
    assert result.rows == []
    rejected = result.rejected[0]
    assert (rejected.source_table, rejected.source_id) == ("TB_CLIENTE", 3)
    assert "check digits" in rejected.reason
    assert rejected.payload["NR_CPF"] == "529.982.247-26"


def test_new_ids_are_deterministic():
    assert customer_uuid("52998224725") == customer_uuid("52998224725")
    assert account_uuid(10) != account_uuid(11)


def account(aid, owner, number="12345-6"):
    return {
        "CD_CONTA": aid,
        "CD_CLIENTE": owner,
        "NR_AGENCIA": "1",
        "NR_CONTA": number,
        "CD_TIPO": "CC",
        "DT_ABERTURA": NOW,
        "CD_SITUACAO": "A",
        "DT_ULTIMA_ALTERACAO": NOW,
    }


def test_account_follows_the_merged_customer_and_orphans_are_rejected():
    owner = customer_uuid("52998224725")
    result = transform_accounts([account(10, 2), account(11, 999)], {1: owner, 2: owner}, TZ)
    assert [r["customer_id"] for r in result.rows] == [owner]
    assert result.rows[0]["branch"] == "0001"
    assert result.rows[0]["opened_at"].tzinfo == ZoneInfo(TZ)
    assert result.rejected[0].reason == "customer does not exist or was not migrated"


def txn(tid, amount, kind="D", posted=NOW - timedelta(days=1), account_id=10, history="COMPRA"):
    return {
        "CD_LANCAMENTO": tid,
        "CD_CONTA": account_id,
        "VL_LANCAMENTO": Decimal(amount),
        "TP_LANCAMENTO": kind,
        "DT_LANCAMENTO": posted,
        "DS_HISTORICO": history,
        "DT_ULTIMA_ALTERACAO": NOW,
    }


def test_transactions_are_signed_and_invalid_ones_rejected():
    started = NOW.replace(tzinfo=ZoneInfo(TZ))
    rows = [
        txn(1, "100.00", "C"),
        txn(2, "40.00", "D", history="TRANSFERÃŠNCIA"),
        txn(3, "0.00"),
        txn(4, "5.00", posted=NOW + timedelta(days=3)),
        txn(5, "5.00", account_id=77),
    ]
    result = transform_transactions(rows, {10: account_uuid(10)}, started, TZ)
    assert [(r["transaction_id"], r["amount"]) for r in result.rows] == [(1, Decimal("100.00")), (2, Decimal("-40.00"))]
    assert result.rows[1]["description"] == "TRANSFERÊNCIA"
    assert {r.source_id: r.reason for r in result.rejected} == {
        3: "amount must be greater than zero",
        4: "transaction dated in the future",
        5: "account does not exist or was not migrated",
    }
