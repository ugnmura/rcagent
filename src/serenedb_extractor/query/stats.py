"""What a query over a log table's scope would read, from metadata only (spec section 6.2 step 1).

In-place Parquet: `parquet_metadata` gives per-row-group row counts, per-column compressed sizes
and timestamp min/max, so a time range is priced by the row groups it overlaps (SereneDB prunes
them when the literal is typed like the column; measured in #10, see the task report). In-place
JSON has no metadata: any query parses the whole file. Copied tables and table sources: an exact
`count(*)` and an average width per column from a few rows.
"""

import math
import re
from dataclasses import dataclass, field
from statistics import median

from serenedb_extractor.catalog.models import LogTable
from serenedb_extractor.db import Database, quote_ident
from serenedb_extractor.query.filters import TimeRange, time_clause
from serenedb_extractor.setup.paths import resolve_source, sql_literal
from serenedb_extractor.setup.roles import HELPER_COLUMNS, is_temporal, role_column
from serenedb_extractor.setup.sniff import relation_columns

WHOLE = "*"  # bytes_by_column key: read by every query whatever its columns (a JSON file is parsed whole)
VECTOR_ROWS = 2048  # SereneDB's vector size: the smallest block worth sampling inside one row group
MAX_BLOCKS_LISTED = 4096  # keep the IN-list of a block sample short by using bigger aligned blocks
JSON_BYTES_PER_ENTRY = 500  # a guess for remote JSON, whose size is unknown here
WIDTH_SAMPLE_ROWS = 1000
_LEAD_IDENT = re.compile(r'^"((?:[^"]|"")+)"')


@dataclass(frozen=True)
class ScopeStats:
    total_rows: int
    rows_in_range: int  # whole row groups overlapping the range (an upper bound when one is cut)
    bytes_by_column: dict[str, int]  # compressed bytes each column reads over the scope
    time_skippable: bool  # the time range skips row groups by their statistics
    remote: bool
    has_filter_index: bool
    has_search_index: bool
    can_sample: bool = False  # a block sample reads proportionally fewer bytes (in-place Parquet)
    row_group_rows: int = VECTOR_ROWS  # typical rows per row group
    file_rows: tuple[int, ...] = field(default_factory=tuple)  # rows per file, for exact sampled fractions

    def bytes_for(self, columns: list[str]) -> int:
        """Bytes read by a query that touches `columns` (unknown names, like helper columns, are free)."""
        named = sum(self.bytes_by_column.get(c, 0) for c in dict.fromkeys(columns) if c != WHOLE)
        return named + self.bytes_by_column.get(WHOLE, 0)

    def blocks(self, stride: int) -> tuple[int, tuple[int, ...], float]:
        """Every `stride`-th block of row numbers in each file: (block_rows, chosen blocks, exact
        fraction of rows they hold). Blocks are whole row groups (multiples, for short IN-lists)
        when a file has several, so SereneDB skips the rest; inside a single row group they are
        vector-sized and save work but not bytes."""
        files = self.file_rows or (self.total_rows,)
        longest = max(files) if files else 0
        rg = max(1, self.row_group_rows)
        block = rg if longest >= 2 * rg else min(rg, VECTOR_ROWS)
        while math.ceil(longest / block) / max(stride, 1) > MAX_BLOCKS_LISTED:
            block *= 2
        n_blocks = max(1, math.ceil(longest / block))
        chosen = tuple(range(0, n_blocks, max(stride, 1)))
        total = sum(files)
        picked = sum(max(0, min(block, rows - b * block)) for rows in files for b in chosen)
        return block, chosen, (picked / total if total else 1.0)


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
    for f, g, c, b in per_col:
        if hit.get((f, g), True):
            by_col[c] = by_col.get(c, 0) + int(b or 0)
    for helper in HELPER_COLUMNS:
        by_col.setdefault(helper, 0)
    files: dict[str, int] = {}
    for f, _, n in groups:
        files[f] = files.get(f, 0) + int(n)
    total = sum(files.values())
    in_range = sum(int(r[2]) for r in groups if hit.get((r[0], r[1]), True))
    sizes = [int(r[2]) for r in groups] or [VECTOR_ROWS]
    return ScopeStats(
        total_rows=total,
        rows_in_range=in_range,
        bytes_by_column=by_col,
        time_skippable=skippable,
        remote=rs.remote,
        has_filter_index=has_f,
        has_search_index=has_s,
        can_sample=True,
        row_group_rows=int(median(sizes)),
        file_rows=tuple(files[k] for k in sorted(files)),
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
    return ScopeStats(total, rows_in_range, widths, False, False, has_f, has_s)
