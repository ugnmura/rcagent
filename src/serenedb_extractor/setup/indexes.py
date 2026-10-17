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

import re
import time
import uuid
from collections.abc import Collection
from dataclasses import dataclass

import psycopg

from serenedb_extractor import format as fmt
from serenedb_extractor.catalog.models import FieldRoles, LogTable
from serenedb_extractor.context import AppContext
from serenedb_extractor.db import Database, quote_ident
from serenedb_extractor.errors import UserFacingError
from serenedb_extractor.setup.roles import role_column
from serenedb_extractor.setup.sniff import human_bytes

KINDS = ("filter", "search")
LOG_DICT = "extractor.log_dict"
TRIAL_ROWS = 1_000_000  # entries in the trial build
MIN_ROWS_FOR_OFFER = 1_000_000  # below this, a scan is fast enough that an index isn't offered
BUILD_TIMEOUT_S = 6 * 3600.0  # asked for; Database.write still caps every statement at the maximum query time
_FILTER_ROLES = ("timestamp", "level", "service", "component", "trace")
_DICTIONARY_DDL = (
    f"CREATE TEXT SEARCH DICTIONARY {LOG_DICT} AS split_text(case := 'lower') | "
    "normalize_tokens('en_US.UTF-8', accent := false) WITH (frequency, position)"
)
_COLUMN_LIST = re.compile(r"USING inverted\s*\((.*?)\)\s*(?:WITH|$)", re.DOTALL)


@dataclass(frozen=True)
class IndexEstimate:
    """Size and build time of an index over the whole source, scaled linearly from a trial build on
    `sample_rows` of its `total_rows` entries."""

    kind: str
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


def _estimates(db: Database) -> dict[tuple[str, str], IndexEstimate]:
    """Estimates made through this database handle (so: in this server process), kept so that a refusal can
    name an index's size without a new trial build."""
    cache: dict[tuple[str, str], IndexEstimate] = db.__dict__.setdefault("_index_estimates", {})
    return cache


def cached_estimate(db: Database, log_table: str, kind: str) -> IndexEstimate | None:
    return _estimates(db).get((log_table, kind))


def check_kind(kind: str) -> str:
    if kind not in KINDS:
        raise UserFacingError(f"kind must be 'filter' or 'search', not '{kind}'.")
    return kind


def index_name(log_table: str, kind: str) -> str:
    return f"{log_table}_{kind}_idx"


def qualified_name(relation: str, log_table: str, kind: str) -> str:
    """The index's name with the schema of the relation it is built on (an index lives next to its table)."""
    prefix, dot, _ = relation.rpartition(".")
    name = index_name(log_table, kind)
    return f"{prefix}.{quote_ident(name)}" if dot else quote_ident(name)


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


def ensure_dictionary(ctx: AppContext) -> None:
    """Create `extractor.log_dict` (spike section 10) when it doesn't exist yet."""
    try:
        ctx.db.read(f"SELECT ts_lexize('{LOG_DICT}', 'x')", {})
        return
    except (psycopg.Error, UserFacingError):
        pass
    try:
        ctx.db.write(_DICTIONARY_DDL, {})
    except psycopg.Error as exc:
        raise UserFacingError(f"SereneDB could not create the text search dictionary: {_detail(exc)}") from exc


def _detail(exc: BaseException) -> str:
    return re.sub(r"\s+", " ", str(exc)).strip()[:300]


def _row_count(ctx: AppContext, relation: str) -> int:
    return int(ctx.db.read(f"SELECT count(*) FROM {relation}", {}).scalar() or 0)


def _trial(ctx: AppContext, relation_sql: str, roles: FieldRoles, kind: str, rows: int) -> tuple[float, float]:
    """(size in bytes, build seconds) of an index over the first `rows` entries; trial objects are dropped."""
    columns = spec(roles, kind)
    if kind == "search":
        ensure_dictionary(ctx)
    tag = f"trial_{uuid.uuid4().hex[:10]}"
    view, name = f"extractor.{tag}_v", f"{tag}_{kind}_idx"
    qualified = f"extractor.{quote_ident(name)}"
    timeout = ctx.settings.max_timeout_s
    try:
        ctx.db.write(f"CREATE VIEW {view} AS SELECT * FROM {relation_sql} LIMIT {int(rows)}", {}, timeout_s=timeout)
        started = time.perf_counter()
        ctx.db.write(
            _create_sql(name, view, columns), {}, timeout_s=timeout, what=f"building a trial {kind} index"
        )
        seconds = time.perf_counter() - started
        size = ctx.db.read("SELECT pg_relation_size(%(n)s)", {"n": f"extractor.{name}"}).scalar()
        return float(size or 0), seconds
    finally:
        for sql in (f"DROP INDEX IF EXISTS {qualified}", f"DROP VIEW IF EXISTS {view}"):
            try:
                ctx.db.write(sql, {}, timeout_s=timeout)
            except (psycopg.Error, UserFacingError):
                pass  # best effort: the trial objects carry a unique name and nothing refers to them


