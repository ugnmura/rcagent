"""The evidence log: every query a tool call ran, kept with the call's result under an ID (Q<n>), so
each measured claim in an answer can be traced to a query that actually ran and checked again.

A tool call collects its queries while it runs (`collecting`); the server then records them with the
result (`EvidenceLog.record`) and appends a short evidence footer to what the agent sees. Records are
kept in `extractor.evidence` so they outlive the session; if that write fails they are still kept in
memory for this process, and the answer is never lost over it.
"""

import json
import logging
import re
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from serenedb_extractor.errors import UserFacingError

if TYPE_CHECKING:
    from serenedb_extractor.db import Database

EVIDENCE_DDL = """CREATE TABLE IF NOT EXISTS extractor.evidence (
        id                 INTEGER PRIMARY KEY,
        tool               VARCHAR NOT NULL,
        args               JSON NOT NULL,
        queries            JSON NOT NULL,
        result             VARCHAR NOT NULL,
        created_at         TIMESTAMP NOT NULL
    )"""

# Bookkeeping reads of the extractor's own tables are not evidence for a claim about the logs.
_CATALOG_ONLY = re.compile(
    r"\bextractor\.(log_tables|templates|template_redirects|log_index_columns|ownership|evidence)\b", re.I
)
_DATA_RELATION = re.compile(r"\bextractor\.(lt_|ix_|sx_)|read_parquet|read_json|read_csv|parquet_", re.I)

UNIQUE_VIOLATION = "23505"  # SQLSTATE of a duplicate key
STORE_ATTEMPTS = 5  # ids tried when other server processes keep taking the next one
FOOTER_QUERIES = 4 # queries shown in the footer; show_evidence has them all
FOOTER_SQL_CHARS = 400
_ID = re.compile(r"^\s*\[?q?(\d+)\]?\s*$", re.I)


@dataclass(frozen=True)
class Query:
    sql: str
    rows: int | None
    seconds: float
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {"sql": self.sql, "rows": self.rows, "seconds": round(self.seconds, 3), "error": self.error}


@dataclass
class Record:
    id: int
    tool: str
    args: dict[str, Any]
    queries: list[Query]
    result: str
    created_at: datetime

    @property
    def handle(self) -> str:
        return f"Q{self.id}"


_current: ContextVar[list[Query] | None] = ContextVar("evidence_queries", default=None)


@contextmanager
def collecting() -> Iterator[list[Query]]:
    """Collect the queries run inside this block (one tool call)."""
    queries: list[Query] = []
    token = _current.set(queries)
    try:
        yield queries
    finally:
        _current.reset(token)


def active() -> bool:
    return _current.get() is not None


def note(sql: str, rows: int | None, seconds: float, error: str | None = None) -> None:
    """Remember one query of the running tool call (no-op outside a call)."""
    queries = _current.get()
    if queries is None or not is_evidence(sql):
        return
    queries.append(Query(" ".join(sql.split()), rows, seconds, error))


def is_evidence(sql: str) -> bool:
    """A query over log data (or a query that is not just catalog bookkeeping)."""
    if _DATA_RELATION.search(sql):
        return True
    return not _CATALOG_ONLY.search(sql)


def parse_id(text: str) -> int:
    m = _ID.match(str(text))
    if not m:
        raise UserFacingError(f"'{text}' is not an evidence ID: use the Q<n> handle from a tool result, e.g. Q7.")
    return int(m.group(1))


def _json(value: Any) -> str:
    return json.dumps(value, default=str, ensure_ascii=False)


