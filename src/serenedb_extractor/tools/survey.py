"""survey: the cheap first look at a log table's message templates, cost-checked before it runs.

The cost check (query/cost.py) picks how the entries are read (R36):
- a block sample of whole row groups, when the source can skip the others (a single in-place
  Parquet file) and reading everything is over budget or more than the sample needs; at least
  five blocks whenever that fits (R46), so margins can be estimated from between-block variation;
- otherwise every entry in scope is read, priced as such: every matching entry is masked, or,
  when there are more than `sample_size`, a filter-first reservoir of them (#10 measured that the
  reservoir reads the whole message column anyway, so it saves work, not bytes).
When every matching entry was read, counts are exact (R26). Nothing fits -> the ask, with a token.
"""

import math
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

from serenedb_extractor import format as fmt
from serenedb_extractor.catalog.models import CandidateTemplate, LogTable, Template, UpsertResult
from serenedb_extractor.context import AppContext
from serenedb_extractor.db import Rows
from serenedb_extractor.query import cost, sampling
from serenedb_extractor.query.filters import (
    FILTER_ROLES,
    Filters,
    TimeRange,
    build_where,
    diagnose_empty,
    parse_time_range,
    role_sql,
    time_clause,
)
from serenedb_extractor.query.stats import ScopeStats, collect, role_columns
from serenedb_extractor.setup.paths import pct
from serenedb_extractor.setup.roles import resolve_column
from serenedb_extractor.setup.sniff import human_bytes, readable
from serenedb_extractor.templating.drain import Breakdown, MaskedGroup, MergedTemplate, merge_groups
from serenedb_extractor.templating.masking import mask_sql
from serenedb_extractor.templating.regex import compile_template
from serenedb_extractor.query.coverage import untimestamped_note
from serenedb_extractor.tools.describe import known_columns

DEFAULT_LIMIT = 30
SAMPLE_SEED = 3  # fixed so that repeating a survey over unchanged data samples the same entries
TOP_BREAKDOWN = 3
NONE_LABEL = "(none)"
MIN_BLOCKS = sampling.MIN_BLOCKS_FOR_MARGIN  # R46

Method = Literal["every", "reservoir", "blocks"]
BlockCounts = dict[str, dict[int, int]]  # masked string -> sampled block -> masked matching entries in it
NARROW = (
    "narrow it: a shorter period (start/end) or filters such as level or service, "
    "or a smaller sample_size; then survey again."
)

# TEST-ONLY HOOK: SQL appended to the survey's filter (it must start with " AND "). Tests set it to
# force a slow query and check that the timeout cancels it; it is always "" in normal use.
SURVEY_SQL_SUFFIX = ""
SAMPLED_NOTE = "estimated from a sample"  # cost.decide's note for a sample that was wanted anyway


def _optional(lt: LogTable, role: str) -> str:
    return role_sql(lt, role) if getattr(lt.roles, role) is not None else "NULL"


def _read(ctx: AppContext, lt: LogTable, sql: str, params: dict[str, Any], timeout: float) -> Rows:
    """Every survey query: the run's timeout, and a survey-specific way to narrow on a timeout."""
    return ctx.db.read(sql, params, timeout_s=timeout, what=f"surveying log table {lt.name}", how_to_narrow=NARROW)


