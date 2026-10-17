"""Inverted indexes over a log table (spec section 7): estimates from a trial build, explicit builds.

Two kinds, both on the log table's relation (a view for sources read in place, the table for copies):

- filter: the present roles among timestamp, level, service, component, trace, verbatim (no
  dictionary). It lists a column's distinct values exactly and answers filters without a scan.
- search: the message with the dictionary `extractor.log_dict`, plus the same columns and the host,
  so text and fuzzy search (and a listing of the matches) can run on the index relation alone.

The index is named `<log_table>_<kind>_idx` and lives in the relation's schema. Queries that use it
must read the *index relation* (`FROM <schema>.<name>_idx`), not the view or table: `ts_dict_agg`
and `@@` fail elsewhere (spike section 9 and 10). Its columns are only the real columns of the view
body, so the Parquet helper columns (`filename`, `file_row_number`) can't be read from it.
"""

import logging
import re
import time
import uuid
from dataclasses import dataclass

import psycopg

from serenedb_extractor import format as fmt
from serenedb_extractor.catalog.models import FieldRoles, LogTable
from serenedb_extractor.context import AppContext
from serenedb_extractor.db import quote_ident
from serenedb_extractor.errors import UserFacingError
from serenedb_extractor.query.indexcover import KINDS, IndexKind
from serenedb_extractor.setup.paths import sql_literal
from serenedb_extractor.setup.roles import role_column
from serenedb_extractor.setup.sniff import human_bytes

log = logging.getLogger(__name__)

SCHEMA = "extractor"  # every index and trial object lives here; no DDL ever touches another schema
LOG_DICT = "extractor.log_dict"
TRIAL_ROWS = 1_000_000  # entries in the trial build
MIN_ROWS_FOR_OFFER = 1_000_000  # below this, a scan is fast enough that an index isn't offered
STALE_TRIAL_S = 3600.0  # a trial object this old is left over from a crashed estimate
_FILTER_ROLES = ("timestamp", "level", "service", "component", "trace")
_DICTIONARY_DDL = (
    f"CREATE TEXT SEARCH DICTIONARY {LOG_DICT} AS split_text(case := 'lower') | "
    "normalize_tokens('en_US.UTF-8', accent := false) WITH (frequency, position)"
)
_TRIAL_NAME = re.compile(r"^(trial_(?:(\d+)_)?[0-9a-f]+)_v$")


@dataclass(frozen=True)
class IndexEstimate:
    """Size and build time of an index over the whole source, scaled linearly from a trial build on
    `sample_rows` of its `total_rows` entries."""

    kind: IndexKind
    size_bytes: float
    build_seconds: float
    sample_rows: int
    total_rows: int

    def describe(self) -> str:
        return (
            f"≈{human_bytes(self.size_bytes)} on disk, {fmt.duration(self.build_seconds)} to build "
            f"(from a trial build on {self.sample_rows:,} of {self.total_rows:,} entries, scaled linearly; rough)"
        )

    def hint(self) -> str:
        return f"≈{human_bytes(self.size_bytes)}, {fmt.duration(self.build_seconds)} to build"


@dataclass(frozen=True)
class BuiltIndex:
    name: str  # qualified, as stored on the log table
    size_bytes: int
    seconds: float


def check_kind(kind: str) -> IndexKind:
    for k in KINDS:
        if kind == k:
            return k
    raise UserFacingError(f"kind must be 'filter' or 'search', not '{kind}'.")


def index_name(log_table: str, kind: str) -> str:
    return f"{log_table}_{kind}_idx"


def qualified_name(relation: str, log_table: str, kind: str) -> str:
    """The index's name in the extractor schema. An index lives next to its table, so the relation must be
    in that schema too (sources that are tables are viewed through `extractor.lt_<name>`)."""
    if not relation.startswith(f"{SCHEMA}."):
        raise UserFacingError(
            f"Log table '{log_table}' reads {relation}, outside the {SCHEMA} schema; indexes are only built in "
            f"{SCHEMA}, so none can be built for it."
        )
    return f"{SCHEMA}.{quote_ident(index_name(log_table, kind))}"


