"""Copying into SereneDB: raw text logs (parsed here) and structured files outside the mounted folder.

Copied tables live in schema `extractor` as `lt_<name>` and are written through the writer role.
"""

import gzip
import json
import os
import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any

from serenedb_extractor.catalog.models import FieldRoles
from serenedb_extractor.context import AppContext
from serenedb_extractor.db import quote_ident
from serenedb_extractor.errors import UserFacingError
from serenedb_extractor.query.filters import get_zone
from serenedb_extractor.setup.paths import ResolvedSource, sql_literal
from serenedb_extractor.setup.rawlog import (
    RawEntry,
    head_lines,
    host_lines,
    line_format_named,
    parse_entries,
    parse_ts,
)
from serenedb_extractor.setup.sniff import readable

BATCH_ROWS = 2000
HEAD_LINES = 200
LARGE_BYTES = 1_000_000_000

RAW_COLUMNS: list[tuple[str, str]] = [
    ("entry_id", "BIGINT"),
    ("source_file", "VARCHAR"),
    ("line_start", "BIGINT"),
    ("line_end", "BIGINT"),
    ("ts", "TIMESTAMPTZ"),
    ("level", "VARCHAR"),
    ("component", "VARCHAR"),
    ("host", "VARCHAR"),
    ("message", "VARCHAR"),
    ("attrs", "JSON"),
]
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def copy_needed(rs: ResolvedSource) -> bool:
    """True when this process must read the file and stream it in: raw text always (it is parsed
    here), a structured local file when it is outside the mounted folder and exists on this machine."""
    if rs.kind == "raw_text":
        return True
    return rs.kind in ("parquet", "json") and not rs.remote and rs.host_path is None and os.path.isfile(rs.db_path)


def under_mount(rs: ResolvedSource) -> bool:
    return rs.host_path is not None


def large_copy_warning(rs: ResolvedSource) -> str | None:
    """Plain warning for a file over 1 GB that this process has to copy (outside the mounted folder)."""
    if under_mount(rs) or rs.size_bytes is None or rs.size_bytes <= LARGE_BYTES:
        return None
    from serenedb_extractor.setup.sniff import human_bytes

    return (
        f"Warning: this file is {human_bytes(rs.size_bytes)} and outside the mounted folder, so this is a full copy "
        "that is read here and streamed in; mounting the folder would avoid it."
    )


def drop_table(ctx: AppContext, relation: str) -> None:
    ctx.db.write(f"DROP TABLE IF EXISTS {relation}", {})


def _create_table(ctx: AppContext, relation: str, columns: list[tuple[str, str]], key: str | None = "entry_id") -> None:
    defs = ", ".join(f"{quote_ident(n)} {t}" + (" PRIMARY KEY" if n == key else "") for n, t in columns)
    drop_table(ctx, relation)
    ctx.db.write(f"CREATE TABLE {relation} ({defs})", {})


class _Writer:
    """Buffers rows and inserts them in batches."""

    def __init__(self, ctx: AppContext, relation: str, columns: list[str]) -> None:
        self.ctx, self.relation, self.columns = ctx, relation, columns
        self.rows: list[tuple[Any, ...]] = []
        self.total = 0

    def add(self, row: tuple[Any, ...]) -> None:
        self.rows.append(row)
        if len(self.rows) >= BATCH_ROWS:
            self.flush()

    def flush(self) -> None:
        if self.rows:
            self.total += self.ctx.db.copy_rows(self.relation, self.columns, self.rows)
            self.rows = []


# ---------------------------------------------------------------- raw text


def _mounted_sql(rs: ResolvedSource, limit: int | None = None) -> str:
    return (
        "SELECT line FROM read_csv("
        f"{sql_literal(rs.db_path)}, header=false, columns={{'line': 'VARCHAR'}}, delim='\\x01', quote='', escape='')"
        + (f" LIMIT {int(limit)}" if limit else "")
    )


def raw_head(ctx: AppContext, rs: ResolvedSource, source: str, n: int = HEAD_LINES) -> list[str]:
    """The first lines of a raw log: read by SereneDB under the mount, otherwise read here."""
    if under_mount(rs):
        with readable(source):
            rows = ctx.db.read(_mounted_sql(rs, n), {}).rows
        return [r[0] or "" for r in rows]
    _require_file(rs, source)
    return head_lines(rs.db_path)[:n]


def _require_file(rs: ResolvedSource, source: str) -> None:
    if not os.path.isfile(rs.db_path):
        raise UserFacingError(
            f"There is no file at {source} on this machine (and it is not under the mounted logs folder)."
        )


def raw_lines(ctx: AppContext, rs: ResolvedSource, source: str) -> Callable[[], Iterator[str]]:
    """A factory of line iterators over the whole file (each call starts again from line 1)."""
    if under_mount(rs):
        with readable(source):
            rows = ctx.db.read(_mounted_sql(rs), {}).rows
        return lambda: iter([r[0] or "" for r in rows])
    _require_file(rs, source)
    path = rs.db_path
    return lambda: host_lines(path)