def _scan_groups(
    ctx: AppContext,
    lt: LogTable,
    where: str,
    params: dict[str, Any],
    reservoir: int | None,
    block_sql: str | None,
    timeout: float,
) -> tuple[list[MaskedGroup], int, BlockCounts]:
    """Mask and group the entries in `where` inside SereneDB: all of them, a filter-first reservoir
    of `reservoir` entries, or (with `block_sql`) the entries of the sampled blocks, also counted
    per block for each masked string."""
    blk = f", ({block_sql}) AS blk" if block_sql else ""
    inner = (
        f"SELECT coalesce(({role_sql(lt, 'message')})::varchar, '') AS msg, ({_optional(lt, 'service')})::varchar AS svc, "
        f"({_optional(lt, 'component')})::varchar AS comp, {_optional(lt, 'timestamp')} AS ts{blk} "
        f"FROM {lt.relation} WHERE {where}"
    )
    sample = " USING SAMPLE reservoir(%(sample_rows)s ROWS) REPEATABLE (%(sample_seed)s)" if reservoir else ""
    sql = (
        f"SELECT {mask_sql('msg')} AS m, svc, comp{', blk' if block_sql else ''}, count(*) AS c, any_value(msg) AS example, "
        "min(ts) AS first_ts, max(ts) AS last_ts "
        f"FROM (SELECT * FROM ({inner}){sample}) GROUP BY {'1, 2, 3, 4' if block_sql else '1, 2, 3'}"
    )
    run_params = {**params, "sample_rows": int(reservoir or 0), "sample_seed": SAMPLE_SEED}
    rows = _read(ctx, lt, sql, run_params, timeout).dicts()
    by_mask: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_mask.setdefault(row["m"], []).append(row)
    groups: list[MaskedGroup] = []
    per_block: BlockCounts = {}
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
        if block_sql:
            mine = per_block.setdefault(masked, {})
            for r in items:
                mine[int(r["blk"])] = mine.get(int(r["blk"]), 0) + int(r["c"])
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
    return groups, sampled, per_block


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


def _columns(lt: LogTable, tr: TimeRange, f: Filters, cols: dict[str, str], excluding: bool) -> tuple[list[str], list[str]]:
    """(scan, count): the columns the template scan reads and those the population count reads."""

    def of(*roles: str) -> list[str]:
        out: list[str] = []
        for r in roles:
            out += role_columns(getattr(lt.roles, r))
        return out

    filter_cols = of(*[k for k, _ in f.items() if k in FILTER_ROLES])
    filter_cols += [c for k, _ in f.items() if k not in FILTER_ROLES and (c := resolve_column(k, cols))]
    scan = list(dict.fromkeys(of("message", "service", "component", "timestamp") + filter_cols))
    count = (of("timestamp") if tr.bounded else []) + filter_cols + (of("message") if excluding else [])
    return scan, count


