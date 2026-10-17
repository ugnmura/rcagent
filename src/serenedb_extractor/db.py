"""SereneDB access: one reader and one writer connection (cancel support arrives with #10)."""

import re
import threading
from dataclasses import dataclass
from typing import Any

import psycopg

from serenedb_extractor.config import Settings
from serenedb_extractor.errors import UserFacingError

_NAME = re.compile(r"^[a-z][a-z0-9_]{0,40}$")


class QueryTimeout(UserFacingError):
    def __init__(self, seconds: float, what: str) -> None:
        super().__init__(f"TIMEOUT after {seconds:g}s: {what}")
        self.seconds = seconds
        self.what = what


class DatabaseUnreachable(UserFacingError):
    def __init__(self, setting: str, detail: str) -> None:
        detail = re.sub(r"\s+", " ", detail).strip() or "connection failed"
        super().__init__(f"Could not reach SereneDB using {setting}: {detail}")


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

    def __init__(self, url: str, setting: str) -> None:
        self.url = url
        self.setting = setting
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

    def run(self, sql: str, params: dict[str, Any] | None) -> Rows:
        with self.lock:
            try:
                cur = self.get().execute(sql, params)  # type: ignore[call-overload]
                if cur.description is None:
                    return Rows([], [])
                return Rows([d.name for d in cur.description], cur.fetchall())
            except psycopg.OperationalError as exc:
                self.close()  # drop a dead connection so the next call reconnects
                raise DatabaseUnreachable(self.setting, str(exc)) from exc


class Database:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._reader = _Conn(settings.reader_url, "SERENEDB_READER_URL")
        self._writer = (
            self._reader
            if settings.writer_url == settings.reader_url
            else _Conn(settings.writer_url, "SERENEDB_WRITER_URL")
        )

    def effective_timeout(self, requested: float | None) -> float:
        s = self.settings
        if requested is None or requested <= 0:
            return s.default_timeout_s
        return min(requested, s.max_timeout_s)

    def read(
        self, sql: str, params: dict[str, Any] | None = None, timeout_s: float | None = None, what: str = ""
    ) -> Rows:
        return self._execute(self._reader, sql, params, timeout_s)

    def write(
        self, sql: str, params: dict[str, Any] | None = None, timeout_s: float | None = None, what: str = ""
    ) -> Rows:
        return self._execute(self._writer, sql, params, timeout_s)

    def _execute(self, conn: _Conn, sql: str, params: dict[str, Any] | None, timeout_s: float | None) -> Rows:
        self.effective_timeout(timeout_s)  # enforced (server-side cancel) in #10
        return conn.run(sql, params)

    def copy_rows(self, table: str, columns: list[str], rows: list[tuple[Any, ...]], batch: int = 500) -> int:
        """Insert rows in batches through the writer; `table` may be schema-qualified."""
        table_sql = ".".join(quote_ident(p) for p in table.split("."))
        cols = ", ".join(quote_ident(c) for c in columns)
        total = 0
        for start in range(0, len(rows), batch):
            chunk = rows[start : start + batch]
            values = ", ".join(
                "(" + ", ".join(f"%(r{j}c{i})s" for i in range(len(columns))) + ")" for j in range(len(chunk))
            )
            params = {f"r{j}c{i}": v for j, row in enumerate(chunk) for i, v in enumerate(row)}
            self._writer.run(f"INSERT INTO {table_sql} ({cols}) VALUES {values}", params)
            total += len(chunk)
        return total

    def close(self) -> None:
        self._reader.close()
        self._writer.close()
