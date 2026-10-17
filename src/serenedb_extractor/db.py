"""SereneDB access: one reader and one writer connection; every query runs under a timeout that
cancels it inside SereneDB (Postgres cancel request from a timer thread, spike section 2)."""

import logging
import math
import re
import threading
from dataclasses import dataclass
from typing import Any

import psycopg
from psycopg.types.datetime import TimestampLoader, TimestamptzLoader

from serenedb_extractor.config import Settings
from serenedb_extractor.errors import UserFacingError
from serenedb_extractor.format import timeout_message

_NAME = re.compile(r"^[a-z][a-z0-9_]{0,40}$")


DEFAULT_NARROW = "narrow it: a shorter period (start/end) or more filters (level, service), then try again."
CONNECT_TIMEOUT_CAP_S = 30  # libpq connect_timeout (whole seconds, at least 2): the query timeout, at most this
CANCEL_TIMEOUT_S = 2.0  # how long the cancel request may take; finish() can wait at most this long for it


_SUB_MICROSECOND = re.compile(rb"(\.\d{6})\d+")


def _to_microseconds(data: Any) -> bytes:
    """A timestamp in text form with its fraction cut to 6 digits: nanosecond columns come back
    with 9, which psycopg can't parse (spike section 5)."""
    return _SUB_MICROSECOND.sub(rb"\1", bytes(data), count=1)


class _NsTimestampLoader(TimestampLoader):
    def load(self, data: Any) -> Any:
        return super().load(_to_microseconds(data))


class _NsTimestamptzLoader(TimestamptzLoader):
    def load(self, data: Any) -> Any:
        return super().load(_to_microseconds(data))


class QueryCancelledElsewhere(UserFacingError):
    def __init__(self) -> None:
        super().__init__("The query was cancelled by the database.")


class QueryTimeout(UserFacingError):
    """The query ran past its timeout and was cancelled in SereneDB; the connection stays usable."""

    def __init__(self, seconds: float, what: str, how_to_narrow: str = DEFAULT_NARROW) -> None:
        super().__init__(timeout_message(seconds, what or "the query", how_to_narrow))
        self.seconds = seconds
        self.what = what
        self.how_to_narrow = how_to_narrow


class DatabaseUnreachable(UserFacingError):
    def __init__(self, setting: str, detail: str) -> None:
        detail = re.sub(r"\s+", " ", detail).strip() or "connection failed"
        super().__init__(f"Could not reach SereneDB using {setting}: {detail}")