def spec(roles: FieldRoles, kind: str) -> list[tuple[str, bool]]:
    """(column, uses the dictionary) of the index: only plain columns can be indexed."""
    out: list[tuple[str, bool]] = []
    if kind == "search":
        msg = role_column(roles.message)
        if msg is None:
            raise UserFacingError(
                "The message field is not a plain column, so a search index can't be built on it. "
                "Set the message role to a column with setup_log_table (roles={...})."
            )
        out.append((msg, True))
    names = _FILTER_ROLES + (("host",) if kind == "search" else ())
    for role in names:
        expr = getattr(roles, role)
        col = role_column(expr) if expr else None
        if col is not None and col not in [c for c, _ in out]:
            out.append((col, False))
    if not any(not d for _, d in out):
        raise UserFacingError(
            "None of the timestamp, level, service, component or trace fields is a plain column, so there is "
            "nothing to put in a filter index."
        )
    return out


def _create_sql(name: str, relation: str, columns: list[tuple[str, bool]]) -> str:
    cols = ", ".join(quote_ident(c) + (f" {LOG_DICT}" if d else "") for c, d in columns)
    return f"CREATE INDEX {quote_ident(name)} ON {relation} USING inverted({cols})"


def _dictionary_exists(ctx: AppContext) -> bool:
    try:
        ctx.db.read(f"SELECT ts_lexize('{LOG_DICT}', 'x')", {})
        return True
    except (psycopg.Error, UserFacingError):
        return False


def ensure_dictionary(ctx: AppContext) -> None:
    """Create `extractor.log_dict` (spike section 10) when it doesn't exist yet; safe to race."""
    if _dictionary_exists(ctx):
        return
    try:
        ctx.db.write(_DICTIONARY_DDL, {})
    except psycopg.Error as exc:
        if "already exists" in str(exc):
            return  # another process created it between our check and our create
        raise UserFacingError(f"SereneDB could not create the text search dictionary: {_detail(exc)}") from exc


def _detail(exc: BaseException) -> str:
    return re.sub(r"\s+", " ", str(exc)).strip()[:300]


def _row_count(ctx: AppContext, relation: str) -> int:
    return int(ctx.db.read(f"SELECT count(*) FROM {relation}", {}).scalar() or 0)


def _drop(ctx: AppContext, sql: str) -> None:
    try:
        ctx.db.write(sql, {}, timeout_s=ctx.settings.max_timeout_s)
    except (psycopg.Error, UserFacingError) as exc:
        log.warning("could not run %s: %s", sql, _detail(exc))  # a trial object may be left behind; swept later


def _drop_trial(ctx: AppContext, tag: str) -> None:
    for kind in KINDS:
        _drop(ctx, f"DROP INDEX IF EXISTS {SCHEMA}.{quote_ident(f'{tag}_{kind}_idx')}")
    _drop(ctx, f"DROP VIEW IF EXISTS {SCHEMA}.{quote_ident(tag + '_v')}")


def sweep_trials(ctx: AppContext) -> None:
    """Drop trial objects left behind by an estimate that crashed (only old ones: another process may be mid-trial)."""
    try:
        names = [
            str(r[0])
            for r in ctx.db.read(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = %(s)s AND table_name LIKE %(p)s",
                {"s": SCHEMA, "p": "trial%"},
            ).rows
        ]
    except (psycopg.Error, UserFacingError) as exc:
        log.warning("could not look for leftover trial objects: %s", _detail(exc))
        return
    now = time.time()
    for name in names:
        m = _TRIAL_NAME.match(name)
        if m is None:
            continue
        made = float(m.group(2) or 0)
        if now - made > STALE_TRIAL_S:
            _drop_trial(ctx, m.group(1))


