"""Minimal DB fixtures; a later ticket replaces `database` with the real Database class."""

import os
from collections.abc import Iterator
from typing import Any

import psycopg
import pytest


class _Rows:
    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self.rows = rows

    def scalar(self) -> Any:
        return self.rows[0][0]


class _Database:
    def __init__(self, conn: psycopg.Connection[Any]) -> None:
        self._conn = conn

    def read(self, sql: str, params: dict[str, Any] | None = None) -> _Rows:
        cur = self._conn.execute(sql, params)
        return _Rows(cur.fetchall())


@pytest.fixture
def db_url() -> str:
    url = os.environ.get("SERENEDB_TEST_URL")
    if not url:
        pytest.skip("SERENEDB_TEST_URL not set")
    return url


@pytest.fixture
def database(db_url: str) -> Iterator[_Database]:
    conn = psycopg.connect(db_url, autocommit=True, cursor_factory=psycopg.ClientCursor)
    try:
        yield _Database(conn)
    finally:
        conn.close()
