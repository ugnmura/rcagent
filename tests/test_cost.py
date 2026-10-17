"""The cost decision (a pure function), block-sample estimates, and the refusal/timeout wording."""

import math
from dataclasses import replace

from serenedb_extractor.format import Measured, refusal, render, timeout_message
from serenedb_extractor.query import cost
from serenedb_extractor.query.cost import decide
from serenedb_extractor.query.sampling import block_estimate, clause
from serenedb_extractor.query.stats import GroupStat, ScopeStats


def _groups(n: int, rows: int, per_col: dict[str, int], first: int = 0) -> tuple[GroupStat, ...]:
    return tuple(GroupStat(first_row=(first + i) * rows, rows=rows, bytes_by_column=dict(per_col)) for i in range(n))


def _stats(groups: tuple[GroupStat, ...], remote: bool = True, **over: object) -> ScopeStats:
    by_col: dict[str, int] = {}
    for g in groups:
        for c, b in g.bytes_by_column.items():
            by_col[c] = by_col.get(c, 0) + b
    rows = sum(g.rows for g in groups)
    base = ScopeStats(
        total_rows=rows,
        rows_in_range=rows,
        bytes_by_column=by_col,
        time_skippable=False,
        remote=remote,
        has_filter_index=False,
        has_search_index=False,
        can_sample=True,
        groups=groups,
    )
    return replace(base, **over)  # type: ignore[arg-type]


# A remote single-file Parquet scope: 1,000 row groups of 1e6 entries; message 2 GB per group (2 TB), level 1 MB.
BIG = _stats(_groups(1000, 1_000_000, {"message": 2_000_000_000, "level": 1_000_000, "ts": 2_000_000}))


def test_cheap_runs_exact():
    d = decide(BIG, ["level"], want_exact=True, sample_target=100_000, confirmed_cost=None, budget_s=30)
    assert d.status == "run" and d.plan.exact and d.plan.sampling is None
    assert d.plan.bytes == 1_000_000_000 and d.plan.seconds == 10.0


def test_only_the_columns_read_are_counted_and_a_column_read_twice_costs_twice():
    assert decide(BIG, ["level", "ts"], True, 100_000, None, budget_s=30).plan.bytes == 3_000_000_000
    assert decide(BIG, ["level", "level"], True, 100_000, None, budget_s=30).plan.bytes == 2_000_000_000


def test_indexed_columns_cost_nothing():
    d = decide(BIG, ["message", "level"], True, 100_000, None, budget_s=30, indexed=("message",))
    assert d.status == "run" and d.plan.exact and d.plan.bytes == 1_000_000_000


def test_too_expensive_exact_falls_back_to_a_sample_of_whole_row_groups():
    # exact: 2 TB at 100 MB/s = 20,000 s. A 100k target is below one group: stride 10,000 > 1,000 groups,
    # so the sample is one row group (at least one is always taken): 2 GB = 20 s.
    d = decide(BIG, ["message"], True, 100_000, None, budget_s=30)
    assert d.status == "run" and not d.plan.exact and d.plan.sampling == "blocks"
    assert d.plan.bytes == 2_000_000_000 and d.plan.sample_rows == 1_000_000
    assert len(d.plan.groups) == 1
    assert any("an exact count would read ~2.0 TB" in n and "estimated from a sample" in n for n in d.plan.notes)


def test_cheaper_sampling_widens_the_margin_and_says_so():
    s = _stats(_groups(10_000, 100_000, {"message": 200_000_000}))  # 1e9 entries, 2 TB
    # target 5e8 entries -> stride 2: 1 TB = 10,000 s; 4: 5,000 s; 8: 2,500 s; 16 (1/8 of it): 1,250 s.
    d = decide(s, ["message"], True, 500_000_000, None, budget_s=1300)
    assert d.status == "run" and not d.plan.exact and d.plan.seconds == 1250
    assert any("margin is wider" in n for n in d.plan.notes)


def test_sample_uses_only_groups_in_the_range():
    in_range = _groups(3, 1000, {"message": 1_000_000}, first=7)  # groups 7, 8, 9 of a longer file
    s = _stats(in_range, remote=False, rows_exact=False)
    d = decide(s, ["message"], True, 100, None, budget_s=0.005)  # exact 3 MB local = 6 ms
    assert d.status == "run" and d.plan.sampling == "blocks"
    assert all(g.first_row >= 7000 for g in d.plan.groups) and d.plan.sample_rows == 1000
    assert d.plan.population_rows == 3000


def test_single_row_group_is_a_full_read_not_a_sample():  # R39
    one = _stats(_groups(1, 5000, {"message": 50_000}), remote=False)
    d = decide(one, ["message"], True, 100_000, None, budget_s=0.0)
    assert d.status == "ask" and "estimated" not in d.message and "an estimate from a sample" not in d.message
    ok = decide(one, ["message"], True, 100_000, None, budget_s=30)
    assert ok.status == "run" and ok.plan.exact and not ok.plan.notes


def test_nothing_fits_asks_with_cost_and_token():
    d = decide(BIG, ["message"], True, 100_000, None, budget_s=0.0)
    assert d.status == "ask" and d.plan.exact
    assert d.message.startswith("TOO EXPENSIVE: needs ~2.0 TB read")
    assert f"confirmed_cost={d.plan.cost_token()}" in d.message
    assert "build a search index (create_index with dry_run shows its size)" in d.message and "narrow" in d.message