def _decide(stats: ScopeStats, columns: list[str], n_target: int, confirmed_cost: str | None, max_s: float) -> cost.Decision:
    """The cost check for the survey scan. R46: a block sample takes at least MIN_BLOCKS row groups
    whenever that still fits, so its margins can be estimated; otherwise the usual ladder."""
    usual = cost.decide(stats, columns, False, n_target, confirmed_cost, max_s=max_s)
    g = len(stats.groups) if stats.can_sample else 0
    if g < 2 or usual.plan.confirmed:
        return usual
    wider = max(n_target, math.ceil(MIN_BLOCKS * stats.rows_in_range / g))
    if wider > n_target:
        d = cost.decide(stats, columns, False, wider, confirmed_cost, max_s=max_s)
        if d.status == "run" and (d.plan.exact or len(d.plan.groups) >= MIN_BLOCKS):
            return d
    return usual


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
    lt = ctx.store.get_log_table(log_table)
    tr: TimeRange = parse_time_range(start, end, timezone)
    f = Filters.from_dict(filters)
    hidden, exclusion_notes = resolve_exclusions(ctx, lt.name, exclude)
    hidden_ids = [t.template_id for t in hidden]
    s = ctx.settings
    n_target = fmt.clamp_limit(sample_size, s.sample_size, s.sample_size * s.limit_cap)
    shown_limit = fmt.clamp_limit(limit, DEFAULT_LIMIT, DEFAULT_LIMIT * s.limit_cap)
    period = tr.describe() if tr.bounded else None
    scope_text = _filters_text(f, hidden_ids)
    db = ctx.db
    with readable(f"the source of log table '{lt.name}'"):
        cols = known_columns(db, lt)
        time_sql, params = time_clause(lt, tr, cols)
        match_sql, match_params = build_where(lt, TimeRange(), f, cols)  # the filters alone
        params.update(match_params)
        for i, t in enumerate(hidden):  # part of the filter, so sampling sees only what is left
            match_sql += f" AND NOT regexp_full_match(coalesce(({role_sql(lt, 'message')})::varchar, ''), %(x_{i})s)"
            params[f"x_{i}"] = t.regex
        match_sql += pct(SURVEY_SQL_SUFFIX)
        scan_cols, count_cols = _columns(lt, tr, f, cols, bool(hidden))
        stats = collect(db, lt, tr)
        decision = _decide(stats, scan_cols + count_cols, n_target, confirmed_cost, s.max_timeout_s)
        if decision.status == "ask":
            head = fmt.how_measured(cost.ASKED_HOW, period, scope_text, tz=timezone)
            return "\n".join([head, *exclusion_notes, decision.message])
        plan = decision.plan
        timeout = cost.run_timeout(plan, s.default_timeout_s, s.max_timeout_s)
        # The How-measured line already says the survey is sampled; keep only notes that add to it.
        notes = [*exclusion_notes, *(fmt.sentence(n) for n in plan.notes if not plan.confirmed and n != SAMPLED_NOTE)]
        if (missing := untimestamped_note(db, lt, tr)) is not None:
            notes.append(missing)
        if confirmed_cost and not plan.confirmed:
            notes.append(f"confirmed_cost={confirmed_cost} was not needed: this survey fits the time budget, so it ran as usual.")
        if plan.sampling == "blocks":
            run = _blocks(ctx, lt, stats, plan, time_sql, match_sql, params, count_cols, n_target, timeout)
        else:
            run = _full(ctx, lt, time_sql + " AND " + match_sql, params, n_target, timeout)
        if run.sampled == 0:
            if plan.sampling == "blocks":
                lines = ["No matching entries in the sampled blocks; matching entries may still exist outside them."]
            else:
                lines = diagnose_empty(db, lt, tr, f, cols) or [
                    "No entries are left after excluding those templates." if hidden else "No entries matched."
                ]
            head = fmt.how_measured(_kind(run, plan), period, scope_text, _method(run, plan), tz=timezone)
            return "\n".join([head, *notes, *lines])
    return _render(ctx, lt, run, plan, period, scope_text, timezone, notes, shown_limit)


@dataclass
class _Run:
    """What the survey read: the masked groups, how many matching entries they hold, and the
    population of matching entries. Block runs also keep what each template's estimate needs."""

    groups: list[MaskedGroup]
    sampled: int
    population: fmt.Measured
    method: Method
    population_note: str | None = None
    stride: int = 1  # block runs: every stride-th entry of each block was masked (R57)
    looked_at: list[int] = field(default_factory=list)  # block runs: entries in scope looked at (every stride-th) per block
    looked_fraction: float = 1.0  # block runs: the looked-at entries' share of the in-range rows
    block_counts: BlockCounts = field(default_factory=dict)


def _full(ctx: AppContext, lt: LogTable, where: str, params: dict[str, Any], n_target: int, timeout: float) -> _Run:
    """Every entry in scope is read (the exact plan): an exact count, then every matching entry,
    or a filter-first reservoir of n_target of them (it reads the same bytes; R36)."""
    population = int(_read(ctx, lt, f"SELECT count(*) FROM {lt.relation} WHERE {where}", params, timeout).scalar() or 0)
    if not population:
        return _Run([], 0, fmt.Measured(0.0, True), "every")
    reservoir = n_target if population > n_target else None
    groups, sampled, _ = _scan_groups(ctx, lt, where, params, reservoir, None, timeout)
    method: Method = "every" if sampled >= population else "reservoir"
    return _Run(groups, sampled, fmt.Measured(float(population), True), method)


