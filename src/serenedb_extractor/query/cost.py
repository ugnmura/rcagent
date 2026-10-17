"""The cost check: predict a query's bytes and seconds before it runs, walk the cheaper ladder
(spec section 8), and ask when nothing fits. `decide` is pure: metadata in, decision out.

Ladder: (1) columns served by an index cost nothing; (2) callers pass only the columns the query
reads (fixed-word prefilters are the caller's job: they shrink what the regex sees, not the bytes);
(3) exact over budget -> an estimate from a block sample sized to `sample_target`; (4) that sample
halved down to 1/8 of its size, margin wider and said so. The first rung that fits runs; if none
does, the answer is an ask with the predicted cost and a confirmation token. The scope (period,
filters) is never narrowed here: that would change the question.
"""

import math
import re
from collections.abc import Collection
from dataclasses import dataclass, field, replace
from typing import Literal

from serenedb_extractor import format as fmt
from serenedb_extractor.query.stats import ScopeStats
from serenedb_extractor.setup.sniff import human_bytes

# Claude's call; the benchmark (spec section 14, layer D) tunes these. Remote reads vary a lot
# between cold and warm runs (spike section 8), so the remote figure is deliberately low.
THROUGHPUT_BYTES_PER_S = {"remote": 100e6, "local": 500e6}
BUDGET_SECONDS = 30.0
CONFIRM_TOLERANCE = 2.0  # a confirmation still holds while the fresh plan is within 2x of it
TIMEOUT_MARGIN = 2.0  # a confirmed run may take twice its prediction before it is cancelled
HALVINGS = (1, 2, 4, 8)

_UNITS = {"B": 1.0, "KB": 1e3, "MB": 1e6, "GB": 1e9, "TB": 1e12, "PB": 1e15}
_TOKEN = re.compile(r"^~?\s*([0-9]+(?:\.[0-9]+)?)\s*(B|KB|MB|GB|TB|PB)$", re.IGNORECASE)


@dataclass(frozen=True)
class Plan:
    exact: bool
    sampling: str | None  # None: every entry in scope is read; "blocks": a block sample of row numbers
    sample_rows: int | None  # expected entries in the sample
    bytes: float
    seconds: float
    notes: tuple[str, ...] = ()
    confirmed: bool = False  # running because the user approved its cost
    fraction: float = 1.0  # share of the scope's entries the sample holds
    block_rows: int = 0
    blocks: tuple[int, ...] = field(default_factory=tuple)

    def cost_token(self) -> str:
        """What the user approves: the predicted bytes, short and readable (e.g. 2.1TB)."""
        return human_bytes(self.bytes).replace(" ", "")


@dataclass(frozen=True)
class Decision:
    status: Literal["run", "ask"]
    plan: Plan
    message: str = ""


def parse_token(token: str) -> float | None:
    m = _TOKEN.match(token.strip())
    if not m:
        return None
    return float(m.group(1)) * _UNITS[m.group(2).upper()]


def _within(approved: float, fresh: float) -> bool:
    a, f = max(approved, 1.0), max(fresh, 1.0)
    return max(a / f, f / a) <= CONFIRM_TOLERANCE


def cost_text(plan: Plan) -> str:
    return f"~{human_bytes(plan.bytes)} read, {fmt.duration(plan.seconds)}"


def run_timeout(plan: Plan, default_s: float, max_s: float) -> float:
    """A confirmed run gets a timeout covering its estimate (with margin), clamped to the maximum."""
    if plan.confirmed:
        return min(max_s, max(default_s, TIMEOUT_MARGIN * plan.seconds))
    return min(default_s, max_s)


def decide(
    stats: ScopeStats,
    columns: list[str],
    want_exact: bool,
    sample_target: int,
    confirmed_cost: str | None,
    budget_s: float | None = None,
    indexed: Collection[str] = (),
) -> Decision:
    budget = BUDGET_SECONDS if budget_s is None else budget_s  # read now, so it can be tuned/patched
    speed = THROUGHPUT_BYTES_PER_S["remote" if stats.remote else "local"]
    read = [c for c in columns if c not in indexed]
    exact_bytes = float(stats.bytes_for(read))
    exact = Plan(True, None, None, exact_bytes, exact_bytes / speed)
    stale = ""
    if confirmed_cost:
        approved = parse_token(confirmed_cost)
        if approved is not None and _within(approved, exact.bytes):
            note = f"running as confirmed: {cost_text(exact)}."
            return Decision("run", replace(exact, confirmed=True, notes=(note,)))
        stale = (
            f"The confirmed cost ({confirmed_cost}) does not match this query any more "
            f"(it now needs {cost_text(exact)}), so it was not run."
        )
    small = stats.rows_in_range <= sample_target
    if exact.seconds <= budget and (want_exact or small):
        return Decision("run", exact)
    tried: list[Plan] = []
    if stats.can_sample and stats.rows_in_range > 0:
        base = max(2, math.ceil(stats.rows_in_range / max(sample_target, 1)))
        for div in HALVINGS:
            block, chosen, fraction = stats.blocks(base * div)
            if fraction >= 1.0:
                continue
            b = exact_bytes * fraction
            plan = Plan(False, "blocks", round(stats.rows_in_range * fraction), b, b / speed, (), False, fraction, block, chosen)
            tried.append(plan)
            if plan.seconds <= budget:
                notes = [
                    f"an exact count would read ~{human_bytes(exact.bytes)} ({fmt.duration(exact.seconds)}), "
                    "so this is estimated from a sample"
                    if want_exact
                    else "estimated from a sample"
                ]
                if div > 1:
                    notes.append(f"the sample is 1/{div} of the usual size to stay within the time budget, so the margin is wider")
                return Decision("run", replace(plan, notes=tuple(notes)))
    if exact.seconds <= budget:  # an estimate was wanted but no sample is cheaper: the exact answer fits
        return Decision("run", exact)
    return Decision("ask", exact, _ask(stats, exact, tried, budget, read, stale))


def _ask(stats: ScopeStats, exact: Plan, tried: list[Plan], budget: float, read: list[str], stale: str) -> str:
    reason = f"needs {cost_text(exact)} (the budget for one query is {fmt.duration(budget)})"
    if tried:
        cheapest = min(tried, key=lambda p: p.bytes)
        reason += f"; even an estimate from a sample would need {cost_text(cheapest)}"
    index = (
        "build a search index (create_index with dry_run shows its size and build time); text searches then read it instead of every message"
        if not stats.has_search_index
        else "build a filter index (create_index with dry_run shows its size); filters on level, service and time then read it"
    )
    options = [
        f"run it anyway: repeat the same call with confirmed_cost={exact.cost_token()}",
        "narrow it: a shorter period (start/end) or filters such as level or service",
        index,
    ]
    out = fmt.refusal(reason, options)
    return (stale + "\n" + out) if stale else out
