"""Time ranges and role filters as SQL, plus the plain-language diagnosis of an empty result."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, NamedTuple
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import psycopg

from serenedb_extractor.catalog.models import LogTable
from serenedb_extractor.db import Database, quote_ident
from serenedb_extractor.errors import UserFacingError
from serenedb_extractor.setup.paths import pct, resolve_source, sql_literal
from serenedb_extractor.setup.roles import is_temporal, resolve_column, role_column

FILTER_ROLES = ("level", "service", "host", "component", "trace")
_FMT = "%Y-%m-%d %H:%M:%S"


class MissingRole(UserFacingError):
    def __init__(self, role: str, present: list[str] | None = None) -> None:
        self.role = role
        have = f" It has: {', '.join(present)}." if present else ""
        super().__init__(
            f"This log table has no {role} field, so it can't be filtered or grouped by {role}.{have} "
            "If a column holds it, set the role again with setup_log_table (roles={...})."
        )


def get_zone(tz: str) -> ZoneInfo:
    try:
        return ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        raise UserFacingError(f"'{tz}' is not a time zone I know; use an IANA name like UTC or Europe/Paris.") from None


@dataclass(frozen=True)
class TimeRange:
    """Start inclusive, end exclusive, both UTC-aware (None = open). `tz` is how times are shown."""

    start: datetime | None = None
    end: datetime | None = None
    tz: str = "UTC"

    @property
    def bounded(self) -> bool:
        return self.start is not None or self.end is not None

    def fmt(self, dt: datetime) -> str:
        return dt.astimezone(get_zone(self.tz)).strftime(_FMT)

    def describe(self) -> str:
        if not self.bounded:
            return "all time"
        lo = self.fmt(self.start) if self.start else "the beginning"
        hi = self.fmt(self.end) if self.end else "the end"
        return f"{lo} to {hi} {self.tz}"


def _parse_moment(text: str, zone: ZoneInfo, what: str) -> datetime:
    raw = text.strip()
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00") if raw.endswith("Z") else raw)
    except ValueError:
        raise UserFacingError(
            f"I could not read {what} '{text}' as a time. Use a form like 2026-03-01 or 2026-03-01T12:30:00."
        ) from None
    return (dt.replace(tzinfo=zone) if dt.tzinfo is None else dt).astimezone(UTC)


def parse_time_range(start: str | None, end: str | None, tz: str = "UTC") -> TimeRange:
    zone = get_zone(tz)
    s = _parse_moment(start, zone, "the start") if start else None
    e = _parse_moment(end, zone, "the end") if end else None
    if s and e and s >= e:
        raise UserFacingError("The time range is empty: the start must be before the end (the end is exclusive).")
    return TimeRange(s, e, tz)


@dataclass(frozen=True)
class Filters:
    level: str | list[str] | None = None
    service: str | list[str] | None = None
    host: str | list[str] | None = None
    component: str | list[str] | None = None
    trace: str | list[str] | None = None
    columns: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> "Filters":
        d = dict(d or {})
        roles = {r: d.pop(r) for r in FILTER_ROLES if d.get(r) is not None}
        d.pop("columns", None)
        return cls(**roles, columns={k: str(v) for k, v in d.items()})

    def items(self) -> list[tuple[str, str | list[str]]]:
        """(role or column, wanted value(s)) for every filter that is set."""
        out: list[tuple[str, str | list[str]]] = [(r, v) for r in FILTER_ROLES if (v := getattr(self, r)) is not None]
        out += list(self.columns.items())
        return out


def role_expr(lt: LogTable, role: str) -> str:
    expr = getattr(lt.roles, role, None)
    if expr is None:
        raise MissingRole(role, list(lt.roles.present()))
    return str(expr)


def _find_column(name: str, known_columns: dict[str, str]) -> str:
    col = resolve_column(name, known_columns)
    if col is None:
        raise UserFacingError(f"There is no column '{name}' in this log table. Columns: {', '.join(known_columns)}.")
    return col


def role_sql(lt: LogTable, role: str) -> str:
    """A role's expression, ready to put into SQL that is sent with a params dict."""
    return pct(role_expr(lt, role))