def test_beyond_the_server_maximum_never_offers_run_anyway():  # R40
    d = decide(BIG, ["message"], True, 100_000, None, budget_s=0.0, max_s=600)
    assert d.status == "ask" and "confirmed_cost=" not in d.message
    assert "server's maximum query time (600 s)" in d.message and "narrow" in d.message and "index" in d.message
    token = decide(BIG, ["message"], True, 100_000, None, budget_s=0.0).plan.cost_token()
    again = decide(BIG, ["message"], True, 100_000, token, budget_s=0.0, max_s=600)
    assert again.status == "ask" and "confirmed_cost=" not in again.message


def test_scope_is_never_narrowed():
    d = decide(BIG, ["message"], True, 100_000, None, budget_s=30)
    assert d.plan.population_rows == BIG.rows_in_range
    assert all("period" not in n for n in d.plan.notes)


def test_confirmation_within_twice_runs_exact_with_its_timeout():
    ask = decide(BIG, ["message"], True, 100_000, None, budget_s=0.0)
    token = ask.plan.cost_token()
    bigger = _stats(_groups(1000, 1_000_000, {"message": 3_000_000_000}))
    d = decide(bigger, ["message"], True, 100_000, token, budget_s=0.0)
    assert d.status == "run" and d.plan.exact and d.plan.confirmed
    assert cost.run_timeout(d.plan, default_s=60, max_s=600) == 600  # 30,000 s, clamped
    assert cost.run_timeout(replace(d.plan, seconds=100), default_s=60, max_s=600) == 200
    assert cost.run_timeout(replace(d.plan, confirmed=False, seconds=100), default_s=60, max_s=600) == 60


def test_confirmation_far_from_the_fresh_plan_asks_again():
    d = decide(BIG, ["message"], True, 100_000, "100GB", budget_s=0.0)
    assert d.status == "ask" and "does not match" in d.message


def test_malformed_confirmation_is_named_as_such():
    d = decide(BIG, ["message"], True, 100_000, "yes please", budget_s=0.0)
    assert d.status == "ask" and "isn't a cost confirmation from this tool" in d.message
    assert "does not match" not in d.message


def test_no_cheaper_sampling_when_a_sample_reads_the_same():
    s = replace(BIG, can_sample=False)
    assert decide(s, ["message"], True, 100_000, None, budget_s=30).status == "ask"


def test_budget_default_is_read_at_call_time(monkeypatch):
    monkeypatch.setattr(cost, "BUDGET_SECONDS", 0.0)
    assert decide(BIG, ["level"], True, 100_000, None).status == "ask"


def test_block_clause_lists_row_number_ranges_of_the_chosen_groups():
    in_range = _groups(4, 1000, {"message": 1_000_000}, first=2)
    d = decide(_stats(in_range, remote=False), ["message"], True, 2000, None, budget_s=0.006)
    assert d.plan.sampling == "blocks"
    assert clause(d.plan) == "(file_row_number BETWEEN 2000 AND 2999 OR file_row_number BETWEEN 4000 AND 4999)"
    assert clause(decide(BIG, ["level"], True, 100_000, None, budget_s=30).plan) == "TRUE"


def test_block_estimate_uses_between_block_variance():  # R38
    m = block_estimate([(100, 10), (100, 20), (100, 10), (100, 20), (100, 15)], fraction=0.5)
    assert m.value == 150 and not m.exact and m.sample_size == 500 and m.hits == 75
    # R = 0.15; s^2 = 0.01 / 4; var(R) = (1 - 0.5) * s^2 / 5; margin = 1.96 * sqrt(var) / R
    assert m.margin_rel is not None and math.isclose(m.margin_rel, 1.96 * math.sqrt(0.5 * 0.0025 / 5) / 0.15)
    assert render(m) == "≈150 (estimated from a 500 sample, ±21%)"


def test_block_estimate_from_few_blocks_is_rough():  # R38
    m = block_estimate([(1000, 30), (1000, 12)], fraction=0.25)
    assert m.margin_rel is None and m.rough == "margin not estimable from 2 blocks"
    assert render(m) == "≈168 (rough estimate from a 2k sample; margin not estimable from 2 blocks)"
    assert "too rare" in render(block_estimate([(1000, 3), (1000, 2)], fraction=0.25))


def test_rough_measure_renders_without_a_margin():
    assert "±" not in render(Measured(10, False, 100, 50, None, rough="margin not estimable from 1 block"))


def test_timeout_message_whole_seconds():
    assert timeout_message(60.0, "searching fx", "narrow it") == "TIMEOUT after 60s: searching fx — narrow it"
    assert timeout_message(1.5, "x", "y").startswith("TIMEOUT after 1.5s: x")


def test_refusal_wording():
    out = refusal("needs ~2.0 TB read, ~6 h", ["run it anyway: confirmed_cost=2.0TB", "narrow it"])
    assert out.startswith("TOO EXPENSIVE: needs ~2.0 TB read, ~6 h.")
    assert "- run it anyway: confirmed_cost=2.0TB" in out and "- narrow it" in out


def test_block_estimate_with_no_between_block_variation_keeps_the_binomial_margin():
    """Identical blocks give zero between-block variance; the margin is floored at the binomial
    margin of the sampled entries (with the same finite-population correction), never "±<0.1%"."""
    m = block_estimate([(1000, 100)] * 5, 0.5)
    binomial = 1.96 * ((1 - 0.5) * (1 - 0.1) / (5000 * 0.1)) ** 0.5
    assert m.margin_rel is not None and abs(m.margin_rel - binomial) < 1e-9
    assert "<0.1" not in render(m)


def test_an_upper_bound_ask_reads_as_one_plain_phrase():
    st = ScopeStats(10, 10, {"m": 10_000_000_000}, False, True, False, False)
    d = decide(st, ["m"], True, 1000, None, ask_options=[], upper_bound=True)
    assert d.status == "ask" and "reads up to ~10.0 GB, " in d.message and " read, " not in d.message, d.message
