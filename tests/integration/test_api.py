from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from migration.api.app import app
from tests.integration.conftest import scalar

KEY = {"X-API-Key": "test-key"}


@pytest.fixture(scope="module")
def client(full_load):
    return TestClient(app)


def test_health_needs_no_key(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_endpoints_require_the_api_key(client):
    assert client.get("/migration/runs").status_code == 401
    assert client.get("/migration/runs", headers={"X-API-Key": "wrong"}).status_code == 401


def test_customer_profile_by_cpf_with_masked_cpf_and_money_as_text(client):
    cpf = scalar(
        "select cpf from core.customer c where exists (select 1 from core.account a where a.customer_id = c.customer_id) limit 1"
    )
    formatted = f"{cpf[:3]}.{cpf[3:6]}.{cpf[6:9]}-{cpf[9:]}"
    body = client.get(f"/customers/{formatted}", headers=KEY).json()
    assert body["cpf_masked"] == f"***.{cpf[3:6]}.{cpf[6:9]}-**"
    assert isinstance(body["total_balance"], str) and body["accounts"]


def test_invalid_and_unknown_cpf(client):
    assert client.get("/customers/111.111.111-11", headers=KEY).status_code == 422
    assert client.get("/customers/529.982.247-25", headers=KEY).status_code in (200, 404)


def test_statement_pages_with_a_cursor_without_gaps_or_repeats(client):
    account_id = scalar(
        "select account_id from core.transaction group by account_id having count(*) >= 7 order by account_id limit 1"
    )
    total = scalar("select count(*) from core.transaction where account_id = :a", a=account_id)
    seen, cursor = [], None
    while True:
        params = {"limit": 3, **({"cursor": cursor} if cursor else {})}
        body = client.get(f"/accounts/{account_id}/transactions", headers=KEY, params=params).json()
        seen += body["transactions"]
        cursor = body["next_cursor"]
        if not cursor:
            break
    assert len(seen) == total == len({t["transaction_id"] for t in seen})
    stamps = [t["posted_at"] for t in seen]
    assert stamps == sorted(stamps, reverse=True)


def test_unknown_account_and_bad_cursor(client):
    assert client.get("/accounts/00000000-0000-0000-0000-000000000000/transactions", headers=KEY).status_code == 404
    account_id = scalar("select account_id from core.transaction limit 1")
    assert client.get(f"/accounts/{account_id}/transactions", headers=KEY, params={"cursor": "xx"}).status_code == 422


def test_migration_runs_with_reconciliation_results(client):
    runs = client.get("/migration/runs", headers=KEY).json()
    assert runs and runs[0]["status"] in ("passed", "failed")
    detail = client.get(f"/migration/runs/{runs[-1]['run_id']}", headers=KEY).json()
    assert any(c["check_name"].startswith("Every legacy transaction") for c in detail["checks"])
    assert client.get("/migration/runs/999999", headers=KEY).status_code == 404
