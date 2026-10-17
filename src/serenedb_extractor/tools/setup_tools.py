"""inspect_source and setup_log_table: structured sources read in place, raw text and outside files copied."""

from datetime import UTC, datetime
from typing import Any

from serenedb_extractor import format as fmt
from serenedb_extractor.catalog.models import ROLE_FIELDS, FieldRoles, LogTable, UnknownLogTable
from serenedb_extractor.context import AppContext
from serenedb_extractor.db import validate_name
import psycopg

from serenedb_extractor.errors import UserFacingError
from serenedb_extractor.setup import indexes, localfiles, rawcopy, structcopy
from serenedb_extractor.setup.paths import ResolvedSource, resolve_source
from serenedb_extractor.setup.rawlog import LINE_FORMATS, detect_line_format, line_format_named, parse_entries
from serenedb_extractor.setup.roles import HELPER_COLUMNS, propose_roles, role_lines, validate_roles
from serenedb_extractor.timezones import get_zone
from serenedb_extractor.setup.tablewrite import drop_table
from serenedb_extractor.setup.sniff import SourceInfo, human_bytes, readable, relation_columns, sample_values, sniff


OUTSIDE_MOUNT = "outside the mounted folder"
INDEX_AFTER_COPY = (
    "indexes: none is built unless you ask; once the copy exists, create_index with dry_run estimates their size."
)


def _why_copy(rs: ResolvedSource) -> str:
    """Plain sentence: why this local file is copied, and how it gets in."""
    if rs.kind == "raw_text":
        reason = (
            "Raw text logs are parsed once and copied into a table so that multi-line entries such as stack traces "
            "are joined into one entry"
        )
        if rs.host_path:
            return f"{reason}. The file is under the mounted folder, so it is read by SereneDB and parsed here."
        return f"{reason}. The file is {OUTSIDE_MOUNT}, so it is read here and streamed in."
    return (
        f"This file is {OUTSIDE_MOUNT} (SereneDB cannot reach it), so it is read here and streamed into a "
        "copied table; mounting the folder would avoid the copy."
    )


def _where_read(rs: ResolvedSource) -> str:
    if rs.kind == "table":
        return "read in place (an existing table; nothing is copied)"
    if rs.remote:
        return "read in place from the remote location by SereneDB (nothing is downloaded or copied)"
    return "read in place by SereneDB (nothing is copied)"


def inspect_source(
    ctx: AppContext, source: str, format_hint: str | None = None, line_format: str | None = None
) -> str:
    rs = resolve_source(source, ctx.settings, format_hint)
    if rs.kind == "raw_text":
        return _inspect_raw(ctx, rs, source, line_format)
    if localfiles.copy_needed(rs):
        return _inspect_outside(ctx, rs, source)
    info = sniff(ctx.db, rs, source)  # reports SereneDB errors in plain language
    columns = [(c, t) for c, t in info.columns if c not in HELPER_COLUMNS]
    roles, evidence = propose_roles(info.columns, sample_values(info))
    offer = indexes.inspect_lines(
        ctx, source, info.resolved.db_path if info.resolved.kind == "parquet" else None, roles, info.row_count
    )
    lines = [
        fmt.how_measured(
            "read only metadata and 5 sample entries; nothing was created or changed", sample="5 sample entries"
        ),
        f"source: {source} ({rs.kind})",
        f"how it will be used: {_where_read(rs)}",
    ]
    size = []
    if info.row_count is not None:
        size.append(f"{info.row_count:,} entries")
    if info.num_files:
        size.append(f"{info.num_files} file(s)")
    if info.size_bytes is not None:
        size.append(human_bytes(info.size_bytes))
    if info.row_groups:
        size.append(f"{info.row_groups:,} row groups")
    if size:
        lines.append("size: " + ", ".join(size))
    lines.append(f"columns ({len(columns)}): " + ", ".join(f"{c} {t}" for c, t in columns))
    if info.big_columns:
        lines.append("largest columns (compressed): " + ", ".join(f"{c} {human_bytes(b)}" for c, b in info.big_columns))
    lines.append("proposed field roles (confirm or correct):")
    lines += role_lines(roles, "  ")
    for role in ROLE_FIELDS:
        if role in evidence:
            lines.append(f"  why {role}: {evidence[role]}")
        elif getattr(roles, role) is None and role != "order":
            lines.append(f"  why {role}: no matching column")
    lines.append("sample entries:")
    for i, row in enumerate(info.samples, 1):
        shown = ", ".join(f"{k}={fmt.shorten(str(v), 80)}" for k, v in row.items() if k not in HELPER_COLUMNS)
        lines.append(f"  {i}. {shown}")
    lines += offer
    return "\n".join(lines)


