"""survey: the cheap first look at a log table's message templates."""

from datetime import UTC, datetime
from typing import Any

from serenedb_extractor import format as fmt
from serenedb_extractor.catalog.models import CandidateTemplate, LogTable, Template, UpsertResult
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
        f"SELECT {mask_sql('msg')} AS m, svc, comp, count(*) AS c, any_value(msg) AS example, min(ts) AS first_ts, max(ts) AS last_ts "
        "FROM (SELECT * FROM (" + inner + ") USING SAMPLE reservoir(%(sample_rows)s ROWS) REPEATABLE (%(sample_seed)s)) "
        "GROUP BY 1, 2, 3"
    )
    rows = ctx.db.read(sql, {**params, "sample_rows": int(sample_size), "sample_seed": SAMPLE_SEED}).dicts()
    by_mask: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_mask.setdefault(row["m"], []).append(row)
    groups: list[MaskedGroup] = []
    sampled = 0
    for masked, items in by_mask.items():
        breakdown: Breakdown = {}
        for role, col in (("service", "svc"), ("component", "comp")):
            if getattr(lt.roles, role) is None:
                continue
            counts = breakdown.setdefault(role, {})
            for r in items:
                label = NONE_LABEL if r[col] is None else str(r[col])
                counts[label] = counts.get(label, 0) + int(r["c"])
        total = sum(int(r["c"]) for r in items)
        sampled += total
        seen_first = [r["first_ts"] for r in items if r["first_ts"] is not None]
        seen_last = [r["last_ts"] for r in items if r["last_ts"] is not None]
        groups.append(
            MaskedGroup(
                masked=masked,
                count=total,
                example=max(items, key=lambda r: int(r["c"]))["example"],
                first_seen=min(seen_first, default=None),
                last_seen=max(seen_last, default=None),
                breakdown=breakdown,
            )
        )
    return groups, sampled


def _filters_text(f: Filters, excluded: list[str] | None = None) -> str | None:
    parts = []
    for key, wanted in f.items():
        if isinstance(wanted, list):
            parts.append(f"{key} in ({', '.join(repr(w) for w in wanted)})")
        else:
            parts.append(f"{key}={wanted!r}")
    if excluded:
        parts.append(f"excluding templates {', '.join(excluded)}")
    return ", ".join(parts) or None


def _share(part: int, whole: int, exact: bool = False) -> str:
    pct = 100 * part / whole if whole else 0.0
    mark = "" if exact else "≈"
    return f"{mark}<1%" if 0 < pct < 1 else f"{mark}{pct:.0f}%"


def _breakdown_line(role: str, counts: dict[str, int], hits: int, exact: bool) -> str | None:
    if not counts:
        return None
    top = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:TOP_BREAKDOWN]
    label = {"service": "services", "component": "components"}[role]
    return f"    {label}: " + ", ".join(f"{name} {_share(n, hits, exact)}" for name, n in top)


def _measure(count: int, sampled: int, population: int) -> fmt.Measured:
    """Every matching entry was read -> exact; otherwise scaled from the sample."""
    if sampled >= population:
        return fmt.Measured(float(count), True, sampled, count)
    return fmt.estimate(count, sampled, population)


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


CONFIRMED_COST_NOTE = "The cost confirmation isn't available yet — it was ignored; this survey ran as usual."


def resolve_exclusions(ctx: AppContext, log_table: str, exclude: list[str] | None) -> tuple[list[Template], list[str]]:
    """The live templates to hide (an unknown ID raises) and one note per ID that was merged away."""
    live: dict[str, Template] = {}
    notes: list[str] = []
    for given in exclude or []:
        resolved = ctx.store.resolve(log_table, given)
        live.setdefault(resolved.template.template_id, resolved.template)
        if resolved.redirected_from:
            notes.append(f"{resolved.redirected_from} was merged into {resolved.template.template_id}; excluded that one.")
    return list(live.values()), notes


