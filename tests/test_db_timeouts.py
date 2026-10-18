"""Which timeout each kind of statement gets, and the connect timeout (R43, R44); no database needed."""

from dataclasses import replace
from typing import Any

import psycopg

from rcagent import db as dbmod
from rcagent.config import Settings
from rcagent.db import Database


def _db() -> Database:
    s = Settings.from_env({"SERENEDB_READER_URL": "postgresql://r@h/x", "SERENEDB_WRITER_URL": "postgresql://w@h/x"})
    return Database(replace(s, default_timeout_s=60.0, max_timeout_s=600.0))


def test_reads_default_and_writes_get_the_maximum(monkeypatch):
    seen: list[tuple[str, float | None]] = []

    def fake_run(self: Any, sql: str, params: Any, timeout_s: float | None = None, what: str = "", how_to_narrow: str = "", prepared: bool = False, zone: str | None = None) -> dbmod.Rows:
        seen.append((sql.split()[0], timeout_s))
        return dbmod.Rows([], [])

    monkeypatch.setattr(dbmod._Conn, "run", fake_run)
    d = _db()
    d.read("SELECT 1")
    d.read("SELECT 2", timeout_s=5)
    d.write("CREATE TABLE t (a INT)")
    d.write("DROP TABLE t", timeout_s=7)
    d.copy_rows("t", ["a"], [(1,)])
    assert seen == [("SELECT", 60.0), ("SELECT", 5), ("CREATE", 600.0), ("DROP", 7), ("INSERT", 600.0)]


def test_connect_is_bounded(monkeypatch):
    got: dict[str, Any] = {}

    def fake_connect(url: str, **kw: Any) -> Any:
        got.update(kw)
        raise psycopg.OperationalError("no route")

    monkeypatch.setattr(psycopg, "connect", fake_connect)
    d = _db()
    try:
        d.read("SELECT 1", timeout_s=5)
    except Exception:
        pass
    assert got["connect_timeout"] == 5
    d.read  # noqa: B018
    try:
        d.read("SELECT 1", timeout_s=500)
    except Exception:
        pass
    assert got["connect_timeout"] == dbmod.CONNECT_TIMEOUT_CAP_S
