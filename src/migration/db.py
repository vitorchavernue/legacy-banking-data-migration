"""Connections to the three systems involved in the migration."""

from __future__ import annotations

from functools import lru_cache

from pymongo import MongoClient
from pymongo.database import Database
from sqlalchemy import Engine, create_engine

from migration.config import Settings, get_settings


@lru_cache
def _engine(url: str) -> Engine:
    return create_engine(url, pool_pre_ping=True, future=True)


def legacy_engine(settings: Settings | None = None) -> Engine:
    return _engine((settings or get_settings()).legacy_db_url)


def target_engine(settings: Settings | None = None) -> Engine:
    return _engine((settings or get_settings()).target_db_url)


@lru_cache
def _mongo_client(uri: str) -> MongoClient:
    # "mongomock://" gives an in-memory MongoDB for quick local runs without a server
    if uri.startswith("mongomock://"):
        import mongomock

        return mongomock.MongoClient()
    return MongoClient(uri, tz_aware=True)


def mongo_db(settings: Settings | None = None) -> Database:
    settings = settings or get_settings()
    return _mongo_client(settings.mongo_uri)[settings.mongo_db]