def _trial(ctx: AppContext, relation_sql: str, roles: FieldRoles, kind: IndexKind, rows: int) -> tuple[float, float]:
    """(size in bytes, build seconds) of an index over the first `rows` entries; trial objects are dropped."""
    columns = spec(roles, kind)
    if kind == "search":
        ensure_dictionary(ctx)
    tag = f"trial_{int(time.time())}_{uuid.uuid4().hex[:10]}"
    view, name = f"{SCHEMA}.{quote_ident(tag + '_v')}", f"{tag}_{kind}_idx"
    timeout = ctx.settings.max_timeout_s
    try:
        ctx.db.write(f"CREATE VIEW {view} AS SELECT * FROM {relation_sql} LIMIT {int(rows)}", {}, timeout_s=timeout)
        started = time.perf_counter()
        ctx.db.write(
            _create_sql(name, view, columns), {}, timeout_s=timeout, what=f"building a trial {kind} index"
        )
        seconds = time.perf_counter() - started
        size = ctx.db.read("SELECT pg_relation_size(%(n)s)", {"n": f"{SCHEMA}.{name}"}).scalar()
        return float(size or 0), seconds
    finally:
        _drop_trial(ctx, tag)


def estimate_relation(
    ctx: AppContext,
    relation_sql: str,
    roles: FieldRoles,
    kind: str,
    total_rows: int | None = None,
    sample_rows: int | None = None,
) -> IndexEstimate:
    """Trial build on `SELECT * FROM <relation_sql> LIMIT n`, scaled linearly to the whole source."""
    kind = check_kind(kind)
    sweep_trials(ctx)
    total = _row_count(ctx, relation_sql) if total_rows is None else int(total_rows)
    n = min(TRIAL_ROWS if sample_rows is None else sample_rows, total)
    if n <= 0:
        return IndexEstimate(kind, 0.0, 0.0, 0, total)
    size, seconds = _trial(ctx, relation_sql, roles, kind, n)
    scale = total / n
    return IndexEstimate(kind, size * scale, seconds * scale, n, total)


def estimate(ctx: AppContext, lt: LogTable, kind: str, sample_rows: int | None = None) -> IndexEstimate:
    est = estimate_relation(ctx, lt.relation, lt.roles, kind, lt.row_count, sample_rows)
    ctx.estimates.put(lt.source, lt.roles, check_kind(kind), est)
    return est


def build_measured(ctx: AppContext, lt: LogTable, kind: str) -> BuiltIndex:
    """Build the index on the log table's relation and record it on the log table."""
    k = check_kind(kind)
    columns = spec(lt.roles, k)
    qualified = qualified_name(lt.relation, lt.name, k)
    limit = ctx.settings.max_timeout_s
    est = ctx.estimates.get(lt.source, lt.roles, k)
    if est is None and (lt.row_count or 0) >= MIN_ROWS_FOR_OFFER:
        est = estimate(ctx, lt, k)  # a trial build tells whether the real one can finish in time
    if est is not None and est.build_seconds > limit:
        raise UserFacingError(
            f"The {k} index was not built: it is estimated to take {fmt.duration(est.build_seconds)}, "
            f"longer than the maximum time one statement may run on this server ({limit:.0f} s), "
            "so it would be cancelled. Build it on a smaller source, or have the server's maximum query time "
            "(max_timeout_s) raised."
        )
    if k == "search":
        ensure_dictionary(ctx)
    started = time.perf_counter()
    try:
        ctx.db.write(
            _create_sql(index_name(lt.name, k), lt.relation, columns),
            {},
            timeout_s=limit,
            what=f"building the {k} index of log table {lt.name}",
        )
        ctx.db.write(f"VACUUM (REFRESH_INDEX) {qualified}", {}, timeout_s=limit)
    except psycopg.Error as exc:
        if "already exists" in str(exc):
            raise UserFacingError(
                f"An index named {qualified} already exists but is not recorded for log table {lt.name}; "
                "drop it in SereneDB first, then build again."
            ) from exc
        _drop(ctx, f"DROP INDEX IF EXISTS {qualified}")
        raise UserFacingError(f"SereneDB could not build the {k} index: {_detail(exc)}") from exc
    except BaseException:
        _drop(ctx, f"DROP INDEX IF EXISTS {qualified}")  # e.g. a timeout: don't leave half an index behind
        raise
    seconds = time.perf_counter() - started
    try:
        size = ctx.db.read("SELECT pg_relation_size(%(n)s)", {"n": qualified.replace('"', "")}).scalar()
        ctx.store.set_index(lt.name, k, qualified, [c for c, _ in columns])
    except BaseException:
        _drop(ctx, f"DROP INDEX IF EXISTS {qualified}")  # not recorded, so nothing would ever use or drop it
        raise
    return BuiltIndex(qualified, int(size or 0), seconds)