def estimate_relation(
    ctx: AppContext,
    relation_sql: str,
    roles: FieldRoles,
    kind: str,
    total_rows: int | None = None,
    sample_rows: int | None = None,
) -> IndexEstimate:
    """Trial build on `SELECT * FROM <relation_sql> LIMIT n`, scaled linearly to the whole source."""
    check_kind(kind)
    total = _row_count(ctx, relation_sql) if total_rows is None else int(total_rows)
    n = min(TRIAL_ROWS if sample_rows is None else sample_rows, total)
    if n <= 0:
        return IndexEstimate(kind, 0.0, 0.0, 0, total)
    size, seconds = _trial(ctx, relation_sql, roles, kind, n)
    scale = total / n
    return IndexEstimate(kind, size * scale, seconds * scale, n, total)


def estimate(ctx: AppContext, lt: LogTable, kind: str, sample_rows: int | None = None) -> IndexEstimate:
    est = estimate_relation(ctx, lt.relation, lt.roles, kind, lt.row_count, sample_rows)
    _estimates(ctx.db)[(lt.name, kind)] = est
    return est


def build_measured(ctx: AppContext, lt: LogTable, kind: str) -> BuiltIndex:
    """Build the index on the log table's relation and record it on the log table."""
    check_kind(kind)
    columns = spec(lt.roles, kind)
    if kind == "search":
        ensure_dictionary(ctx)
    name = index_name(lt.name, kind)
    qualified = qualified_name(lt.relation, lt.name, kind)
    started = time.perf_counter()
    try:
        ctx.db.write(
            _create_sql(name, lt.relation, columns),
            {},
            timeout_s=BUILD_TIMEOUT_S,
            what=f"building the {kind} index of log table {lt.name}",
        )
        ctx.db.write(f"VACUUM (REFRESH_INDEX) {qualified}", {}, timeout_s=BUILD_TIMEOUT_S)
    except psycopg.Error as exc:
        if "already exists" in str(exc):
            raise UserFacingError(
                f"An index named {qualified} already exists but is not recorded for log table {lt.name}; "
                "drop it in SereneDB first, then build again."
            ) from exc
        _drop_quietly(ctx, qualified)
        raise UserFacingError(f"SereneDB could not build the {kind} index: {_detail(exc)}") from exc
    except BaseException:
        _drop_quietly(ctx, qualified)  # e.g. a timeout: don't leave half an index behind
        raise
    seconds = time.perf_counter() - started
    size = ctx.db.read("SELECT pg_relation_size(%(n)s)", {"n": qualified.replace('"', "")}).scalar()
    ctx.store.set_index(lt.name, kind, qualified)
    return BuiltIndex(qualified, int(size or 0), seconds)


def build(ctx: AppContext, lt: LogTable, kind: str) -> str:
    """Build the index; returns its (qualified) name."""
    return build_measured(ctx, lt, kind).name


def _drop_quietly(ctx: AppContext, qualified: str) -> None:
    try:
        ctx.db.write(f"DROP INDEX IF EXISTS {qualified}", {}, timeout_s=ctx.settings.max_timeout_s)
    except (psycopg.Error, UserFacingError):
        pass


# ------------------------------------------------------------------ using an existing index


def indexed_columns(db: Database, index: str) -> set[str]:
    """The columns an existing index covers, read from its definition."""
    row = db.read("SELECT pg_get_indexdef(%(n)s::regclass)", {"n": index.replace('"', "")}).scalar()
    m = _COLUMN_LIST.search(str(row or ""))
    if not m:
        return set()
    return {part.strip().split(" ")[0].strip('"') for part in m.group(1).split(",") if part.strip()}


def covering(db: Database, lt: LogTable, columns: Collection[str], kinds: tuple[str, ...] = KINDS) -> tuple[str, str] | None:
    """(kind, index name) of the first existing index of `lt` that covers every column, else None."""
    wanted = set(columns)
    for kind in kinds:
        name = lt.filter_index_name if kind == "filter" else lt.search_index_name
        if name and wanted <= indexed_columns(db, name):
            return kind, name
    return None


def all_indexed_columns(db: Database, lt: LogTable) -> set[str]:
    """Columns any existing index of `lt` covers (what the cost check may treat as served by an index)."""
    out: set[str] = set()
    for name in (lt.filter_index_name, lt.search_index_name):
        if name:
            out |= indexed_columns(db, name)
    return out


def hints(db: Database, lt: LogTable) -> dict[str, str]:
    """Kind -> '≈X GB, ~N min to build' for the indexes of `lt` estimated earlier in this process."""
    out: dict[str, str] = {}
    for kind in KINDS:
        est = cached_estimate(db, lt.name, kind)
        if est is not None:
            out[kind] = est.hint()
    return out


# ------------------------------------------------------------------ the offer in inspect_source / setup


def offer_lines(
    ctx: AppContext, relation_sql: str, roles: FieldRoles, total_rows: int | None, cache_for: str | None = None
) -> list[str]:
    """The index offer: estimates for both kinds when the source has at least MIN_ROWS_FOR_OFFER entries.
    Runs trial builds (dropped again); nothing is built."""
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
        if cache_for is not None:
            _estimates(ctx.db)[(cache_for, kind)] = est
        out.append(f"{kind} index: {est.describe()}")
    out.append(
        "No index is built unless you ask for it (build_filter_index / build_search_index at setup, or create_index). "
        "A filter index lists values exactly and makes filters nearly free; a search index also speeds up text "
        "search and allows fuzzy search."
    )
    return out
