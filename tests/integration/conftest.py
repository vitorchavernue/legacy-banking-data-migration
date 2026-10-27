"""Integration tests run against real databases (SQL Server, PostgreSQL, MongoDB in CI).

They are skipped when LEGACY_DB_URL is not set. ``make test-integration`` and the CI
workflow provide the connection strings.
"""

from __future__ import annotations

import os

import pytest
from sqlalchemy import text

if not os.environ.get("LEGACY_DB_URL"):
    pytest.skip("integration tests need LEGACY_DB_URL / TARGET_DB_URL / MONGO_URI", allow_module_level=True)

os.environ.setdefault("API_KEY", "test-key")


@pytest.fixture(scope="session")
def settings(tmp_path_factory):
    from migration.config import get_settings

    os.environ["REPORTS_DIR"] = str(tmp_path_factory.mktemp("reports"))
    get_settings.cache_clear()
    return get_settings()


@pytest.fixture(scope="session")
def fresh_systems(settings):
    """Legacy database recreated with synthetic data; target and MongoDB emptied."""
    from sqlalchemy.engine import make_url

    from migration.db import legacy_engine, mongo_db, target_engine
    from migration.legacy import seed

    url = make_url(settings.legacy_db_url)
    if url.get_backend_name() == "mssql":
        seed.create_database_if_missing(url.set(database="master"), url.database)
    counts = seed.load(legacy_engine(settings), seed.generate(scale=0.2))
    with target_engine(settings).begin() as conn:
        conn.execute(text("drop schema if exists core cascade"))
        conn.execute(text("drop schema if exists migration cascade"))
    mongo_db(settings).customer_profiles.drop()
    return counts


@pytest.fixture(scope="session")
def full_load(fresh_systems, settings):
    from migration.runner import run

    return run("full", settings)


def scalar(sql: str, **params):
    from migration.db import target_engine

    with target_engine().connect() as conn:
        return conn.execute(text(sql), params).scalar_one()