def _stride(plan: cost.Plan, n_target: int) -> int:
    """R57: mask at most ceil(n_target / blocks) entries per sampled block, spread evenly through it."""
    cap = max(1, math.ceil(n_target / max(1, len(plan.groups))))
    return max([1, *(math.ceil(g.rows / cap) for g in plan.groups)])


def _positions(first: int, rows: int, stride: int) -> int:
    """How many row positions in [first, first + rows) are multiples of `stride`."""
    return (first + rows - 1) // stride - (first - 1) // stride if rows else 0


def _blocks(
    ctx: AppContext,
    lt: LogTable,
    stats: ScopeStats,
    plan: cost.Plan,
    time_sql: str,
    match_sql: str,
    params: dict[str, Any],
    count_cols: list[str],
    n_target: int,
    timeout: float,
) -> _Run:
    """Whole row groups (the plan's block sample). Every entry in them is counted per block; every
    stride-th one (R57) is masked, so the work stays near the sample size. The population is an
    exact count when the cost check prices it within what is left of the budget, otherwise it is
    estimated from the blocks' counts."""
    stride = _stride(plan, n_target)
    spread = f"mod({sampling.POSITION}, {stride}) = 0" if stride > 1 else "TRUE"
    scope = f"{time_sql} AND {sampling.clause(plan)}"
    block_id = sampling.block_id_sql(plan)
    per_block = _read(
        ctx, lt,
        f"SELECT {block_id} AS b, count(*) AS n, count(*) FILTER (WHERE {match_sql}) AS y, "
        f"count(*) FILTER (WHERE {spread}) AS n_seen FROM {lt.relation} WHERE {scope} GROUP BY 1",
        params, timeout,
    ).rows
    found = {int(r[0]): (int(r[1]), int(r[2]), int(r[3])) for r in per_block if r[0] is not None}
    counted = [found.get(i, (0, 0, 0)) for i in range(len(plan.groups))]
    looked_fraction = (
        sum(_positions(g.first_row, g.rows, stride) for g in plan.groups) / plan.population_rows
        if plan.population_rows else 1.0
    )
    run = _Run(
        [], 0, fmt.Measured(0.0, False), "blocks", stride=stride, looked_at=[c[2] for c in counted],
        looked_fraction=looked_fraction,
    )
    if not sum(c[1] for c in counted):
        return run
    run.groups, run.sampled, run.block_counts = _scan_groups(
        ctx, lt, f"{scope} AND {spread} AND {match_sql}", params, None, block_id, timeout
    )
    left = max(0.0, cost.BUDGET_SECONDS - plan.seconds)
    count = cost.decide(stats, count_cols, True, n_target, None, budget_s=left, max_s=ctx.settings.max_timeout_s)
    if count.status == "run" and count.plan.exact:
        n = _read(ctx, lt, f"SELECT count(*) FROM {lt.relation} WHERE {time_sql} AND {match_sql}", params, timeout).scalar()
        run.population = fmt.Measured(float(n or 0), True)
        return run
    b = float(stats.bytes_for(count_cols))
    run.population_note = (
        f"an exact count of the matching entries would read a further ~{human_bytes(b)} "
        f"({fmt.duration(cost.seconds_for(stats, b))}), beyond the time budget, so it was not run"
    )
    run.population = sampling.block_estimate([(c[0], c[1]) for c in counted], plan.fraction)
    return run


def _kind(run: _Run, plan: cost.Plan) -> str:
    confirmed = " (run as you confirmed)" if plan.confirmed else ""
    if run.method == "every":
        n = f" ({round(run.population.value):,})" if run.sampled else ""
        return (
            f"survey, exact{confirmed}: every matching entry{n} was read, masked, grouped and merged into templates "
            "inside SereneDB; all counts and shares are exact"
        )
    if run.method == "reservoir":
        return (
            f"survey{confirmed}: the matching entries were counted exactly ({round(run.population.value):,}), then a "
            f"random sample of {run.sampled:,} of them was masked, grouped and merged into templates inside SereneDB; "
            "counts per template are estimates scaled from the sample"
        )
    return (
        "survey, estimated: matching entries in whole blocks of entries (row groups) were masked, grouped and "
        "merged into templates inside SereneDB; counts per template are estimates scaled up from the blocks"
    )


