"""PostgreSQL fixtures: every test session gets its own throwaway database.

Safety: tests only run when TEST_PG_ADMIN_URL is set (a connection to a maintenance
database such as `postgres`). They CREATE a fresh `emg_test_<random>` database and
DROP it afterwards – the pipeline's own database is never touched.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, make_url

ADMIN_URL = os.getenv("TEST_PG_ADMIN_URL")


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        if "tests/integration" in str(item.fspath):
            item.add_marker(pytest.mark.integration)
            if not ADMIN_URL:
                item.add_marker(pytest.mark.skip(reason="TEST_PG_ADMIN_URL not set (see `make test-integration`)"))


@pytest.fixture(scope="session")
def pg_engine() -> Iterator[Engine]:
    admin_url = make_url(ADMIN_URL)
    name = f"emg_test_{uuid.uuid4().hex[:10]}"
    assert name != os.getenv("POSTGRES_DB"), "refusing to use the pipeline database"
    admin = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{name}"'))
    engine = create_engine(admin_url.set(database=name), future=True)
    try:
        yield engine
    finally:
        engine.dispose()
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


@pytest.fixture
def clean_db(pg_engine: Engine) -> Engine:
    """Empty schema before each test so tests are independent."""
    with pg_engine.begin() as conn:
        conn.execute(text("DROP SCHEMA IF EXISTS marts CASCADE; DROP SCHEMA public CASCADE; CREATE SCHEMA public"))
    return pg_engine
