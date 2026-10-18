"""Structured files outside the mounted folder: read here (Parquet via pyarrow, JSON/JSONL) and copied."""

import csv
import json
import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any

from serenedb_extractor.catalog.models import FieldRoles
from serenedb_extractor.context import AppContext
from serenedb_extractor.db import quote_ident
from serenedb_extractor.errors import UserFacingError
from serenedb_extractor.setup.localfiles import open_local, require_file
from serenedb_extractor.setup.paths import ResolvedSource
from serenedb_extractor.setup.rawlog import parse_ts
from serenedb_extractor.setup.tablewrite import BATCH_ENTRIES, Writer, create_table, drop_table
from serenedb_extractor.timezones import get_zone

_ISO_FULL = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?(?:Z|[+-]\d{2}:?\d{2})?$")
SCHEMA_ROWS = 1000


_INT = re.compile(r"^[+-]?\d{1,18}$")
_FLOAT = re.compile(r"^[+-]?(?:\d+\.\d*|\.\d+|\d+)(?:[eE][+-]?\d+)?$")


def _csv_value(v: str | None) -> Any:
    """A CSV field as JSON-like data, so the JSON schema inference applies: numbers as numbers, empty as missing."""
    if v is None or v == "":
        return None
    if _INT.match(v):
        return int(v)
    if _FLOAT.match(v):
        return float(v)
    return v


def _csv_records(path: str) -> Iterator[dict[str, Any]]:
    with open_local(path) as f:
        head = f.read(65536)
        f.seek(0)
        try:
            dialect: Any = csv.Sniffer().sniff(head.splitlines()[0] if head else "", delimiters=",;\t|")
        except csv.Error:
            dialect = csv.excel
        for row in csv.DictReader(f, dialect=dialect):
            yield {k: _csv_value(v) for k, v in row.items() if k}


def _json_records(path: str) -> Iterator[dict[str, Any]]:
    with open_local(path) as f:
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
        for batch in pf.iter_batches(batch_size=BATCH_ENTRIES):
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
    rows: Iterator[dict[str, Any]]  # entries in file order
    total: int | None = None
    samples: list[dict[str, Any]] = field(default_factory=list)


def open_structured(rs: ResolvedSource, source: str, schema_limit: int | None = SCHEMA_ROWS) -> StructuredSource:
    """Open a local Parquet/JSON file for reading here. For JSON the schema comes from the first
    `schema_limit` entries (all of them when None)."""
    require_file(rs, source)
    if rs.kind == "parquet":
        cols, rows, total = _parquet_rows(rs.db_path)
        return StructuredSource(cols, rows, total)
    if rs.kind == "csv":
        cols = _infer_json(_csv_records(rs.db_path), schema_limit)
        if not cols:
            raise UserFacingError(f"{source} has no CSV rows to copy.")
        return StructuredSource(cols, _csv_records(rs.db_path))
    cols = _infer_json(_json_records(rs.db_path), schema_limit)
    if not cols:
        raise UserFacingError(f"{source} has no JSON entries to copy.")
    return StructuredSource(cols, _json_records(rs.db_path))


def peek_samples(src: StructuredSource, zone: Any, n: int = 5) -> list[dict[str, Any]]:
    """Up to n entries from the start of `src.rows`, converted to column values. This consumes them
    from `src.rows`, so use a source opened just for the preview."""
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
    create_table(ctx, relation, columns, key="entry_id" if add_id else None)
    try:
        writer = Writer(ctx, relation, [c for c, _ in columns])
        for i, rec in enumerate(src.rows, 1):
            row = tuple(_convert(rec.get(c), t, zone) for c, t in data_cols)
            writer.add(((i,) + row) if add_id else row)
        writer.flush()
    except BaseException:
        drop_table(ctx, relation)
        raise
    return StructuredCopy(relation, writer.total, columns), roles