def _merge(base: FieldRoles, changes: dict[str, str | None]) -> FieldRoles:
    return FieldRoles(**{**vars(base), **changes})


def _existing(ctx: AppContext, name: str) -> LogTable | None:
    try:
        return ctx.store.get_log_table(name)
    except UnknownLogTable:
        return None


def _rerun(ctx: AppContext, lt: LogTable, source: str, roles: dict[str, Any] | None, timezone: str | None) -> str:
    ctx.estimates.clear(lt.source)  # estimates were made for the old setup
    if source.strip() != lt.source:
        raise UserFacingError(
            f"Log table '{lt.name}' already exists for {lt.source}. Re-running setup only corrects field roles "
            "and the time zone; pick another name for a different source."
        )
    if timezone is not None:
        get_zone(timezone)
        if lt.mode == "copied" and timezone != lt.timezone:
            raise UserFacingError(
                f"Log table '{lt.name}' is a copy whose timestamps were read as {lt.timezone} when it was copied, "
                "so the time zone can't be changed now. Set it up again under another name with the zone you want."
            )
    changes: list[str] = []
    new_roles = lt.roles
    if roles:
        with readable(lt.source):
            cols = dict(relation_columns(ctx.db, lt.relation, lt.source))
        wanted = validate_roles(roles, cols)
        changed = [r for r, v in wanted.items() if getattr(lt.roles, r) != v]
        if changed:
            new_roles = _merge(lt.roles, wanted)
            ctx.store.update_roles(lt.name, new_roles)
            changes.append(f"updated field roles: {', '.join(changed)}")
    if timezone is not None and timezone != lt.timezone:
        ctx.store.set_timezone(lt.name, timezone)
        changes.append(f"updated time zone: {timezone}")
    header = fmt.how_measured("log table settings updated; no data was read")
    if not changes:
        return header + f"\nLog table '{lt.name}' is already set up and nothing changed. Pass roles={{...}} or timezone to correct them."
    out = [header, f"Log table '{lt.name}': {'; '.join(changes)}. Nothing else changed.", "field roles now:"]
    return "\n".join(out + role_lines(new_roles, "  "))


def setup_log_table(
    ctx: AppContext,
    name: str,
    source: str,
    roles: dict[str, Any] | None = None,
    line_format: str | None = None,
    timezone: str | None = None,
    build_filter_index: bool = False,
    build_search_index: bool = False,
) -> str:
    validate_name(name)
    ctx.estimates.clear(source)
    existing = _existing(ctx, name)
    if existing is not None:
        return _rerun(ctx, existing, source, roles, timezone)
    zone = timezone or "UTC"
    get_zone(zone)
    rs = resolve_source(source, ctx.settings, None)
    if rs.kind == "raw_text":
        return _setup_raw(ctx, name, rs, source, roles, line_format, zone, (build_filter_index, build_search_index))
    if localfiles.copy_needed(rs):
        return _setup_outside(ctx, name, rs, source, roles, zone, (build_filter_index, build_search_index))
    info = sniff(ctx.db, rs, source)
    given = validate_roles(roles, dict(info.columns)) if roles else None
    final, _ = propose_roles(info.columns, sample_values(info), given)
    with readable(source, rs.remote):
        relation = _create_relation(ctx, name, info)
        now = datetime.now(UTC).replace(tzinfo=None)
        lt = LogTable(
            name=name,
            source=source.strip(),
            source_format=rs.kind,
            mode="in_place",
            relation=relation,
            roles=final,
            filter_index_name=None,
            search_index_name=None,
            row_count=_row_count(ctx, info, relation),
            timezone=zone,
            created_at=now,
            roles_updated_at=now,
        )
        try:
            ctx.store.create_log_table(lt)
        except Exception:
            ctx.db.write(f"DROP VIEW IF EXISTS {relation}", {})
            raise
    index_lines, read_data = _index_section(ctx, lt, build_filter_index, build_search_index)
    lines = [
        fmt.how_measured(
            "log table registered; only the source's metadata and 5 sample entries were read"
            + (index_lines_how(read_data) if read_data else "")
        ),
        f"Set up log table '{name}': {_where_read(rs)}."
        + f" View {relation} reads the source directly.",
        f"entries: {lt.row_count:,}" if lt.row_count is not None else "entries: not counted",
        f"time zone for naive timestamps: {zone}",
        "field roles:",
        *role_lines(final, "  "),
        "The template catalog starts empty.",
    ]
    lines += index_lines
    return "\n".join(lines)


