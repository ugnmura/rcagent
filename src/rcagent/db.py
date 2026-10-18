"""SereneDB access: one reader and one writer connection; every query runs under a timeout that
cancels it inside SereneDB (Postgres cancel request from a timer thread, spike section 2)."""

import logging
import math
import os
import re
import socket
import threading
import time
from dataclasses import dataclass
from typing import Any

import psycopg
from psycopg.types.datetime import TimestampLoader, TimestamptzLoader

from rcagent import evidence
from rcagent.config import Settings
from rcagent.errors import UserFacingError
from rcagent.format import timeout_message

_NAME = re.compile(r"^[a-z][a-z0-9_]{0,40}$")


DEFAULT_NARROW = "narrow it: a shorter period (start/end) or more filters (level, service), then try again."
CONNECT_TIMEOUT_CAP_S = 30  # libpq connect_timeout (whole seconds, at least 2): the query timeout, at most this
CANCEL_TIMEOUT_S = 2.0  # how long the cancel request may take; finish() can wait at most this long for it
LATE_GRACE_S = 3.0  # after the cancel, how long a statement may take to stop before the call answers TIMEOUT anyway


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
            f"SereneDB refused this to the role in {setting}: {detail}. Grant it access as in the "
            f"\"Reader and writer roles\" section of docs/reference.md: {needs}."
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

    def mogrify(self, sql: str, params: dict[str, Any] | None) -> str:
        """The statement with its parameters filled in, as it would be sent (for the evidence log)."""
        if params is None:  # sent as is: psycopg leaves the text alone without a params dict
            return sql
        try:
            with self.lock:
                return psycopg.ClientCursor(self.get()).mogrify(sql, params)
        except Exception:
            return sql + "  -- parameters: " + ", ".join(f"{k}={v!r}" for k, v in params.items())

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
        zone: str | None = None,
    ) -> Rows:
        """Run one statement; past `timeout_s` it is cancelled in SereneDB and QueryTimeout is raised.
        `prepared`: use the extended protocol (server-side parsing), so the server itself refuses a
        string holding several statements; for untrusted SQL (run_sql). `zone`: the session time zone
        for this statement only (how timestamptz values print, and what date_trunc, ::date and time
        literals mean); it is reset afterwards."""
        with self.lock:
            canceller: _Canceller | None = None
            zoned = False
            abandoned = False
            try:
                pg = self.get(timeout_s)
                canceller = _Canceller(pg, timeout_s)
                if zone is not None:
                    pg.execute(f"SET TimeZone = {_literal(zone)}")
                    zoned = True
                deadline = None if timeout_s is None else timeout_s + CANCEL_TIMEOUT_S + LATE_GRACE_S
                rows = _run_bounded(pg, sql, params, prepared, deadline)
                if rows is None:
                    # Still running well past the timeout although it was cancelled: SereneDB only notices a
                    # cancel between steps of a query, and one big step (a single huge aggregate) can take
                    # minutes. Answer now; the connection is dropped (the statement's thread closes it).
                    abandoned = True
                    self._conn = None
                    logging.getLogger("rcagent").warning(
                        "statement still running %.0f s after its timeout; connection abandoned",
                        CANCEL_TIMEOUT_S + LATE_GRACE_S,
                    )
                    raise QueryTimeout(timeout_s or 0, what, how_to_narrow)
                return rows
            except psycopg.errors.InsufficientPrivilege as exc:
                raise PermissionRefused(self.setting, str(exc).splitlines()[0] if str(exc) else "") from exc
            except psycopg.errors.QueryCanceled:
                if canceller is not None and canceller.fired and timeout_s is not None:
                    raise QueryTimeout(timeout_s, what, how_to_narrow) from None
                raise QueryCancelledElsewhere() from None  # not our timer: an operator or the server
            except psycopg.OperationalError as exc:
                if canceller is not None and canceller.fired and timeout_s is not None:  # the cancel failed and the timer cut the link
                    self.close()
                    raise QueryTimeout(timeout_s, what, how_to_narrow) from None
                conn = self._conn
                if exc.sqlstate is not None and conn is not None and not conn.closed and not conn.broken:
                    raise  # SereneDB answered with an error (e.g. a file could not be read): not a dead link
                self.close()  # drop a dead connection so the next call reconnects
                raise DatabaseUnreachable(self.setting, str(exc)) from exc
            finally:
                if canceller is not None:
                    canceller.finish()
                if zoned and not abandoned:
                    self._reset_zone()

    def _reset_zone(self) -> None:
        """Back to the session's own time zone; a connection that can't be reset is dropped (a new one starts clean)."""
        pg = self._conn
        if pg is None or pg.closed:
            return
        try:
            pg.execute("RESET TimeZone")
        except psycopg.Error:
            self.close()