class EvidenceLog:
    """Numbers and keeps evidence records; persistent when the writer can store them."""

    def __init__(self, db: "Database | None") -> None:
        self._db = db
        self._lock = threading.Lock()
        self._memory: dict[int, Record] = {}
        self._next: int | None = None
        self._persist = db is not None

    def _next_id(self) -> int:
        if self._next is None:
            start = 0
            if self._db is not None:
                try:
                    start = int(self._db.read("SELECT coalesce(max(id), 0) FROM extractor.evidence", {}).scalar() or 0)
                except Exception:  # no table yet, or no access: number from 1 in memory
                    self._persist = False
            self._next = start + 1
        n = self._next
        self._next += 1
        return n

    def _resync(self) -> None:
        """Number on from the stored maximum again: another server process on the same database took ids."""
        if self._db is None:
            return
        try:
            top = int(self._db.read("SELECT coalesce(max(id), 0) FROM extractor.evidence", {}).scalar() or 0)
        except Exception:
            return
        self._next = max(self._next or 0, top + 1)

    def record(self, tool: str, args: dict[str, Any], queries: list[Query], result: str) -> Record:
        with self._lock:
            rec = Record(self._next_id(), tool, args, list(queries), result, datetime.now(UTC).replace(tzinfo=None))
            if self._persist and self._db is not None:
                self._store(rec)
            self._memory[rec.id] = rec
            return rec

    def _store(self, rec: Record) -> None:
        """Insert `rec`; when its id was taken meanwhile by another process (duplicate key), take the next
        free one and try again, so a handle never names someone else's record. Other failures leave the
        record in memory only."""
        assert self._db is not None
        log = logging.getLogger("serenedb_extractor")
        for _ in range(STORE_ATTEMPTS):
            try:
                self._db.write(
                    "INSERT INTO extractor.evidence (id, tool, args, queries, result, created_at) "
                    "VALUES (%(id)s, %(tool)s, %(args)s, %(queries)s, %(result)s, %(at)s)",
                    {
                        "id": rec.id,
                        "tool": rec.tool,
                        "args": _json(rec.args),
                        "queries": _json([q.as_dict() for q in rec.queries]),
                        "result": rec.result,
                        "at": rec.created_at,
                    },
                )
                return
            except Exception as exc:
                if getattr(exc, "sqlstate", None) != UNIQUE_VIOLATION:
                    log.warning("evidence not stored in SereneDB: %s", exc)
                    self._persist = False
                    return
                self._resync()
                rec.id = self._next_id()
        log.warning("evidence not stored in SereneDB: no free id after %d attempts", STORE_ATTEMPTS)

    def get(self, ident: int) -> Record | None:
        with self._lock:
            if ident in self._memory:
                return self._memory[ident]
        if self._db is None:
            return None
        try:
            rows = self._db.read(
                "SELECT id, tool, args, queries, result, created_at FROM extractor.evidence WHERE id = %(id)s",
                {"id": ident},
            ).dicts()
        except Exception:
            return None
        if not rows:
            return None
        return _from_row(rows[0])

    def recent(self, n: int = 20) -> list[Record]:
        if self._db is not None and self._persist:
            try:
                rows = self._db.read(
                    "SELECT id, tool, args, queries, result, created_at FROM extractor.evidence "
                    "ORDER BY id DESC LIMIT %(n)s",
                    {"n": n},
                ).dicts()
                return [_from_row(r) for r in rows]
            except Exception:
                pass
        with self._lock:
            return sorted(self._memory.values(), key=lambda r: -r.id)[:n]


def _loads(v: Any) -> Any:
    return json.loads(v) if isinstance(v, str) else v


def _from_row(r: dict[str, Any]) -> Record:
    qs = [Query(q["sql"], q.get("rows"), float(q.get("seconds") or 0), q.get("error")) for q in _loads(r["queries"]) or []]
    return Record(int(r["id"]), r["tool"], _loads(r["args"]) or {}, qs, r["result"], r["created_at"])


def _short(sql: str, n: int) -> str:
    return sql if len(sql) <= n else sql[: n - 1].rstrip() + "…"


def _q_line(i: int, q: Query, handle: str, chars: int | None) -> str:
    rows = "error: " + q.error if q.error else (f"{q.rows:,} row(s)" if q.rows is not None else "ran")
    sql = q.sql if chars is None else _short(q.sql, chars)
    return f"  {handle}.{i} ({q.seconds:.2f} s, {rows}): {sql}"


_LOOKUP = re.compile(
    r"^\s*(DESCRIBE\b|EXPLAIN\b|SELECT \* FROM \S+ LIMIT 0\b)|parquet_(file_)?metadata\(|information_schema\.",
    re.I,
)


def is_lookup(q: Query) -> bool:
    """Metadata only (columns, Parquet statistics, the plan): how a query was prepared, not what it found."""
    return bool(_LOOKUP.search(q.sql))


def footer(rec: Record) -> str:
    """What the agent sees under a result: the evidence handle and the queries that ran."""
    if not rec.queries:
        return (
            f"Evidence [{rec.handle}]: no query over the logs ran for this result "
            "(it came from the extractor catalog alone)."
        )
    numbered = list(enumerate(rec.queries, 1))
    data = [(i, q) for i, q in numbered if not is_lookup(q)]
    lookups = len(numbered) - len(data)
    shown = data[:FOOTER_QUERIES]
    lines = [
        f"Evidence [{rec.handle}]: the queries that produced this result. Cite [{rec.handle}] next to numbers "
        f"taken from it; show_evidence(['{rec.handle}']) gives every query in full and the result again."
    ]
    lines += [_q_line(i, q, rec.handle, FOOTER_SQL_CHARS) for i, q in shown]
    rest = []
    if len(data) > len(shown):
        rest.append(f"{len(data) - len(shown)} more data quer{'y' if len(data) - len(shown) == 1 else 'ies'}")
    if lookups:
        rest.append(f"{lookups} metadata lookup{'' if lookups == 1 else 's'} (columns, Parquet statistics) to plan the cost")
    if rest:
        lines.append("  plus " + " and ".join(rest) + " (show_evidence lists them)")
    return "\n".join(lines)


def full_text(rec: Record, with_result: bool = True) -> str:
    args = ", ".join(f"{k}={v!r}" for k, v in rec.args.items() if v not in (None, "", [], {}))
    lines = [
        f"[{rec.handle}] {rec.tool}({args}) at {rec.created_at:%Y-%m-%d %H:%M:%S} UTC",
        f"queries ({len(rec.queries)}):" if rec.queries else "queries: none over the logs",
    ]
    lines += [_q_line(i, q, rec.handle, None) for i, q in enumerate(rec.queries, 1)]
    if with_result:
        lines += ["result:", *("  " + ln for ln in rec.result.splitlines())]
    return "\n".join(lines)