class PermissionRefused(UserFacingError):
    """SereneDB refused a statement to the role of one connection (SQLSTATE 42501)."""

    def __init__(self, setting: str, detail: str) -> None:
        detail = re.sub(r"\s+", " ", detail).strip()[:300] or "permission denied"
        if setting == "SERENEDB_WRITER_URL":
            needs = "the writer needs CREATE on the database (to create schema extractor) and to own schema extractor"
        else:
            needs = (
                "the reader needs USAGE on schema extractor and SELECT on its tables, "
                "granted again after each new log table"
            )
        super().__init__(
            f"SereneDB refused this to the role in {setting}: {detail}. Grant it access as in the README's "
            f"\"Reader and writer roles\" section: {needs}."
        )


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
        raise UserFacingError(
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

    def get(self, timeout_s: float | None = None) -> psycopg.Connection[Any]:
        if self._conn is None or self._conn.closed:
            limit = CONNECT_TIMEOUT_CAP_S if timeout_s is None else min(timeout_s, CONNECT_TIMEOUT_CAP_S)
            self._conn = psycopg.connect(
                self.url,
                autocommit=True,
                cursor_factory=psycopg.ClientCursor,
                connect_timeout=max(2, math.ceil(limit)),  # a hung connect is bounded too
            )
            self._conn.adapters.register_loader("timestamp", _NsTimestampLoader)
            self._conn.adapters.register_loader("timestamptz", _NsTimestamptzLoader)
        return self._conn

    def close(self) -> None:
        with self.lock:
            if self._conn is not None and not self._conn.closed:
                self._conn.close()
            self._conn = None

    def run(
        self,
        sql: str,
        params: dict[str, Any] | None,
        timeout_s: float | None = None,
        what: str = "",
        how_to_narrow: str = DEFAULT_NARROW,
        prepared: bool = False,
    ) -> Rows:
        """Run one statement; past `timeout_s` it is cancelled in SereneDB and QueryTimeout is raised.
        `prepared`: use the extended protocol (server-side parsing), so the server itself refuses a
        string holding several statements; for untrusted SQL (run_sql)."""
        with self.lock:
            canceller = _Canceller(self, timeout_s)
            try:
                pg = self.get(timeout_s)
                if prepared:
                    cur = psycopg.Cursor(pg)
                    cur.execute(sql, params, prepare=True)  # type: ignore[call-overload]
                else:
                    cur = pg.execute(sql, params)  # type: ignore[call-overload]
                if cur.description is None:
                    return Rows([], [])
                return Rows([d.name for d in cur.description], cur.fetchall())
            except psycopg.errors.InsufficientPrivilege as exc:
                raise PermissionRefused(self.setting, str(exc).splitlines()[0] if str(exc) else "") from exc
            except psycopg.errors.QueryCanceled:
                if canceller.fired and timeout_s is not None:
                    raise QueryTimeout(timeout_s, what, how_to_narrow) from None
                raise QueryCancelledElsewhere() from None  # not our timer: an operator or the server
            except psycopg.OperationalError as exc:
                if canceller.fired and timeout_s is not None:  # the cancel failed and the timer closed the link
                    self.close()
                    raise QueryTimeout(timeout_s, what, how_to_narrow) from None
                conn = self._conn
                if exc.sqlstate is not None and conn is not None and not conn.closed and not conn.broken:
                    raise  # SereneDB answered with an error (e.g. a file could not be read): not a dead link
                self.close()  # drop a dead connection so the next call reconnects
                raise DatabaseUnreachable(self.setting, str(exc)) from exc
            finally:
                canceller.finish()


class _Canceller:
    """Sends a cancel request for the connection's running statement once the timeout passes.

    `finish()` is called (under the connection lock) as soon as the statement returns, so a late
    timer never cancels the next statement on the same connection.
    """

    def __init__(self, conn: _Conn, timeout_s: float | None) -> None:
        self._conn = conn
        self._guard = threading.Lock()
        self._done = False
        self.fired = False
        self._timer: threading.Timer | None = None
        if timeout_s is not None and timeout_s > 0:
            self._timer = threading.Timer(timeout_s, self._fire)
            self._timer.daemon = True
            self._timer.start()

    def _fire(self) -> None:
        with self._guard:
            pg = self._conn._conn
            if self._done or pg is None or pg.closed:
                return
            self.fired = True
            try:
                pg.cancel_safe(timeout=CANCEL_TIMEOUT_S)
            except Exception:  # cancel failed: fall back to dropping the connection (spike section 2)
                logging.getLogger("serenedb_extractor").warning("cancel request failed; closing the connection")
                pg.close()

    def finish(self) -> None:
        with self._guard:
            self._done = True
        if self._timer is not None:
            self._timer.cancel()


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
        self,
        sql: str,
        params: dict[str, Any] | None = None,
        timeout_s: float | None = None,
        what: str = "",
        how_to_narrow: str = DEFAULT_NARROW,
        prepared: bool = False,
    ) -> Rows:
        return self._execute(
            self._reader, sql, params, timeout_s, what, how_to_narrow, self.settings.default_timeout_s, prepared
        )

    def write(
        self,
        sql: str,
        params: dict[str, Any] | None = None,
        timeout_s: float | None = None,
        what: str = "",
        how_to_narrow: str = DEFAULT_NARROW,
    ) -> Rows:
        return self._execute(self._writer, sql, params, timeout_s, what, how_to_narrow, self.settings.max_timeout_s)

    def _execute(
        self,
        conn: _Conn,
        sql: str,
        params: dict[str, Any] | None,
        timeout_s: float | None,
        what: str,
        how_to_narrow: str,
        default_s: float,
        prepared: bool = False,
    ) -> Rows:
        """Every statement runs under a timeout. Reads default to the query timeout (60 s); writes
        (DDL, catalog updates, copy batches) default to the maximum (600 s), because setup and index
        builds are long but approved work. Either can be set per call, capped at the maximum."""
        timeout = default_s if timeout_s is None or timeout_s <= 0 else timeout_s
        return conn.run(sql, params, min(timeout, self.settings.max_timeout_s), what, how_to_narrow, prepared)

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
            self._writer.run(
                f"INSERT INTO {table_sql} ({cols}) VALUES {values}", params, self.settings.max_timeout_s, "saving entries"
            )
            total += len(chunk)
        return total

    def close(self) -> None:
        self._reader.close()
        self._writer.close()
