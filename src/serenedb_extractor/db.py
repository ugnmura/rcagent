"""SereneDB access: one reader and one writer connection (cancel support arrives with #10)."""

import re
import threading
from dataclasses import dataclass
from typing import Any

import psycopg

from serenedb_extractor.config import Settings

_NAME = re.compile(r"^[a-z][a-z0-9_]{0,40}$")


class QueryTimeout(Exception):
    def __init__(self, seconds: float, what: str) -> None:
        super().__init__(f"TIMEOUT after {seconds:g}s: {what}")
        self.seconds = seconds
        self.what = what


@dataclass(frozen=True)
class Rows:
    columns: list[str]
    rows: list[tuple[Any, ...]]

    def dicts(self) -> list[dict[str, Any]]:
        return [dict(zip(self.columns, r, strict=True)) for r in self.rows]

    def scalar(self) -> Any:
        return self.rows[0][0] if self.rows else None


def quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def validate_name(name: str) -> str:
    if not _NAME.match(name):
        raise ValueError(
            f"'{name}' is not a usable name: start with a lowercase letter, then lowercase "
            "letters, digits or underscores (at most 41 characters)."
        )
    return name


class _Conn:
    """A lazily opened, serialized autocommit connection."""

    def __init__(self, url: str) -> None:
        self.url = url
        self.lock = threading.RLock()
        self._conn: psycopg.Connection[Any] | None = None

    def get(self) -> psycopg.Connection[Any]:
        if self._conn is None or self._conn.closed:
            self._conn = psycopg.connect(self.url, autocommit=True, cursor_factory=psycopg.ClientCursor)
        return self._conn

    def close(self) -> None:
        with self.lock:
            if self._conn is not None and not self._conn.closed:
                self._conn.close()
            self._conn = None


class Database:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._reader = _Conn(settings.reader_url)
        self._writer = self._reader if settings.writer_url == settings.reader_url else _Conn(settings.writer_url)

    def effective_timeout(self, requested: float | None) -> float:
        s = self.settings
        if requested is None or requested <= 0:
            return s.default_timeout_s
        return min(requested, s.max_timeout_s)

    def read(
        self, sql: str, params: dict[str, Any] | None = None, timeout_s: float | None = None, what: str = ""
    ) -> Rows:
        self.effective_timeout(timeout_s)  # enforced (server-side cancel) in #10
        return self._run(self._reader, sql, params)

    def write(
        self, sql: str, params: dict[str, Any] | None = None, timeout_s: float | None = None, what: str = ""
    ) -> Rows:
        self.effective_timeout(timeout_s)
        return self._run(self._writer, sql, params)

    def copy_rows(self, table: str, columns: list[str], rows: list[tuple[Any, ...]], batch: int = 500) -> int:
        """Insert rows in batches through the writer; `table` may be schema-qualified."""
        if not rows:
            return 0
        table_sql = ".".join(quote_ident(p) for p in table.split("."))
        cols = ", ".join(quote_ident(c) for c in columns)
        marks = ", ".join(f"%(c{i})s" for i in range(len(columns)))
        total = 0
        with self._writer.lock:
            conn = self._writer.get()
            for start in range(0, len(rows), batch):
                chunk = rows[start : start + batch]
                values = ", ".join(f"({marks.replace('%(c', '%(r' + str(j) + 'c')})" for j in range(len(chunk)))
                params = {f"r{j}c{i}": v for j, row in enumerate(chunk) for i, v in enumerate(row)}
                conn.execute(f"INSERT INTO {table_sql} ({cols}) VALUES {values}", params)  # type: ignore[call-overload]
                total += len(chunk)
        return total

    @staticmethod
    def _run(c: _Conn, sql: str, params: dict[str, Any] | None) -> Rows:
        with c.lock:
            try:
                cur = c.get().execute(sql, params)  # type: ignore[call-overload]
                if cur.description is None:
                    return Rows([], [])
                return Rows([d.name for d in cur.description], cur.fetchall())
            except psycopg.OperationalError:
                c.close()  # drop a dead connection so the next call reconnects
                raise

    def close(self) -> None:
        self._reader.close()
        self._writer.close()