def _filter_expr(lt: LogTable, key: str, known_columns: dict[str, str]) -> str:
    if key in FILTER_ROLES:
        return role_sql(lt, key)
    return quote_ident(_find_column(key, known_columns))


def _ts_type(lt: LogTable, known_columns: dict[str, str]) -> str:
    col = role_column(role_expr(lt, "timestamp"))
    return known_columns.get(col or "", "TIMESTAMP WITH TIME ZONE")


def time_clause(lt: LogTable, tr: TimeRange, known_columns: dict[str, str], prefix: str = "t") -> tuple[str, dict[str, Any]]:
    """Predicate for the time range. Literals are typed to match the column so Parquet can prune
    (spike section 6): timestamptz_ns for nanosecond columns, never a cast of the column."""
    if not tr.bounded:
        return "TRUE", {}
    expr = role_sql(lt, "timestamp")
    typ = _ts_type(lt, known_columns).upper()
    parts: list[str] = []
    params: dict[str, Any] = {}
    for op, dt, name in ((">=", tr.start, "lo"), ("<", tr.end, "hi")):
        if dt is None:
            continue
        key = f"{prefix}_{name}"
        if not is_temporal(typ):
            parts.append(f"({expr})::timestamptz {op} %({key})s::timestamptz")
            params[key] = dt.isoformat()
        elif "WITH TIME ZONE" in typ or typ.startswith("TIMESTAMPTZ"):
            cast = "timestamptz_ns" if typ.endswith("_NS") else "timestamptz"
            parts.append(f"{expr} {op} %({key})s::{cast}")
            params[key] = dt.isoformat()
        else:
            cast = "timestamp_ns" if typ.endswith("_NS") else "timestamp"
            local = dt.astimezone(get_zone(lt.timezone)).replace(tzinfo=None)
            parts.append(f"{expr} {op} %({key})s::{cast}")
            params[key] = local.isoformat(sep=" ")
    return " AND ".join(parts), params


def _value_clause(expr: str, wanted: str | list[str], key: str) -> tuple[str, dict[str, Any]]:
    if isinstance(wanted, list):
        names = {f"{key}_{i}": str(v) for i, v in enumerate(wanted)}
        return f"({expr})::varchar IN ({', '.join(f'%({n})s' for n in names)})", names
    return f"({expr})::varchar = %({key})s", {key: str(wanted)}


def build_where(
    lt: LogTable, tr: TimeRange, f: Filters, known_columns: dict[str, str]
) -> tuple[str, dict[str, Any]]:
    """WHERE body (without the keyword) and its parameters. Raises MissingRole for absent roles."""
    clauses: list[str] = []
    params: dict[str, Any] = {}
    if tr.bounded:
        c, p = time_clause(lt, tr, known_columns)
        clauses.append(c)
        params.update(p)
    for i, (key, wanted) in enumerate(f.items()):
        c, p = _value_clause(_filter_expr(lt, key, known_columns), wanted, f"f{i}")
        clauses.append(c)
        params.update(p)
    return (" AND ".join(clauses) or "TRUE"), params


def _shown(wanted: str | list[str]) -> str:
    if isinstance(wanted, list) and len(wanted) == 1:
        wanted = wanted[0]
    def q(w: str) -> str:
        return "'" + str(w).replace("'", "''") + "'"

    return "in (" + ", ".join(q(w) for w in wanted) + ")" if isinstance(wanted, list) else f"={q(wanted)}"


class DataRange(NamedTuple):
    first: datetime
    last: datetime
    from_stats: bool  # True when read from Parquet statistics, False when scanned
    note: str = ""  # why statistics were not used, when that is worth telling