def _merge_notes(result: UpsertResult) -> list[str]:
    notes = []
    for t, status in result.items:
        if status == "generalized":
            gone = result.absorbed_into(t.template_id)
            tail = f"; {', '.join(gone)} {'was' if len(gone) == 1 else 'were'} merged into it" if gone else ""
            notes.append(f"{t.template_id} was generalized to \"{t.template}\" (same ID){tail}.")
    return notes


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
    # `confirmed_cost` (#12) is not acted on yet; the output says so.
    lt = ctx.store.get_log_table(log_table)
    tr: TimeRange = parse_time_range(start, end, timezone)
    f = Filters.from_dict(filters)
    hidden, exclusion_notes = resolve_exclusions(ctx, lt.name, exclude)
    hidden_ids = [t.template_id for t in hidden]
    cap = ctx.settings.limit_cap
    n_target = fmt.clamp_limit(sample_size, ctx.settings.sample_size, ctx.settings.sample_size * cap)
    shown_limit = fmt.clamp_limit(limit, DEFAULT_LIMIT, DEFAULT_LIMIT * cap)
    with readable(f"the source of log table '{lt.name}'"):
        cols = known_columns(ctx.db, lt)
        where, params = build_where(lt, tr, f, cols)
        for i, t in enumerate(hidden):  # inside the filter subquery, so sampling sees only what is left
            where += f" AND NOT regexp_full_match(coalesce(({role_sql(lt, 'message')})::varchar, ''), %(x_{i})s)"
            params[f"x_{i}"] = t.regex
        population = int(ctx.db.read(f"SELECT count(*) FROM {lt.relation} WHERE {where}", params).scalar())
        groups, sampled = _sample_groups(ctx, lt, where, params, n_target) if population else ([], 0)
        if sampled == 0:
            lines = diagnose_empty(ctx.db, lt, tr, f, cols) or [
                "No entries are left after excluding those templates." if hidden else "No entries matched."
            ]
            head = fmt.how_measured(
                "exact count of the entries that match", tr.describe() if tr.bounded else None, _filters_text(f, hidden_ids), tz=timezone
            )
            return head + "\n" + "\n".join([*exclusion_notes, *([CONFIRMED_COST_NOTE] if confirmed_cost else []), *lines])
    merged = merge_groups(groups)
    exact = sampled >= population
    measures = {m.template: _measure(m.count, sampled, population) for m in merged}
    candidates = [_candidate(m, measures[m.template]) for m in merged]
    result = ctx.store.upsert_survey_templates(lt.name, candidates, datetime.now(UTC))
    saved: dict[str, tuple[Template, str]] = {t.template: (t, status) for t, status in result.items}

    if exact:
        kind = (
            f"survey, exact: every matching entry ({population:,}) was read, masked, grouped and merged into "
            "templates inside SereneDB; all counts and shares are exact"
        )
    else:
        kind = (
            f"survey: the matching entries were counted exactly ({population:,}), then a random sample of "
            f"{sampled:,} of them was masked, grouped and merged into templates inside SereneDB; "
            "counts per template are estimates scaled from the sample"
        )
    head = fmt.how_measured(
        kind,
        tr.describe() if tr.bounded else None,
        _filters_text(f, hidden_ids),
        "all matching entries read, no sampling" if exact else f"filtered first, then sampled ({sampled:,} entries, repeatable)",
        tz=timezone,
    )
    shown, note = fmt.cut(merged, shown_limit, "templates")
    covered = sum(m.count for m in shown)
    out = [
        head,
        *exclusion_notes,
        *([CONFIRMED_COST_NOTE] if confirmed_cost else []),
        *_merge_notes(result),
        f"Log table {lt.name}: {population:,} entries match; {len(merged)} templates found in the sample.",
        f"These {len(shown)} cover {100 * covered / sampled:.0f}% of the sample.",
    ]
    if note:
        out.append(note)
    for m in shown:
        template, status = saved[m.template]
        measured = measures[m.template]
        flag = {"new": "  NEW", "generalized": "  GENERALIZED"}.get(status, "")
        out.append("")
        out.append(f"{template.template_id}  {m.template}{flag}")
        out.append(f"    {fmt.render(measured)}, {_share(m.count, sampled, exact)} of matching entries")
        for role in ("service", "component"):
            line = _breakdown_line(role, m.breakdown.get(role, {}), m.count, exact)
            if line:
                out.append(line)
        out.append(f"    example: {fmt.shorten(m.example)}")
    return "\n".join(out)