def _create_relation(ctx: AppContext, name: str, info: SourceInfo) -> str:
    # Also for a table source: the view keeps everything this server creates (indexes included) in the
    # extractor schema; nothing is ever created in the user's schema.
    relation = f"extractor.lt_{name}"
    ctx.db.write(f"CREATE OR REPLACE VIEW {relation} AS SELECT * FROM {info.from_sql}", {})
    return relation


def _row_count(ctx: AppContext, info: SourceInfo, relation: str) -> int | None:
    if info.row_count is not None:
        return int(info.row_count)
    return int(ctx.db.read(f"SELECT count(*) FROM {relation}", {}).scalar())


# ---------------------------------------------------------------- copied sources


def _size_lines(rs: ResolvedSource) -> list[str]:
    out = []
    if rs.size_bytes is not None:
        out.append(f"size: {human_bytes(rs.size_bytes)}")
    return out + localfiles.large_input_notes(rs)


def _chosen_format(ctx: AppContext, rs: ResolvedSource, source: str, line_format: str | None) -> tuple[str, str]:
    """(format name, how it was chosen)."""
    if line_format:
        return line_format_named(line_format).name, "given by you"
    return detect_line_format(rawcopy.raw_head(ctx, rs, source)), "recognised from the first lines"


def _inspect_raw(ctx: AppContext, rs: ResolvedSource, source: str, line_format: str | None) -> str:
    head = rawcopy.raw_head(ctx, rs, source)
    name, how = _chosen_format(ctx, rs, source, line_format)
    entries = list(parse_entries(head, name, "UTC"))[:5]
    lines = [
        fmt.how_measured(
            "read only the first lines of the file; nothing was created or changed", sample="the first lines"
        ),
        f"source: {source} (raw_text)",
        f"how it will be used: {_why_copy(rs)}",
        *_size_lines(rs),
        f"line format: {name} ({how}); known formats: {', '.join(LINE_FORMATS)}",
        "pattern: " + LINE_FORMATS[name].describes,
        "columns of the copied table: " + ", ".join(f"{c} {t}" for c, t in rawcopy.RAW_COLUMNS),
        "proposed field roles (confirm or correct):",
        "  message: message",
        "  timestamp: ts" + ("" if any(e.ts for e in entries) else "  (none found in the first lines)"),
        "  level: level",
        "  component: component",
        "  host: host",
        "  order: entry_id",
        "sample entries:",
    ]
    for i, e in enumerate(entries, 1):
        shown = ", ".join(
            f"{k}={fmt.shorten(str(v), 80)}"
            for k, v in (
                ("lines", f"{e.line_start}-{e.line_end}"),
                ("ts", e.ts.isoformat() if e.ts else None),
                ("level", e.level),
                ("component", e.component),
                ("host", e.host),
                ("message", e.message.replace("\n", " ⏎ ")),
            )
            if v is not None
        )
        lines.append(f"  {i}. {shown}")
    if not entries:
        lines.append("  (no lines)")
    lines.append(INDEX_AFTER_COPY)
    return "\n".join(lines)


