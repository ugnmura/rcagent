"""Raw text logs: parsed here and copied into `extractor.lt_<name>`, one entry per (multi-line) log entry."""

import gzip
import json
import zlib
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime

from rcagent.catalog.models import FieldRoles
from rcagent.context import AppContext
from rcagent.db import quote_ident
from rcagent.errors import UserFacingError
from rcagent.setup.localfiles import head_lines, host_lines, require_file, split_lines, under_mount
from rcagent.setup.paths import ResolvedSource, sql_literal
from rcagent.setup.rawlog import LINE_FORMATS, RawEntry, line_format_named, parse_entries
from rcagent.setup.sniff import readable
from rcagent.setup.tablewrite import Writer, create_table, drop_table
from rcagent.timezones import get_zone

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
    """The exact content of a file under the mounted folder, read by SereneDB. Plain files use
    `read_text`; gzipped ones come as bytes (`read_blob`, which SereneDB does not decompress) and are
    unzipped here, decoded like host files (UTF-8, bad bytes replaced). `chars` limits the text."""
    path = sql_literal(rs.db_path)
    with readable(source):
        if not rs.db_path.lower().endswith(".gz"):
            expr = "content" if chars is None else f"substr(content, 1, {int(chars)})"
            return str(ctx.db.read(f"SELECT {expr} FROM read_text({path})", {}).scalar() or "")
        blob = ctx.db.read(f"SELECT content FROM read_blob({path})", {}).scalar() or b""
    try:
        if chars is None:
            data = gzip.decompress(bytes(blob))
        else:
            data = zlib.decompressobj(wbits=31).decompress(bytes(blob), chars * 4)  # up to 4 bytes per char
    except (OSError, EOFError, zlib.error):
        raise UserFacingError(f"{source} is not a readable gzip file.") from None
    text = data.decode("utf-8", errors="replace")
    return text if chars is None else text[:chars]


def raw_head(ctx: AppContext, rs: ResolvedSource, source: str, n: int = HEAD_LINES) -> list[str]:
    """The first lines of a raw log: read by SereneDB under the mount, otherwise read here. A last
    line that the size limit may have cut is dropped, as for host files."""
    if under_mount(rs):
        text = _mounted_text(ctx, rs, source, HEAD_CHARS)
        lines = split_lines(text)
        if len(text) >= HEAD_CHARS and len(lines) > 1:
            lines.pop()
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
    explicit: bool = False,
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
    seen = {"level": False, "component": False, "host": False, "service": False, "trace": False}
    in_order = True
    last = _sort_key(RawEntry(0, 0, None, None, None, None, "", {}))
    for e in parse_entries(counted(), line_format, tz):
        count += 1
        no_ts += e.ts is None
        seen["level"] |= e.level is not None
        seen["component"] |= e.component is not None
        seen["host"] |= e.host is not None
        seen["service"] |= "service" in e.attrs
        seen["trace"] |= "trace" in e.attrs
        key = _sort_key(e)
        in_order &= key >= last
        last = key
    if count == 0:
        raise UserFacingError(f"{source} has no lines to copy.")
    if no_ts == count and line_format != "lines":  # no line matched: everything would collapse into one entry
        fmt_ = line_format_named(line_format)
        if explicit:
            others = ", ".join(n for n in LINE_FORMATS if n != fmt_.name)
            raise UserFacingError(
                f"No line of {source} matches the {fmt_.name} line format ({fmt_.describes}), so it can't be split "
                f"into entries. Try another line_format ({others}); the generic one needs an ISO time "
                "(2026-03-15T09:30:00) at the start of each line. inspect_source shows the first lines."
            )
        return copy_raw(ctx, name, rs, source, "lines", tz, explicit=True)
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
        service="attrs ->> 'service'" if seen["service"] else None,
        trace="attrs ->> 'trace'" if seen["trace"] else None,
        order=quote_ident("entry_id"),
    )
    return RawCopy(relation, count, no_ts, line_format, roles, bad_lines)
