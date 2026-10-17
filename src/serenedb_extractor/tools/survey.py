"""survey: the cheap first look at a log table's message templates."""

from datetime import UTC, datetime
from typing import Any

from serenedb_extractor import format as fmt
from serenedb_extractor.catalog.models import CandidateTemplate, LogTable, Template
from serenedb_extractor.context import AppContext
from serenedb_extractor.query.filters import Filters, TimeRange, build_where, diagnose_empty, parse_time_range, role_sql
from serenedb_extractor.templating.drain import Breakdown, MaskedGroup, MergedTemplate, merge_groups
from serenedb_extractor.templating.masking import mask_sql
from serenedb_extractor.templating.regex import compile_template
from serenedb_extractor.tools.describe import known_columns
from serenedb_extractor.setup.sniff import readable

DEFAULT_LIMIT = 30
SAMPLE_SEED = 3  # fixed so that repeating a survey over unchanged data samples the same entries
TOP_BREAKDOWN = 3
NONE_LABEL = "(none)"


def _optional(lt: LogTable, role: str) -> str:
    return role_sql(lt, role) if getattr(lt.roles, role) is not None else "NULL"


def _sample_groups(
    ctx: AppContext, lt: LogTable, where: str, params: dict[str, Any], sample_size: int
) -> tuple[list[MaskedGroup], int]:
    """Filter first, then sample the filtered rows, then mask and group in SereneDB (spike section 8)."""
    inner = (
        f"SELECT coalesce(({role_sql(lt, 'message')})::varchar, '') AS msg, ({_optional(lt, 'service')})::varchar AS svc, "
        f"({_optional(lt, 'component')})::varchar AS comp, {_optional(lt, 'timestamp')} AS ts "
        f"FROM {lt.relation} WHERE {where}"
    )
    sql = (
        f"SELECT {mask_sql('msg')} AS m, svc, comp, count(*) AS c, any_value(msg) AS example, min(ts), max(ts) "
        f"FROM (SELECT * FROM ({inner}) USING SAMPLE reservoir({int(sample_size)} ROWS) REPEATABLE ({SAMPLE_SEED})) "
        "GROUP BY 1, 2, 3"
    )
    rows = ctx.db.read(sql, params).rows
    by_mask: dict[str, list[tuple[Any, ...]]] = {}
    for row in rows:
        by_mask.setdefault(row[0], []).append(row)
    groups: list[MaskedGroup] = []
    sampled = 0
    for masked, items in by_mask.items():
        breakdown: Breakdown = {}
        for role, idx in (("service", 1), ("component", 2)):
            if getattr(lt.roles, role) is None:
                continue
            counts = breakdown.setdefault(role, {})
            for r in items:
                label = NONE_LABEL if r[idx] is None else str(r[idx])
                counts[label] = counts.get(label, 0) + int(r[3])
        total = sum(int(r[3]) for r in items)
        sampled += total
        seen_first = [r[5] for r in items if r[5] is not None]
        seen_last = [r[6] for r in items if r[6] is not None]
        groups.append(
            MaskedGroup(
                masked=masked,
                count=total,
                example=max(items, key=lambda r: int(r[3]))[4],
                first_seen=min(seen_first, default=None),
                last_seen=max(seen_last, default=None),
                breakdown=breakdown,
            )
        )
    return groups, sampled


def _filters_text(f: Filters) -> str | None:
    parts = []
    for key, wanted in f.items():
        if isinstance(wanted, list):
            parts.append(f"{key} in ({', '.join(repr(w) for w in wanted)})")
        else:
            parts.append(f"{key}={wanted!r}")
    return ", ".join(parts) or None


def _share(part: int, whole: int) -> str:
    pct = 100 * part / whole if whole else 0.0
    return "≈<1%" if 0 < pct < 1 else f"≈{pct:.0f}%"