@dataclass
class RawCopy:
    relation: str
    entries: int
    no_timestamp: int
    line_format: str
    roles: FieldRoles


def _sort_key(e: RawEntry) -> tuple[bool, datetime]:
    return (e.ts is not None, e.ts or _EPOCH)  # entries without a timestamp first


def copy_raw(
    ctx: AppContext,
    name: str,
    rs: ResolvedSource,
    source: str,
    line_format: str,
    tz: str,
) -> RawCopy:
    """Parse a raw log and copy its entries into extractor.lt_<name>, sorted by timestamp
    (NULLs first), entry_id numbered in that order. Raises with the table dropped on failure."""
    line_format_named(line_format)
    get_zone(tz)
    lines = raw_lines(ctx, rs, source)
    shown_file = rs.host_path or rs.db_path
    # Pass 1: count, see which fields exist, and find out whether the file is already in order.
    count = no_ts = 0
    seen = {"level": False, "component": False, "host": False}
    in_order = True
    last = _sort_key(RawEntry(0, 0, None, None, None, None, "", {}))
    for e in parse_entries(lines(), line_format, tz):
        count += 1
        no_ts += e.ts is None
        seen["level"] |= e.level is not None
        seen["component"] |= e.component is not None
        seen["host"] |= e.host is not None
        key = _sort_key(e)
        in_order &= key >= last
        last = key
    if count == 0:
        raise UserFacingError(f"{source} has no lines to copy.")
    relation = f"extractor.lt_{name}"
    _create_table(ctx, relation, RAW_COLUMNS)
    try:
        writer = _Writer(ctx, relation, [c for c, _ in RAW_COLUMNS])
        entries: Iterator[RawEntry] = parse_entries(lines(), line_format, tz)
        if not in_order:
            entries = iter(sorted(entries, key=_sort_key))  # stable: ties keep file order
        for i, e in enumerate(entries, 1):
            attrs = json.dumps(e.attrs) if e.attrs else None
            writer.add((i, shown_file, e.line_start, e.line_end, e.ts, e.level, e.component, e.host, e.message, attrs))
        writer.flush()
    except BaseException:
        drop_table(ctx, relation)
        raise
    quoted = quote_ident
    roles = FieldRoles(
        message=quoted("message"),
        timestamp=quoted("ts") if count > no_ts else None,
        level=quoted("level") if seen["level"] else None,
        component=quoted("component") if seen["component"] else None,
        host=quoted("host") if seen["host"] else None,
        order=quoted("entry_id"),
    )
    return RawCopy(relation, count, no_ts, line_format, roles)


# ---------------------------------------------------------------- structured files outside the mount

_ISO_FULL = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?(?:Z|[+-]\d{2}:?\d{2})?$")
SCHEMA_ROWS = 1000


def _json_records(path: str) -> Iterator[dict[str, Any]]:
    opener = gzip.open if path.lower().endswith(".gz") else open
    with opener(path, "rt", encoding="utf-8", errors="replace") as f:
        first = ""
        while (ch := f.read(1)) != "":
            if not ch.isspace():
                first = ch
                break
        f.seek(0)
        if first == "[":
            try:
                data = json.load(f)
            except ValueError as exc:
                raise UserFacingError(f"{path} is not valid JSON: {exc}") from None
            for item in data:
                if isinstance(item, dict):
                    yield item
            return
        for n, line in enumerate(f, 1):
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except ValueError:
                raise UserFacingError(f"Line {n} of {path} is not valid JSON, so the file can't be copied.") from None
            if isinstance(item, dict):
                yield item


def _arrow_type(t: Any) -> str:
    import pyarrow as pa

    if pa.types.is_timestamp(t):
        return "TIMESTAMPTZ"
    if pa.types.is_boolean(t):
        return "BOOLEAN"
    if pa.types.is_integer(t):
        return "BIGINT"
    if pa.types.is_floating(t):
        return "DOUBLE"
    if pa.types.is_string(t) or pa.types.is_large_string(t):
        return "VARCHAR"
    if pa.types.is_struct(t) or pa.types.is_list(t) or pa.types.is_large_list(t) or pa.types.is_map(t):
        return "JSON"
    return "VARCHAR"


def _parquet_rows(path: str) -> tuple[list[tuple[str, str]], Iterator[dict[str, Any]], int]:
    import pyarrow.parquet as pq

    try:
        pf = pq.ParquetFile(path)
    except Exception as exc:
        raise UserFacingError(f"{path} could not be read as Parquet: {' '.join(str(exc).split())[:200]}") from None
    cols = [(f.name, _arrow_type(f.type)) for f in pf.schema_arrow]

    def rows() -> Iterator[dict[str, Any]]:
        for batch in pf.iter_batches(batch_size=BATCH_ROWS):
            yield from batch.to_pylist()

    return cols, rows(), pf.metadata.num_rows


