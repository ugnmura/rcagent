"""What a query over a log table's scope would read, from metadata only (spec section 6.2 step 1).

In-place Parquet: `parquet_metadata` gives per-row-group row counts, per-column compressed sizes
and timestamp min/max, so a time range is priced by the row groups it overlaps (SereneDB prunes
them when the literal is typed like the column; measured in #10, see the task report). In-place
JSON has no metadata: any query parses the whole file. Copied tables and table sources: an exact
`count(*)` and an average width per column from a few rows.
"""

import re
from dataclasses import dataclass, field

from serenedb_extractor.catalog.models import LogTable
from serenedb_extractor.db import Database, quote_ident
from serenedb_extractor.query.filters import TimeRange, time_clause
from serenedb_extractor.setup.paths import resolve_source, sql_literal
from serenedb_extractor.setup.roles import HELPER_COLUMNS, is_temporal, role_column
from serenedb_extractor.setup.sniff import relation_columns

WHOLE = "*"  # bytes_by_column key: read by every query whatever its columns (a JSON file is parsed whole)
JSON_BYTES_PER_ENTRY = 500  # a guess for remote JSON, whose size is unknown here
WIDTH_SAMPLE_ROWS = 1000
_LEAD_IDENT = re.compile(r'^"((?:[^"]|"")+)"')


@dataclass(frozen=True)
class GroupStat:
    """One Parquet row group that overlaps the time range: where its rows start and what it costs."""

    first_row: int  # its first file_row_number
    rows: int
    bytes_by_column: dict[str, int]


@dataclass(frozen=True)
class ScopeStats:
    total_rows: int
    rows_in_range: int  # whole row groups overlapping the range: an upper bound when the range cuts one
    bytes_by_column: dict[str, int]  # compressed bytes each column reads over the scope
    time_skippable: bool  # the time range skips row groups by their statistics
    remote: bool
    has_filter_index: bool
    has_search_index: bool
    # Block sampling needs a row-position column that SereneDB prunes on: `file_row_number` of a
    # single in-place Parquet file. With several files, `filename = … AND file_row_number …` does
    # not prune (measured in the #10 fix round), and copied tables, tables and JSON read every byte
    # anyway, so they never sample.
    can_sample: bool = False
    groups: tuple[GroupStat, ...] = field(default_factory=tuple)  # the in-range row groups, in file order
    rows_exact: bool = True  # False when rows_in_range is only the row-group upper bound

    def bytes_for(self, columns: list[str]) -> int:
        """Bytes read by a query that touches `columns`; a column listed twice (read by two scans)
        costs twice. Unknown names, like the helper columns, are free."""
        named = sum(self.bytes_by_column.get(c, 0) for c in columns if c != WHOLE)
        return named + self.bytes_by_column.get(WHOLE, 0)


def role_columns(expr: str | None) -> list[str]:
    """The column a stored role expression reads (`"col"` or `"col" ->> 'key'`)."""
    if not expr:
        return []
    col = role_column(expr)
    if col is not None:
        return [col]
    m = _LEAD_IDENT.match(expr.strip())
    return [m.group(1).replace('""', '"')] if m else []


def collect(db: Database, lt: LogTable, tr: TimeRange) -> ScopeStats:
    has_f, has_s = lt.filter_index_name is not None, lt.search_index_name is not None
    if lt.mode == "in_place" and lt.source_format == "parquet":
        return _parquet(db, lt, tr, has_f, has_s)
    if lt.mode == "in_place" and lt.source_format == "json":
        rs = resolve_source(lt.source, db.settings, "json")
        rows = int(lt.row_count or 0)
        size = rs.size_bytes if rs.size_bytes is not None else rows * JSON_BYTES_PER_ENTRY
        return ScopeStats(rows, rows, {WHOLE: int(size)}, False, rs.remote, has_f, has_s)
    return _table(db, lt, tr, has_f, has_s)