def _breakdown_line(role: str, counts: dict[str, int], hits: int) -> str | None:
    if not counts:
        return None
    top = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:TOP_BREAKDOWN]
    label = {"service": "services", "component": "components"}[role]
    return f"    {label}: " + ", ".join(f"{name} {_share(n, hits)}" for name, n in top)


def _candidate(m: MergedTemplate, measured: fmt.Measured) -> CandidateTemplate:
    compiled = compile_template(m.template)
    return CandidateTemplate(
        template=m.template,
        regex=compiled.regex,
        params=list(compiled.params),
        example=m.example,
        first_seen=m.first_seen,
        last_seen=m.last_seen,
        estimate=round(measured.value),
    )


def survey(
    ctx: AppContext,
    log_table: str,
    start: str | None = None,
    end: str | None = None,
    filters: dict[str, Any] | None = None,
    exclude: list[str] | None = None,
    sample_size: int | None = None,
    limit: int | None = None,
    timezone: str = "UTC",
    confirmed_cost: str | None = None,
) -> str:
    # `exclude` (#11) and `confirmed_cost` (#12) are part of the signature but not acted on yet.
    lt = ctx.store.get_log_table(log_table)
    tr: TimeRange = parse_time_range(start, end, timezone)
    f = Filters.from_dict(filters)
    cap = ctx.settings.limit_cap
    n_target = fmt.clamp_limit(sample_size, ctx.settings.sample_size, ctx.settings.sample_size * cap)
    shown_limit = fmt.clamp_limit(limit, DEFAULT_LIMIT, DEFAULT_LIMIT * cap)
    with readable(f"the source of log table '{lt.name}'"):
        cols = known_columns(ctx.db, lt)
        where, params = build_where(lt, tr, f, cols)
        population = int(ctx.db.read(f"SELECT count(*) FROM {lt.relation} WHERE {where}", params).scalar())
        groups, sampled = _sample_groups(ctx, lt, where, params, n_target) if population else ([], 0)
        if sampled == 0:
            lines = diagnose_empty(ctx.db, lt, tr, f, cols) or ["No entries matched."]
            head = fmt.how_measured(
                "exact count of the entries that match", tr.describe() if tr.bounded else None, _filters_text(f), tz=timezone
            )
            return head + "\n" + "\n".join(lines)
    merged = merge_groups(groups)
    candidates = [_candidate(m, fmt.estimate(m.count, sampled, population)) for m in merged]
    result = ctx.store.upsert_survey_templates(lt.name, candidates, datetime.now(UTC))
    saved: dict[str, tuple[Template, str]] = {t.template: (t, status) for t, status in result.items}

    whole = "every matching entry" if sampled >= population else f"a random sample of {sampled:,} of them"
    head = fmt.how_measured(
        f"survey: the matching entries were counted exactly ({population:,}), then {whole} was masked, grouped and "
        "merged into templates inside SereneDB; counts per template are estimates scaled from the sample",
        tr.describe() if tr.bounded else None,
        _filters_text(f),
        f"filtered first, then sampled ({sampled:,} entries, repeatable)",
        tz=timezone,
    )
    shown, note = fmt.cut(merged, shown_limit, "templates")
    covered = sum(m.count for m in shown)
    out = [
        head,
        f"Log table {lt.name}: {population:,} entries match; {len(merged)} templates found in the sample.",
        f"These {len(shown)} cover {100 * covered / sampled:.0f}% of the sample.",
    ]
    if note:
        out.append(note)
    for m in shown:
        template, status = saved[m.template]
        measured = fmt.estimate(m.count, sampled, population)
        flag = "  NEW" if status == "new" else ""
        out.append("")
        out.append(f"{template.template_id}  {m.template}{flag}")
        out.append(f"    {fmt.render(measured)}, {_share(m.count, sampled)} of matching entries")
        for role in ("service", "component"):
            line = _breakdown_line(role, m.breakdown.get(role, {}), m.count)
            if line:
                out.append(line)
        out.append(f"    example: {fmt.shorten(m.example)}")
    return "\n".join(out)
