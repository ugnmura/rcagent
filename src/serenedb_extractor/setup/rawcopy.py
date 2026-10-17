"""Raw text logs: parsed here and copied into `extractor.lt_<name>`, one entry per (multi-line) log entry."""

import json
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime

from serenedb_extractor.catalog.models import FieldRoles
from serenedb_extractor.context import AppContext
from serenedb_extractor.db import quote_ident
from serenedb_extractor.errors import UserFacingError
from serenedb_extractor.setup.localfiles import head_lines, host_lines, require_file, split_lines, under_mount
from serenedb_extractor.setup.paths import ResolvedSource, sql_literal
from serenedb_extractor.setup.rawlog import RawEntry, line_format_named, parse_entries
from serenedb_extractor.setup.sniff import readable
from serenedb_extractor.setup.tablewrite import Writer, create_table, drop_table
from serenedb_extractor.timezones import get_zone

HEAD_LINES = 200
HEAD_CHARS = 262_144

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


def _mounted_text(ctx: AppContext, rs: ResolvedSource, source: str, chars: int | None = None) -> str:
    """The exact content of a file under the mounted folder, read by SereneDB (`read_text`)."""
    expr = "content" if chars is None else f"substr(content, 1, {int(chars)})"
    with readable(source):
        value = ctx.db.read(f"SELECT {expr} FROM read_text({sql_literal(rs.db_path)})", {}).scalar()
    return str(value or "")


def raw_head(ctx: AppContext, rs: ResolvedSource, source: str, n: int = HEAD_LINES) -> list[str]:
    """The first lines of a raw log: read by SereneDB under the mount, otherwise read here."""
    if under_mount(rs):
        lines = split_lines(_mounted_text(ctx, rs, source, HEAD_CHARS))
        return lines[:n]
    require_file(rs, source)
    return head_lines(rs.db_path)[:n]


def raw_lines(ctx: AppContext, rs: ResolvedSource, source: str) -> Callable[[], Iterator[str]]:
    """A factory of line iterators over the whole file (each call starts again from line 1)."""
    if under_mount(rs):
        lines = split_lines(_mounted_text(ctx, rs, source))
        return lambda: iter(lines)
    require_file(rs, source)
    path = rs.db_path
    return lambda: host_lines(path)


@dataclass
class RawCopy:
    relation: str
    entries: int
    no_timestamp: int
    line_format: str
    roles: FieldRoles
    bad_lines: int = 0  # lines in which undecodable bytes were replaced


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
    bad_lines = 0

    def counted() -> Iterator[str]:
        nonlocal bad_lines
        for line in lines():
            bad_lines += "�" in line
            yield line

    # Pass 1: count, see which fields exist, and find out whether the file is already in order.
    count = no_ts = 0
    seen = {"level": False, "component": False, "host": False}
    in_order = True
    last = _sort_key(RawEntry(0, 0, None, None, None, None, "", {}))
    for e in parse_entries(counted(), line_format, tz):
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
    create_table(ctx, relation, RAW_COLUMNS)
    try:
        writer = Writer(ctx, relation, [c for c, _ in RAW_COLUMNS])
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
    roles = FieldRoles(
        message=quote_ident("message"),
        timestamp=quote_ident("ts") if count > no_ts else None,
        level=quote_ident("level") if seen["level"] else None,
        component=quote_ident("component") if seen["component"] else None,
        host=quote_ident("host") if seen["host"] else None,
        order=quote_ident("entry_id"),
    )
    return RawCopy(relation, count, no_ts, line_format, roles, bad_lines)