def _shutdown_socket(pg: psycopg.Connection[Any]) -> None:
    """Shut the connection's socket down (both ways) without freeing the connection: a thread waiting on it
    wakes with a broken connection. Works on a duplicate of the descriptor, so the connection object itself
    is never touched from this thread."""
    try:
        fd = os.dup(pg.pgconn.socket)
    except Exception:
        return
    try:
        with socket.socket(fileno=fd) as s:
            s.shutdown(socket.SHUT_RDWR)
    except OSError:
        pass


def _run_bounded(
    pg: psycopg.Connection[Any], sql: str, params: dict[str, Any] | None, prepared: bool, deadline_s: float | None
) -> Rows | None:
    """Run one statement on its own thread and wait at most `deadline_s` for it. None: still running at the
    deadline; the connection is then cut (socket shut down) and the thread closes it when it returns, so the
    caller must drop it. Errors of the statement are raised here."""
    box: dict[str, Any] = {}
    done = threading.Event()
    guard = threading.Lock()
    abandoned = threading.Event()

    def work() -> None:
        try:
            if prepared:
                cur = psycopg.Cursor(pg)
                cur.execute(sql, params, prepare=True)  # type: ignore[call-overload]
            else:
                cur = pg.execute(sql, params)  # type: ignore[call-overload]
            box["rows"] = Rows([], []) if cur.description is None else Rows([d.name for d in cur.description], cur.fetchall())
        except BaseException as exc:  # handed to the caller's thread
            box["error"] = exc
        finally:
            with guard:
                done.set()
                late = abandoned.is_set()
            if late:
                try:
                    pg.close()
                except Exception:
                    pass

    worker = threading.Thread(target=work, name="serenedb-statement", daemon=True)
    worker.start()
    if not done.wait(deadline_s):
        with guard:  # the worker can't close the connection while this is held, so its socket is still its own
            if not done.is_set():
                abandoned.set()
                _shutdown_socket(pg)
                return None
    worker.join()
    if "error" in box:
        raise box["error"]
    rows: Rows = box["rows"]
    return rows


def _literal(text: str) -> str:
    return "'" + text.replace("'", "''") + "'"


class _Canceller:
    """Sends a cancel request for the connection's running statement once the timeout passes.

    `finish()` is called (under the connection lock) as soon as the statement returns, so a late
    timer never cancels the next statement on the same connection.
    """

    def __init__(self, pg: psycopg.Connection[Any], timeout_s: float | None) -> None:
        self._pg = pg
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
            pg = self._pg
            if self._done or pg.closed:
                return
            self.fired = True
            try:
                pg.cancel_safe(timeout=CANCEL_TIMEOUT_S)
            except Exception:  # cancel failed: fall back to cutting the connection (spike section 2)
                # Not pg.close(): freeing the connection under the thread that is waiting on it neither wakes
                # that thread (it waited until the query ended, 30-80 s late) nor is safe. Shutting the socket
                # down wakes it at once with a broken connection, and the server sees the client go.
                logging.getLogger("rcagent").warning("cancel request failed; cutting the connection")
                _shutdown_socket(pg)

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
        zone: str | None = None,
    ) -> Rows:
        if not evidence.active():
            return self._execute(
                self._reader, sql, params, timeout_s, what, how_to_narrow, self.settings.default_timeout_s, prepared, zone
            )
        shown = self._reader.mogrify(sql, params)
        began = time.perf_counter()
        try:
            rows = self._execute(
                self._reader, sql, params, timeout_s, what, how_to_narrow, self.settings.default_timeout_s, prepared, zone
            )
        except Exception as exc:
            evidence.note(shown, None, time.perf_counter() - began, " ".join(str(exc).split())[:200] or type(exc).__name__)
            raise
        evidence.note(shown, len(rows.rows), time.perf_counter() - began)
        return rows

    def write(
        self,
        sql: str,
        params: dict[str, Any] | None = None,
        timeout_s: float | None = None,
        what: str = "",
        how_to_narrow: str = DEFAULT_NARROW,
    ) -> Rows:
        if not evidence.active() or not evidence.is_evidence(sql):
            return self._execute(self._writer, sql, params, timeout_s, what, how_to_narrow, self.settings.max_timeout_s)
        shown = self._writer.mogrify(sql, params)
        began = time.perf_counter()
        try:
            rows = self._execute(self._writer, sql, params, timeout_s, what, how_to_narrow, self.settings.max_timeout_s)
        except Exception as exc:
            evidence.note(shown, None, time.perf_counter() - began, " ".join(str(exc).split())[:200] or type(exc).__name__)
            raise
        evidence.note(shown, len(rows.rows), time.perf_counter() - began)
        return rows

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
        zone: str | None = None,
    ) -> Rows:
        """Every statement runs under a timeout. Reads default to the query timeout (60 s); writes
        (DDL, catalog updates, copy batches) default to the maximum (600 s), because setup and index
        builds are long but approved work. Either can be set per call, capped at the maximum."""
        timeout = default_s if timeout_s is None or timeout_s <= 0 else timeout_s
        return conn.run(sql, params, min(timeout, self.settings.max_timeout_s), what, how_to_narrow, prepared, zone)

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
