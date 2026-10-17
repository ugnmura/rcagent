"""The cost decision (a pure function) and the refusal/timeout wording."""

from dataclasses import replace

from serenedb_extractor.format import refusal, timeout_message
from serenedb_extractor.query import cost
from serenedb_extractor.query.cost import decide
from serenedb_extractor.query.sampling import clause
from serenedb_extractor.query.stats import ScopeStats

# A remote Parquet scope: 1e9 entries in 1,000 row groups of 1e6; message 2 TB, level 1 GB.
BIG = ScopeStats(
    total_rows=1_000_000_000,
    rows_in_range=1_000_000_000,
    bytes_by_column={"message": 2_000_000_000_000, "level": 1_000_000_000, "ts": 2_000_000_000},
    time_skippable=False,
    remote=True,
    has_filter_index=False,
    has_search_index=False,
    can_sample=True,
    row_group_rows=1_000_000,
    file_rows=(1_000_000_000,),
)


def test_cheap_runs_exact():
    d = decide(BIG, ["level"], want_exact=True, sample_target=100_000, confirmed_cost=None, budget_s=30)
    assert d.status == "run" and d.plan.exact and d.plan.sampling is None
    assert d.plan.bytes == 1_000_000_000 and d.plan.seconds == 10.0


def test_only_the_columns_read_are_counted():
    d = decide(BIG, ["level", "ts"], True, 100_000, None, budget_s=30)
    assert d.plan.bytes == 3_000_000_000


def test_indexed_columns_cost_nothing():
    d = decide(BIG, ["message", "level"], True, 100_000, None, budget_s=30, indexed=("message",))
    assert d.status == "run" and d.plan.exact and d.plan.bytes == 1_000_000_000


def test_too_expensive_exact_falls_back_to_a_sample():
    # exact: 2 TB at 100 MB/s = 20,000 s. A 100k sample of 1e9 rows is a stride of 10,000 row groups:
    # more than there are, so the sample is the first row group: 1/1000 of the bytes = 20 s.
    d = decide(BIG, ["message"], True, 100_000, None, budget_s=30)
    assert d.status == "run" and not d.plan.exact and d.plan.sampling == "blocks"
    assert d.plan.seconds <= 30 and d.plan.bytes < 2_000_000_000_000 / 100
    assert any("an exact count would read ~2.0 TB" in n and "estimated from a sample" in n for n in d.plan.notes)


def test_cheaper_sampling_widens_the_margin_and_says_so():
    s = replace(BIG, bytes_by_column={"message": 2_000_000_000_000}, row_group_rows=1_000, file_rows=(1_000_000_000,))
    # target fraction 1e-4 -> 200 MB = 2 s; with a 0.5 s budget it must go to 1/4 or 1/8 of that.
    d = decide(s, ["message"], True, 100_000, None, budget_s=0.6)
    assert d.status == "run" and not d.plan.exact and d.plan.seconds <= 0.6
    assert any("margin is wider" in n for n in d.plan.notes)


def test_nothing_fits_asks_with_cost_and_token():
    d = decide(BIG, ["message"], True, 100_000, None, budget_s=0.0)
    assert d.status == "ask" and d.plan.exact
    assert d.message.startswith("TOO EXPENSIVE: needs ~2.0 TB read")
    assert f"confirmed_cost={d.plan.cost_token()}" in d.message
    assert "search index" in d.message and "narrow" in d.message


def test_scope_is_never_narrowed():
    d = decide(BIG, ["message"], True, 100_000, None, budget_s=30)
    assert d.plan.sample_rows is not None and d.plan.sample_rows < BIG.rows_in_range
    assert all("period" not in n for n in d.plan.notes)


def test_confirmation_within_twice_runs_exact_with_its_timeout():
    ask = decide(BIG, ["message"], True, 100_000, None, budget_s=0.0)
    token = ask.plan.cost_token()
    d = decide(replace(BIG, bytes_by_column={"message": 3_000_000_000_000}), ["message"], True, 100_000, token, budget_s=0.0)
    assert d.status == "run" and d.plan.exact and d.plan.confirmed
    assert cost.run_timeout(d.plan, default_s=60, max_s=600) == 600  # 30,000 s, clamped
    assert cost.run_timeout(replace(d.plan, seconds=100), default_s=60, max_s=600) == 200
    assert cost.run_timeout(replace(d.plan, confirmed=False, seconds=100), default_s=60, max_s=600) == 60


def test_confirmation_far_from_the_fresh_plan_asks_again():
    d = decide(BIG, ["message"], True, 100_000, "100GB", budget_s=0.0)
    assert d.status == "ask" and "does not match" in d.message


def test_no_cheaper_sampling_when_a_sample_reads_the_same():
    s = replace(BIG, can_sample=False)
    assert decide(s, ["message"], True, 100_000, None, budget_s=30).status == "ask"


def test_budget_default_is_read_at_call_time(monkeypatch):
    monkeypatch.setattr(cost, "BUDGET_SECONDS", 0.0)
    assert decide(BIG, ["level"], True, 100_000, None).status == "ask"


def test_block_clause_prunes_by_row_number():
    d = decide(BIG, ["message"], True, 100_000, None, budget_s=30)
    sql = clause(d.plan)
    assert sql.startswith("(file_row_number // 1000000) IN (0")
    assert clause(decide(BIG, ["level"], True, 100_000, None, budget_s=30).plan) == "TRUE"


def test_block_fraction_is_exact_for_a_short_last_block():
    s = replace(BIG, rows_in_range=5000, total_rows=5000, row_group_rows=5000, file_rows=(5000,),
                bytes_by_column={"message": 50_000}, remote=False)
    block, blocks, fraction = s.blocks(2)
    assert block == 2048 and blocks == (0, 2) and fraction == (2048 + 904) / 5000  # vector-sized blocks inside one row group


def test_timeout_message_whole_seconds():
    assert timeout_message(60.0, "searching fx", "narrow it") == "TIMEOUT after 60s: searching fx — narrow it"
    assert timeout_message(1.5, "x", "y").startswith("TIMEOUT after 1.5s: x")


def test_refusal_wording():
    out = refusal("needs ~2.0 TB read, ~6 h", ["run it anyway: confirmed_cost=2.0TB", "narrow it"])
    assert out.startswith("TOO EXPENSIVE: needs ~2.0 TB read, ~6 h.")
    assert "- run it anyway: confirmed_cost=2.0TB" in out and "- narrow it" in out
