"""Turning a plan's block sample into SQL, and estimating from it.

A block sample is a set of whole Parquet row groups that overlap the time range, written as
`file_row_number BETWEEN a AND b OR ...` so SereneDB skips the other row groups (measured in #10:
5 of 20 row groups read, a quarter of the bytes). It needs a row-position column that the scan
prunes on, so only a single in-place Parquet file is ever block-sampled (`ScopeStats.can_sample`).
`USING SAMPLE ... (system)`, `bernoulli` and `reservoir` read every row group, so they save no bytes.

Entries within a row group are not independent (a row group is a slice of time), so the margin
comes from the variation between the sampled blocks, never from a binomial formula.
"""

import math

from rcagent.format import MIN_HITS, Measured
from rcagent.query.cost import Plan

POSITION = "file_row_number"
MIN_BLOCKS_FOR_MARGIN = 5


def _ranges(plan: Plan) -> list[tuple[int, int]]:
    return [(g.first_row, g.first_row + g.rows - 1) for g in plan.groups]


def clause(plan: Plan, position: str = POSITION) -> str:
    """A WHERE predicate selecting the plan's sample ("TRUE" when the plan reads everything)."""
    if plan.sampling is None or not plan.groups:
        return "TRUE"
    if position != POSITION:
        raise ValueError("block samples are defined on Parquet file_row_number only")
    return "(" + " OR ".join(f"{position} BETWEEN {a} AND {b}" for a, b in _ranges(plan)) + ")"


def block_id_sql(plan: Plan, position: str = POSITION) -> str:
    """Which chosen block (0, 1, ...) a row is in, for per-block counts."""
    whens = " ".join(f"WHEN {position} BETWEEN {a} AND {b} THEN {i}" for i, (a, b) in enumerate(_ranges(plan)))
    return f"CASE {whens} END"


def block_estimate(blocks: list[tuple[int, int]], fraction: float) -> Measured:
    """Scale hits from a block sample: `blocks` = (entries in scope, hits) per sampled block;
    `fraction` = the sampled blocks' share of the in-range rows.

    Ratio estimator R = sum(hits) / sum(entries); value = sum(hits) / fraction. Its 95% margin uses
    the between-block variance, var(R) = (1 - f) * s^2 / (m * mean_n^2), s^2 = sum((y - R n)^2) / (m - 1).
    With fewer than 5 blocks no margin can be estimated, and it says so. The margin is floored at the
    binomial margin of the sampled entries, with the same finite-population correction (zero
    between-block variation is not certainty)."""
    m = len(blocks)
    n = sum(b[0] for b in blocks)
    hits = sum(b[1] for b in blocks)
    value = hits / fraction if fraction > 0 else 0.0
    if hits <= 0 or n <= 0:
        return Measured(0.0, False, n, hits, None)
    if m < MIN_BLOCKS_FOR_MARGIN:
        return Measured(value, False, n, hits, None, rough=f"margin not estimable from {m} block{'' if m == 1 else 's'}")
    r = hits / n
    s2 = sum((y - r * k) ** 2 for k, y in blocks) / (m - 1)
    var = (1 - min(fraction, 1.0)) * s2 / (m * (n / m) ** 2)
    margin = 1.96 * math.sqrt(var) / r
    # Blocks that happen to agree exactly give zero between-block variance; the margin is never below
    # the binomial margin of the sampled entries, so an estimate never claims more precision than that.
    binomial = 1.96 * math.sqrt((1 - min(fraction, 1.0)) * (1 - r) / (n * r))  # same finite-population correction
    margin = max(margin, binomial)
    return Measured(value, False, n, hits, margin if hits >= MIN_HITS else None)