def _ordinal(n: int) -> str:
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _method(run: _Run, plan: cost.Plan) -> str:
    if run.method == "every":
        return "every matching entry read, no sampling"
    if run.method == "reservoir":
        return (
            f"reservoir sample of {run.sampled:,} of the {round(run.population.value):,} matching entries "
            "(filtered first; drawing it reads every entry in scope; repeatable)"
        )
    k = len(plan.groups)
    upto = "" if plan.rows_exact else "up to "
    spread = (
        f"; every {_ordinal(run.stride)} entry of each looked at: {sum(run.looked_at):,} entries" if run.stride > 1 else ""
    )
    return (
        f"block sample of {k} row group{'' if k == 1 else 's'} ({plan.sample_rows or 0:,} of {upto}"
        f"{plan.population_rows:,} entries in the period{spread}; entries in a row group are close together in time, "
        "so margins may understate the error; repeatable)"
    )


def _measure_template(m: MergedTemplate, run: _Run) -> fmt.Measured:
    if run.method == "every":
        return fmt.Measured(float(m.count), True, run.sampled, m.count)
    if run.method == "reservoir":
        return fmt.estimate(m.count, run.sampled, round(run.population.value))
    hits = [0] * len(run.looked_at)
    for masked in m.masks:
        for b, c in run.block_counts.get(masked, {}).items():
            hits[b] += c
    return sampling.block_estimate(list(zip(run.looked_at, hits, strict=True)), run.looked_fraction)


def _render(
    ctx: AppContext,
    lt: LogTable,
    run: _Run,
    plan: cost.Plan,
    period: str | None,
    scope_text: str | None,
    tz: str,
    notes: list[str],
    shown_limit: int,
) -> str:
    merged = merge_groups(run.groups)
    exact = run.method == "every"
    measures = {m.template: _measure_template(m, run) for m in merged}
    candidates = [_candidate(m, measures[m.template]) for m in merged]
    result = ctx.store.upsert_survey_templates(lt.name, candidates, datetime.now(UTC))
    saved: dict[str, tuple[Template, str]] = {t.template: (t, status) for t, status in result.items}
    head = fmt.how_measured(_kind(run, plan), period, scope_text, _method(run, plan), tz=tz)
    shown, note = fmt.cut(merged, shown_limit, "templates")
    covered = sum(m.count for m in shown)
    found = f"{len(merged)} templates found" + ("" if exact else " in the sample")
    if run.population.exact:
        population = f"Log table {lt.name}: {round(run.population.value):,} entries match; {found}."
    else:
        population = f"Log table {lt.name}: population estimated: {fmt.render(run.population)} matching entries; {found}."
    out = [
        head,
        *notes,
        *_merge_notes(result),
        population,
        *([fmt.sentence(run.population_note)] if run.population_note else []),
        f"These {len(shown)} cover {100 * covered / run.sampled:.0f}% of the {'matching entries' if exact else 'sample'}.",
    ]
    if note:
        out.append(note)
    for m in shown:
        template, status = saved[m.template]
        measured = measures[m.template]
        flag = {"new": "  NEW", "generalized": "  GENERALIZED"}.get(status, "")
        out.append("")
        out.append(f"{template.template_id}  {m.template}{flag}")
        out.append(f"    {fmt.render(measured)}, {_share(m.count, run.sampled, exact)} of matching entries")
        for role in ("service", "component"):
            line = _breakdown_line(role, m.breakdown.get(role, {}), m.count, exact)
            if line:
                out.append(line)
        out.append(f"    example: {fmt.shorten(m.example)}")
    return "\n".join(out)