def _parquet(db: Database, lt: LogTable, tr: TimeRange, has_f: bool, has_s: bool) -> ScopeStats:
    rs = resolve_source(lt.source, db.settings, "parquet")
    meta = f"parquet_metadata({sql_literal(rs.db_path)})"
    ts_col = role_column(lt.roles.timestamp) if lt.roles.timestamp else None
    params: dict[str, object] = {"ts": ts_col or ""}
    what = f"reading the Parquet metadata of {lt.name}"
    skippable = False
    hit: dict[tuple[str, int], bool] = {}
    groups = db.read(
        f"SELECT file_name, row_group_id, max(row_group_num_rows) AS n FROM {meta} GROUP BY 1, 2", {}, what=what
    ).rows
    if tr.bounded and ts_col is not None:
        cols = dict(relation_columns(db, lt.relation, lt.source, rs.remote))
        typ = cols.get(ts_col, "").upper()
        if is_temporal(typ):
            skippable = True
            naive = "WITH TIME ZONE" not in typ and not typ.startswith("TIMESTAMPTZ")
            zone = sql_literal(lt.timezone)

            def bound(stat: str) -> str:  # try_cast: statistics are text and may be missing
                return f"try_cast({stat} AS timestamp) AT TIME ZONE {zone}" if naive else f"try_cast({stat} AS timestamptz)"

            bounds = []
            if tr.end is not None:
                bounds.append(f"{bound('stats_min')} < %(hi)s::timestamptz")
                params["hi"] = tr.end.isoformat()
            if tr.start is not None:
                bounds.append(f"{bound('stats_max')} >= %(lo)s::timestamptz")
                params["lo"] = tr.start.isoformat()
            # A group without usable statistics can't be skipped (coalesce to TRUE).
            ranges = db.read(
                f"SELECT file_name, row_group_id, coalesce({' AND '.join(bounds)}, TRUE) AS hit "
                f"FROM {meta} WHERE path_in_schema = %(ts)s",
                params,
                what=what,
            ).rows
            hit = {(r[0], r[1]): bool(r[2]) for r in ranges}
    per_col = db.read(
        f"SELECT file_name, row_group_id, split_part(path_in_schema, ', ', 1) AS c, "
        f"sum(total_compressed_size)::bigint AS b FROM {meta} GROUP BY 1, 2, 3",
        {},
        what=what,
    ).rows
    by_col: dict[str, int] = {}
    group_cols: dict[tuple[str, int], dict[str, int]] = {}
    for f, g, c, b in per_col:
        if hit.get((f, g), True):
            by_col[c] = by_col.get(c, 0) + int(b or 0)
            group_cols.setdefault((f, g), {})[c] = int(b or 0)
    for helper in HELPER_COLUMNS:
        by_col.setdefault(helper, 0)
    files = sorted({r[0] for r in groups})
    in_range_groups: list[GroupStat] = []
    first = 0
    for f, g, n in sorted(groups, key=lambda r: (r[0], r[1])):
        if f != files[0]:
            continue  # only a single file can be block-sampled; the others count via the totals below
        if hit.get((f, g), True):
            in_range_groups.append(GroupStat(first, int(n), group_cols.get((f, g), {})))
        first += int(n)
    total = sum(int(r[2]) for r in groups)
    in_range = sum(int(r[2]) for r in groups if hit.get((r[0], r[1]), True))
    single = len(files) == 1
    return ScopeStats(
        total_rows=total,
        rows_in_range=in_range,
        bytes_by_column=by_col,
        time_skippable=skippable,
        remote=rs.remote,
        has_filter_index=has_f,
        has_search_index=has_s,
        can_sample=single,
        groups=tuple(in_range_groups) if single else (),
        rows_exact=not tr.bounded,
    )


def _table(db: Database, lt: LogTable, tr: TimeRange, has_f: bool, has_s: bool) -> ScopeStats:
    cols = dict(relation_columns(db, lt.relation, lt.source))
    total = int(db.read(f"SELECT count(*) FROM {lt.relation}", {}, what=f"counting {lt.name}").scalar() or 0)
    rows_in_range = total
    if tr.bounded and lt.roles.timestamp is not None:
        where, params = time_clause(lt, tr, cols)
        rows_in_range = int(
            db.read(f"SELECT count(*) FROM {lt.relation} WHERE {where}", params, what=f"counting {lt.name}").scalar() or 0
        )
    names = list(cols)
    widths: dict[str, int] = {}
    if names and total:
        avgs = ", ".join(f"avg(octet_length(({quote_ident(c)})::varchar))" for c in names)
        row = db.read(
            f"SELECT {avgs} FROM (SELECT * FROM {lt.relation} LIMIT {WIDTH_SAMPLE_ROWS})", {}, what=f"sizing {lt.name}"
        ).rows[0]
        widths = {c: int(round(float(w or 0) * total)) for c, w in zip(names, row, strict=True)}
    return ScopeStats(total, rows_in_range, widths, False, False, has_f, has_s)  # counted exactly