def _sample_strings(samples: list[dict[str, Any]]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for row in samples:
        for k, v in row.items():
            if v is not None:
                out.setdefault(k, []).append(fmt.shorten(str(v), 80))
    return out


def _inspect_outside(ctx: AppContext, rs: ResolvedSource, source: str) -> str:
    src = structcopy.open_structured(rs, source)
    samples = structcopy.peek_samples(src, get_zone("UTC"))
    columns = src.columns
    roles, evidence = propose_roles(columns, _sample_strings(samples))
    lines = [
        fmt.how_measured(
            f"read only the schema and {len(samples)} sample entries; nothing was created or changed",
            sample=f"{len(samples)} sample entries",
        ),
        f"source: {source} ({rs.kind})",
        f"how it will be used: {_why_copy(rs)}",
        *_size_lines(rs),
        *([f"entries: {src.total:,}"] if src.total is not None else []),
        f"columns ({len(columns)}): " + ", ".join(f"{c} {t}" for c, t in columns),
        "proposed field roles (confirm or correct):",
        *role_lines(roles, "  "),
    ]
    for role in ROLE_FIELDS:
        if role in evidence:
            lines.append(f"  why {role}: {evidence[role]}")
    lines.append("sample entries:")
    for i, row in enumerate(samples, 1):
        lines.append(f"  {i}. " + ", ".join(f"{k}={fmt.shorten(str(v), 80)}" for k, v in row.items()))
    lines.append(INDEX_AFTER_COPY)
    return "\n".join(lines)


def _register_copied(
    ctx: AppContext, name: str, source: str, source_format: str, relation: str, roles: FieldRoles, rows: int, zone: str
) -> LogTable:
    now = datetime.now(UTC).replace(tzinfo=None)
    lt = LogTable(
        name=name,
        source=source.strip(),
        source_format=source_format,
        mode="copied",
        relation=relation,
        roles=roles,
        filter_index_name=None,
        search_index_name=None,
        row_count=rows,
        timezone=zone,
        created_at=now,
        roles_updated_at=now,
    )
    try:
        ctx.store.create_log_table(lt)
    except BaseException:
        drop_table(ctx, relation)
        raise
    return lt


def _copied_summary(
    ctx: AppContext, lt: LogTable, rs: ResolvedSource, extra: list[str], build: tuple[bool, bool], how: str
) -> str:
    index_lines, read_data = _index_section(ctx, lt, *build)
    lines = [
        fmt.how_measured(how + (index_lines_how(read_data) if read_data else "")),
        f"Set up log table '{lt.name}': {_why_copy(rs)}",
        f"The copy is {lt.relation} ({lt.row_count:,} entries); the original file was not changed.",
        *_size_lines(rs),
        *extra,
        f"time zone for timestamps without one: {lt.timezone}",
        "field roles:",
        *role_lines(lt.roles, "  "),
        "The template catalog starts empty.",
        *index_lines,
    ]
    return "\n".join(lines)


def _setup_raw(
    ctx: AppContext,
    name: str,
    rs: ResolvedSource,
    source: str,
    roles: dict[str, Any] | None,
    line_format: str | None,
    zone: str,
    build: tuple[bool, bool] = (False, False),
) -> str:
    given = validate_roles(roles, dict(rawcopy.RAW_COLUMNS)) if roles else {}
    fmt_name, how = _chosen_format(ctx, rs, source, line_format)
    with readable(source):
        result = rawcopy.copy_raw(ctx, name, rs, source, fmt_name, zone)
    final = _merge(result.roles, given) if given else result.roles
    lt = _register_copied(ctx, name, source, "raw_text", result.relation, final, result.entries, zone)
    extra = [f"line format: {fmt_name} ({how})"]
    if result.no_timestamp:
        n = result.no_timestamp
        extra.append(
            f"{n:,} {'entry has' if n == 1 else 'entries have'} no timestamp: "
            + "kept, but a question about a time range can't place them"
        )
    if result.bad_lines:
        n = result.bad_lines
        extra.append(
            f"{n:,} {'line' if n == 1 else 'lines'} had bytes that are not valid UTF-8; "
            "they were replaced with the character �"
        )
    return _copied_summary(ctx, lt, rs, extra, build, "every line of the file was read and parsed; entries were copied into a table")


def _setup_outside(
    ctx: AppContext,
    name: str,
    rs: ResolvedSource,
    source: str,
    roles: dict[str, Any] | None,
    zone: str,
    build: tuple[bool, bool] = (False, False),
) -> str:
    def roles_for(columns: list[tuple[str, str]], samples: list[dict[str, Any]]) -> FieldRoles:
        given = validate_roles(roles, dict(columns)) if roles else None
        final, _ = propose_roles(columns, _sample_strings(samples), given)
        return final

    result, final = structcopy.copy_structured(ctx, name, rs, source, zone, roles_for)
    lt = _register_copied(ctx, name, source, rs.kind, result.relation, final, result.entries, zone)
    return _copied_summary(ctx, lt, rs, [], build, "every entry of the file was read here and copied into a table")


# ---------------------------------------------------------------- indexes


def index_lines_how(read_data: bool) -> str:
    return "; trial or real index builds read the entries (see the index lines)" if read_data else ""


def _index_section(ctx: AppContext, lt: LogTable, build_filter: bool, build_search: bool) -> tuple[list[str], bool]:
    """Lines about indexes for a fresh log table, and whether entries were read for them. A requested
    build runs now; otherwise estimates are shown for a big source. A failed build leaves the table set up."""
    wanted = [k for k, on in (("filter", build_filter), ("search", build_search)) if on]
    if not wanted:
        out = indexes.offer_lines(ctx, lt.relation, lt.roles, lt.row_count, lt.source)
        big = lt.row_count is not None and lt.row_count >= indexes.MIN_ROWS_FOR_OFFER
        return out + ["No index was built."], big
    out = []
    for kind in wanted:
        try:
            built = indexes.build_measured(ctx, lt, kind)
            out.append(_built_line(kind, built))
        except (psycopg.Error, UserFacingError) as exc:
            out.append(f"The {kind} index could not be built ({exc}); the log table is set up without it.")
    return out, True


def _built_line(kind: str, built: indexes.BuiltIndex) -> str:
    return f"Built the {kind} index {built.name}: {human_bytes(built.size_bytes)} on disk, built in {fmt.duration(built.seconds)}."


def create_index(ctx: AppContext, log_table: str, kind: str, dry_run: bool = False) -> str:
    kind = indexes.check_kind(kind)
    lt = ctx.store.get_log_table(log_table)
    have = lt.filter_index_name if kind == "filter" else lt.search_index_name
    if have:
        return (
            fmt.how_measured("catalog only; nothing was read or built")
            + f"\nLog table '{lt.name}' already has its {kind} index {have}; nothing changed."
        )
    with readable(f"the source of log table '{lt.name}'"):
        if dry_run:
            est = indexes.estimate(ctx, lt, kind)
            return "\n".join(
                [
                    fmt.how_measured(
                        f"a trial {kind} index was built on {est.sample_rows:,} of {est.total_rows:,} entries "
                        "and dropped again; size and time are scaled up linearly",
                        sample=f"{est.sample_rows:,} entries",
                    ),
                    f"Estimated {kind} index for log table '{lt.name}': {est.describe()}.",
                    *(
                        [
                            f"Warning: that is longer than the server's maximum time for one statement "
                            f"({fmt.duration(ctx.settings.max_timeout_s)}), so a build would be cancelled."
                        ]
                        if est.build_seconds > ctx.settings.max_timeout_s
                        else []
                    ),
                    "Nothing was built. Run create_index again without dry_run to build it.",
                ]
            )
        built = indexes.build_measured(ctx, lt, kind)
    note = {
        "filter": "describe_logs now lists values exactly and filters on the indexed fields cost almost nothing.",
        "search": "search_logs uses it for text search, and fuzzy search is available.",
    }[kind]
    return "\n".join(
        [
            fmt.how_measured(f"the {kind} index was built over every entry of the log table"),
            _built_line(kind, built),
            note,
        ]
    )
