"""inspect_source and setup_log_table: structured sources, read in place."""

from datetime import UTC, datetime
from typing import Any

from serenedb_extractor import format as fmt
from serenedb_extractor.catalog.models import ROLE_FIELDS, FieldRoles, LogTable, UnknownLogTable
from serenedb_extractor.context import AppContext
from serenedb_extractor.db import validate_name
from serenedb_extractor.errors import UserFacingError
from serenedb_extractor.query.filters import get_zone
from serenedb_extractor.setup.paths import ResolvedSource, resolve_source
from serenedb_extractor.setup.roles import HELPER_COLUMNS, propose_roles, validate_roles
from serenedb_extractor.setup.sniff import SourceInfo, human_bytes, relation_columns, sample_values, sniff
from serenedb_extractor.tools.describe import role_lines

RAW_TEXT_UNAVAILABLE = (
    "This is a raw text log (plain lines rather than structured fields). Setting up and inspecting "
    "raw text logs isn't available yet; structured Parquet and JSON sources and existing tables work now."
)


def _structured(source: str, ctx: AppContext, format_hint: str | None) -> ResolvedSource:
    rs = resolve_source(source, ctx.settings, format_hint)
    if rs.kind == "raw_text":
        raise UserFacingError(RAW_TEXT_UNAVAILABLE)
    return rs


def _where_read(rs: ResolvedSource) -> str:
    if rs.kind == "table":
        return "read in place (an existing table; nothing is copied)"
    if rs.remote:
        return "read in place from the remote location by SereneDB (nothing is downloaded or copied)"
    return "read in place by SereneDB (nothing is copied)"


def inspect_source(
    ctx: AppContext, source: str, format_hint: str | None = None, line_format: str | None = None
) -> str:
    rs = _structured(source, ctx, format_hint)
    info = sniff(ctx.db, rs, source)
    columns = [(c, t) for c, t in info.columns if c not in HELPER_COLUMNS]
    roles, evidence = propose_roles(info.columns, sample_values(info))
    lines = [
        fmt.how_measured(
            "read only metadata and 5 sample entries; nothing was created or changed", sample="5 sample entries"
        ),
        f"source: {source} ({rs.kind})",
        f"how it will be used: {_where_read(rs)}",
    ]
    size = []
    if info.row_count is not None:
        size.append(f"{info.row_count:,} rows")
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
    return "\n".join(lines)


def _merge(base: FieldRoles, changes: dict[str, str | None]) -> FieldRoles:
    return FieldRoles(**{**vars(base), **changes})


def _existing(ctx: AppContext, name: str) -> LogTable | None:
    try:
        return ctx.store.get_log_table(name)
    except UnknownLogTable:
        return None


def _rerun(ctx: AppContext, lt: LogTable, source: str, roles: dict[str, Any] | None) -> str:
    if source.strip() != lt.source:
        raise UserFacingError(
            f"Log table '{lt.name}' already exists for {lt.source}. Re-running setup only corrects field roles; "
            "pick another name for a different source."
        )
    header = fmt.how_measured("catalog update only; no data was read")
    if not roles:
        return header + f"\nLog table '{lt.name}' is already set up; nothing changed. Pass roles={{...}} to correct field roles."
    cols = dict(relation_columns(ctx.db, lt.relation, lt.source))
    wanted = validate_roles(roles, cols)
    changed = [r for r, v in wanted.items() if getattr(lt.roles, r) != v]
    if not changed:
        return header + f"\nLog table '{lt.name}': field roles already as requested; nothing changed."
    new_roles = _merge(lt.roles, wanted)
    ctx.store.update_roles(lt.name, new_roles)
    return "\n".join(
        [header, f"Log table '{lt.name}': updated field roles: {', '.join(changed)}. Nothing else changed.", "field roles now:"]
        + role_lines(new_roles, "  ")
    )


def setup_log_table(
    ctx: AppContext,
    name: str,
    source: str,
    roles: dict[str, Any] | None = None,
    line_format: str | None = None,
    timezone: str = "UTC",
    build_filter_index: bool = False,
    build_search_index: bool = False,
) -> str:
    try:
        validate_name(name)
    except ValueError as exc:
        raise UserFacingError(str(exc)) from None
    existing = _existing(ctx, name)
    if existing is not None:
        return _rerun(ctx, existing, source, roles)
    get_zone(timezone)
    rs = _structured(source, ctx, None)
    info = sniff(ctx.db, rs, source)
    proposed, _ = propose_roles(info.columns, sample_values(info))
    final = proposed
    if roles:
        wanted = validate_roles(roles, dict(info.columns))
        final = _merge(proposed, wanted)
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
        timezone=timezone,
        created_at=now,
        roles_updated_at=now,
    )
    try:
        ctx.store.create_log_table(lt)
    except BaseException:
        if rs.kind != "table":
            ctx.db.write(f"DROP VIEW IF EXISTS {relation}")
        raise
    lines = [
        fmt.how_measured("catalog entry created; only the source's metadata and 5 sample entries were read"),
        f"Set up log table '{name}': {_where_read(rs)}."
        + (f" View {relation} reads the source directly." if rs.kind != "table" else ""),
        f"rows: {lt.row_count:,}" if lt.row_count is not None else "rows: not counted",
        "field roles:",
        *role_lines(final, "  "),
        "The template catalog starts empty.",
    ]
    if build_filter_index or build_search_index:
        lines.append("Indexes can't be built yet, so none was built. No index is ever built unless you ask for it.")
    else:
        lines.append("No index was built.")
    return "\n".join(lines)


def _create_relation(ctx: AppContext, name: str, info: SourceInfo) -> str:
    if info.resolved.kind == "table":
        return info.from_sql
    relation = f"extractor.lt_{name}"
    ctx.db.write(f"CREATE OR REPLACE VIEW {relation} AS SELECT * FROM {info.from_sql}")
    return relation


def _row_count(ctx: AppContext, info: SourceInfo, relation: str) -> int | None:
    if info.row_count is not None:
        return int(info.row_count)
    return int(ctx.db.read(f"SELECT count(*) FROM {relation}").scalar())