def build(ctx: AppContext, lt: LogTable, kind: str) -> str:
    """Build the index; returns its (qualified) name."""
    return build_measured(ctx, lt, kind).name


# ------------------------------------------------------------------ the offer in inspect_source / setup


def offer_lines(
    ctx: AppContext, relation_sql: str, roles: FieldRoles, total_rows: int | None, source: str | None = None
) -> list[str]:
    """The index offer of setup: estimates for both kinds when the source has at least MIN_ROWS_FOR_OFFER
    entries. Runs trial builds (dropped again); nothing is built."""
    if total_rows is None:
        return [
            "indexes: the number of entries is unknown, so no estimate was made; "
            "create_index with dry_run measures one once the log table exists."
        ]
    if total_rows < MIN_ROWS_FOR_OFFER:
        return [f"indexes: none needed — {total_rows:,} entries are small enough to search without an index."]
    out = []
    for kind in KINDS:
        try:
            est = estimate_relation(ctx, relation_sql, roles, kind, total_rows)
        except (psycopg.Error, UserFacingError) as exc:
            out.append(f"{kind} index: no estimate ({_detail(exc)})")
            continue
        if source is not None:
            ctx.estimates.put(source, roles, kind, est)
        out.append(f"{kind} index: {est.describe()}")
    out.append(_OFFER_FOOTER)
    return out


_OFFER_FOOTER = (
    "No index is built unless you ask for it (build_filter_index / build_search_index at setup, or create_index). "
    "A filter index lists values exactly and makes filters nearly free; a search index also speeds up text "
    "search and allows fuzzy search."
)


def inspect_lines(
    ctx: AppContext, source: str, parquet_path: str | None, roles: FieldRoles, total_rows: int | None
) -> list[str]:
    """The index offer of inspect_source, which only reads: an estimate from an earlier trial build when this
    session has one, else a rough size from the Parquet column sizes. Never builds or creates anything."""
    if total_rows is None:
        return ["indexes: the number of entries is unknown; create_index with dry_run measures them after setup."]
    if total_rows < MIN_ROWS_FOR_OFFER:
        return [f"indexes: none needed — {total_rows:,} entries are small enough to search without an index."]
    out = []
    for kind in KINDS:
        est = ctx.estimates.get(source, roles, kind)
        if est is not None:
            out.append(f"{kind} index: {est.describe()}")
            continue
        try:
            size = _rough_size(ctx, parquet_path, roles, kind) if parquet_path else None
        except (psycopg.Error, UserFacingError):
            size = None
        out.append(
            f"{kind} index: about {human_bytes(size)} on disk (rough, from column sizes — create_index with dry_run measures it)"
            if size
            else f"{kind} index: size not known (create_index with dry_run measures it once the log table exists)"
        )
    out.append(_OFFER_FOOTER)
    return out


def _rough_size(ctx: AppContext, parquet_path: str, roles: FieldRoles, kind: IndexKind) -> float | None:
    """Compressed bytes of the Parquet columns the index would cover: a stand-in for the index's size."""
    names = [c for c, _ in spec(roles, kind)]
    params = {f"c{i}": n for i, n in enumerate(names)}
    marks = ", ".join(f"%({k})s" for k in params)
    total = ctx.db.read(
        f"SELECT sum(total_compressed_size)::bigint FROM parquet_metadata({sql_literal(parquet_path)}) "
        f"WHERE split_part(path_in_schema, ', ', 1) IN ({marks})",
        params,
    ).scalar()
    return float(total) if total else None