def _infer_json(records: Iterator[dict[str, Any]], limit: int | None) -> list[tuple[str, str]]:
    kinds: dict[str, set[str]] = {}
    for n, rec in enumerate(records):
        if limit is not None and n >= limit:
            break
        for k, v in rec.items():
            ks = kinds.setdefault(k, set())
            if v is None:
                continue
            if isinstance(v, bool):
                ks.add("bool")
            elif isinstance(v, int):
                ks.add("int")
            elif isinstance(v, float):
                ks.add("float")
            elif isinstance(v, str):
                ks.add("ts" if _ISO_FULL.match(v) else "str")
            else:
                ks.add("json")
    out: list[tuple[str, str]] = []
    for k, ks in kinds.items():
        if ks == {"bool"}:
            t = "BOOLEAN"
        elif ks == {"int"}:
            t = "BIGINT"
        elif ks and ks <= {"int", "float"}:
            t = "DOUBLE"
        elif ks == {"ts"}:
            t = "TIMESTAMPTZ"
        elif ks == {"json"}:
            t = "JSON"
        else:
            t = "VARCHAR"
        out.append((k, t))
    return out


def _convert(v: Any, sql_type: str, zone: Any) -> Any:
    if v is None:
        return None
    if sql_type == "TIMESTAMPTZ":
        if isinstance(v, datetime):
            return (v.replace(tzinfo=zone) if v.tzinfo is None else v).astimezone(UTC)
        return parse_ts(str(v), None, zone)
    if sql_type == "JSON":
        return json.dumps(v, default=str)
    if sql_type == "DOUBLE":
        return float(v)
    if sql_type in ("BIGINT", "BOOLEAN"):
        return v
    if isinstance(v, str):
        return v.replace("\x00", "")
    return json.dumps(v, default=str) if isinstance(v, (dict, list, bool)) else str(v)


@dataclass
class StructuredSource:
    columns: list[tuple[str, str]]
    rows: Iterator[dict[str, Any]]  # records in file order
    total: int | None = None
    samples: list[dict[str, Any]] = field(default_factory=list)


def open_structured(rs: ResolvedSource, source: str, schema_limit: int | None = SCHEMA_ROWS) -> StructuredSource:
    """Open a local Parquet/JSON file for reading here. For JSON the schema comes from the first
    `schema_limit` records (all of them when None)."""
    _require_file(rs, source)
    if rs.kind == "parquet":
        cols, rows, total = _parquet_rows(rs.db_path)
        return StructuredSource(cols, rows, total)
    cols = _infer_json(_json_records(rs.db_path), schema_limit)
    if not cols:
        raise UserFacingError(f"{source} has no JSON records to copy.")
    return StructuredSource(cols, _json_records(rs.db_path))


def peek_samples(src: StructuredSource, zone: Any, n: int = 5) -> list[dict[str, Any]]:
    """Up to n converted records (re-opens JSON; Parquet is read from a fresh batch)."""
    types = dict(src.columns)
    out = []
    for rec in src.rows:
        out.append({k: _convert(rec.get(k), t, zone) for k, t in types.items()})
        if len(out) >= n:
            break
    return out


@dataclass
class StructuredCopy:
    relation: str
    entries: int
    columns: list[tuple[str, str]]


def copy_structured(
    ctx: AppContext,
    name: str,
    rs: ResolvedSource,
    source: str,
    tz: str,
    roles_for: Callable[[list[tuple[str, str]], list[dict[str, Any]]], FieldRoles],
) -> tuple[StructuredCopy, FieldRoles]:
    """Stream a local Parquet/JSON file into extractor.lt_<name> in file order, adding `entry_id`.
    `roles_for(columns, samples)` decides the field roles once the columns are known."""
    zone = get_zone(tz)
    src = open_structured(rs, source, schema_limit=None)
    data_cols = src.columns
    add_id = "entry_id" not in {c for c, _ in data_cols}
    columns = ([("entry_id", "BIGINT")] if add_id else []) + data_cols
    sample_src = open_structured(rs, source)
    samples = peek_samples(sample_src, zone)
    roles = roles_for(data_cols, samples)
    if add_id:
        roles = replace(roles, order=quote_ident("entry_id"))
    relation = f"extractor.lt_{name}"
    _create_table(ctx, relation, columns, key="entry_id" if add_id else None)
    try:
        writer = _Writer(ctx, relation, [c for c, _ in columns])
        for i, rec in enumerate(src.rows, 1):
            row = tuple(_convert(rec.get(c), t, zone) for c, t in data_cols)
            writer.add(((i,) + row) if add_id else row)
        writer.flush()
    except BaseException:
        drop_table(ctx, relation)
        raise
    return StructuredCopy(relation, writer.total, columns), roles