def data_range(db: Database, lt: LogTable, known_columns: dict[str, str]) -> DataRange | None:
    """First and last timestamp in the data (UTC). Parquet statistics when possible (no data read)."""
    if lt.roles.timestamp is None:
        return None
    expr = lt.roles.timestamp
    col = role_column(expr)
    typ = known_columns.get(col or "", "").upper()
    naive = is_temporal(typ) and "WITH TIME ZONE" not in typ and not typ.startswith("TIMESTAMPTZ")
    zone = sql_literal(lt.timezone)
    note = ""
    if lt.mode == "in_place" and lt.source_format == "parquet" and col is not None:
        path = resolve_source(lt.source, db.settings, "parquet").db_path
        cast = f"(stats_min::timestamp) AT TIME ZONE {zone}" if naive else "stats_min::timestamptz"
        cast_max = f"(stats_max::timestamp) AT TIME ZONE {zone}" if naive else "stats_max::timestamptz"
        try:
            row = db.read(
                f"SELECT min({cast}), max({cast_max}) FROM parquet_metadata({sql_literal(path)}) "
                "WHERE path_in_schema = %(c)s AND stats_min IS NOT NULL",
                {"c": col},
            ).rows[0]
            if row[0] is not None:
                return DataRange(row[0], row[1], True)
            note = "the file has no statistics for it"
        except psycopg.Error as exc:
            note = "Parquet statistics could not be read: " + " ".join(str(exc).split())[:120]
    # TODO(#10): cap the cost of this full scan with the cost check (it reads the whole timestamp column).
    e = pct(expr)
    cast_e = f"e AT TIME ZONE {zone}" if naive else "e::timestamptz"
    row = db.read(f"SELECT min({cast_e})::timestamptz, max({cast_e})::timestamptz FROM (SELECT {e} AS e FROM {lt.relation})", {}).rows[0]
    return DataRange(row[0], row[1], False, note) if row[0] is not None else None


def covers_text(rng: DataRange | None, tr: TimeRange) -> str:
    if rng is None:
        return "the log table has no timestamps I could read"
    return f"the data covers {tr.fmt(rng.first)} to {tr.fmt(rng.last)} {tr.tz}"


def seen_values(
    db: Database, lt: LogTable, expr: str, where: str, params: dict[str, Any], limit: int = 8
) -> tuple[list[str], bool]:
    rows = db.read(
        f"SELECT v, c FROM (SELECT ({expr})::varchar AS v, count(*) AS c FROM {lt.relation} WHERE {where} "
        f"GROUP BY 1) ORDER BY c DESC, v LIMIT {limit + 1}",
        params,
    ).rows
    vals = [str(r[0]) for r in rows if r[0] is not None]
    return vals[:limit], len(rows) > limit


def diagnose_empty(
    db: Database, lt: LogTable, tr: TimeRange, f: Filters, known_columns: dict[str, str]
) -> list[str]:
    """Plain-language lines saying which part of the query matched nothing."""
    lines: list[str] = []
    time_sql, time_params = time_clause(lt, tr, known_columns)
    if tr.bounded:
        rng = data_range(db, lt, known_columns)
        outside = rng is not None and ((tr.end is not None and tr.end <= rng.first) or (tr.start is not None and tr.start > rng.last))
        if outside or rng is None:
            return [f"No entries from {tr.describe()}: {covers_text(rng, tr)}."]
        any_row = db.read(f"SELECT 1 FROM {lt.relation} WHERE {time_sql} LIMIT 1", time_params).rows
        if not any_row:
            return [f"No entries from {tr.describe()} (inside the data's span, but that period is empty): {covers_text(rng, tr)}."]
    each_ok = True
    for i, (key, wanted) in enumerate(f.items()):
        expr = _filter_expr(lt, key, known_columns)
        clause, p = _value_clause(expr, wanted, f"d{i}")
        hit = db.read(f"SELECT 1 FROM {lt.relation} WHERE {time_sql} AND {clause} LIMIT 1", {**time_params, **p}).rows
        if hit:
            continue
        each_ok = False
        vals, more = seen_values(db, lt, expr, time_sql, time_params)
        seen = ", ".join(vals) + (", …" if more else "")
        lines.append(f"{key}{_shown(wanted)} matched nothing" + (f" (seen: {seen})" if vals else "") + ".")
    if each_ok and f.items():
        lines.append(
            "Each filter matches entries on its own, but no entry matches all of them together"
            + (f" in {tr.describe()}" if tr.bounded else "")
            + "."
        )
    return lines

