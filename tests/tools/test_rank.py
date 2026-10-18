"""rank_problems: candidates from a survey, exact counts over both periods, and a stated score."""

import re
import shutil
from pathlib import Path

import pytest

from serenedb_extractor.tools import rank
from tests.conftest import call

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
pytestmark = pytest.mark.db


@pytest.fixture
async def corpus(mcp, tmp_path):
    for name, fixture in (("bgl", "bgl_sample.log"), ("openstack", "openstack_sample.log")):
        dest = tmp_path / fixture
        shutil.copy(FIXTURES / fixture, dest)
        await call(mcp, "setup_log_table", name=name, source=str(dest))


def _items(out: str) -> list[tuple[int, int, str]]:
    """(rank, score, template text) per ranked problem."""
    return [(int(a), int(b), c) for a, b, c in re.findall(r"^(\d+)\. score (\d+)/18  \[\S+ T\d+\] (.*)$", out, re.M)]


async def test_ranks_by_the_stated_score_with_exact_counts(mcp, corpus):
    out = await call(mcp, "rank_problems", log_tables=["bgl"], start="2005-06-09", end="2005-06-15")
    assert "score = 2 x severity + change + persistence + spread + share" in out
    assert "does not measure impact" in out
    items = _items(out)
    assert {"data TLB error interrupt", "data storage interrupt"} <= {t for _, _, t in items}
    tlb = next(b for b in out.split("\n\n") if "] data TLB error interrupt" in b)
    assert "spread: 1 distinct host\n" in tlb and "spread 0" in tlb  # one node: no spread, so it ranks lower
    assert [s for _, s, _ in items] == sorted((s for _, s, _ in items), reverse=True)
    assert "60 entries this period (exact; FATAL 60)" in out
    assert "owning team: Node OS (from the stand-in ownership table" in out
    # the points shown add up to the score
    for block in out.split("\n\n")[1:]:
        m = re.search(r"score (\d+)/18", block)
        pts = re.search(r"points: severity (\d+), change (\d+), persistence (\d+), spread (\d+), share (\d+)", block)
        if m and pts:
            assert int(m.group(1)) == sum(int(x) for x in pts.groups())


async def test_a_gap_makes_the_change_not_comparable(mcp, corpus):
    out = await call(mcp, "rank_problems", log_tables=["bgl"], start="2005-06-09", end="2005-06-15")
    assert "limited comparison" in out and "not comparable" in out
    assert "new:" not in out  # nothing is called new across missing data


async def test_whole_corpus_and_levels(mcp, corpus):
    out = await call(mcp, "rank_problems", start="2005-06-09", end="2005-06-15", min_level="fatal")
    assert "Log table openstack: no entries at fatal level or above in this period" in out
    assert _items(out)
    warn = await call(mcp, "rank_problems", log_tables=["openstack"], start="2017-05-16", end="2017-05-17")
    assert "WARNING" in warn and _items(warn)


async def test_bad_input_is_explained(mcp, corpus):
    assert "needs start and end" in await call(mcp, "rank_problems", start="2005-06-09", end="")
    assert "min_level must be one of" in await call(
        mcp, "rank_problems", start="2005-06-09", end="2005-06-15", min_level="info"
    )
    assert "Use min_level" in await call(
        mcp, "rank_problems", start="2005-06-09", end="2005-06-15", filters={"level": "FATAL"}
    )


def test_severity_names():
    assert rank.SEVERITY["FATAL"] == 3 and rank.SEVERITY["ERROR"] == 2 and rank.SEVERITY["WARNING"] == 1
    assert "INFO" not in rank.SEVERITY


def test_breadth_weighs_wildcards_above_typed_placeholders():
    from serenedb_extractor.catalog.store import breadth

    assert breadth("x <*> <*>") == 4 and breadth("x <PATH>") == 1 and breadth("plain text") == 0
