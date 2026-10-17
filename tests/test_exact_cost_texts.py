"""I7 (final review): when the cost check offers only a sample, a "would need" text quotes the EXACT
cost of what it skipped, never the sample's."""

from datetime import UTC, datetime

import pytest

from serenedb_extractor.catalog.models import FieldRoles, LogTable
from serenedb_extractor.config import Settings
from serenedb_extractor.query import cost, coverage, filters
from serenedb_extractor.query.filters import ScanTooExpensive, TimeRange
from serenedb_extractor.query.stats import GroupStat, ScopeStats
from serenedb_extractor.tools import describe

GB = 1_000_000_000
STATS = ScopeStats(
    total_rows=100_000_000,
    rows_in_range=100_000_000,
    bytes_by_column={"ts": 100 * GB},
    time_skippable=True,
    remote=False,
    has_filter_index=False,
    has_search_index=False,
    can_sample=True,
    groups=tuple(GroupStat(i * 1_000_000, 1_000_000, {"ts": GB}) for i in range(100)),
)
EXACT = "~100.0 GB"  # what an exact scan of ts reads
SAMPLE = "~1.0 GB"


class NoDb:
    settings = Settings("postgresql://r", "postgresql://w", False, None, None)

    def read(self, *a, **k):
        raise AssertionError("nothing may be read when the scan is skipped")


@pytest.fixture(autouse=True)
def sampled_only(monkeypatch):
    monkeypatch.setattr(cost, "collect", lambda db, lt, tr: STATS)
    d = cost.decide(STATS, ["ts"], True, 100_000, None)
    assert d.status == "run" and not d.plan.exact  # the premise: only a sample fits


def _lt(mode: str = "copied") -> LogTable:
    now = datetime.now(UTC)
    return LogTable("t", "/x", "raw", mode, "extractor.c_t", FieldRoles(message='"message"', timestamp='"ts"'), None, None, 1, "UTC", now, now)


TR = TimeRange(datetime(2026, 3, 1, tzinfo=UTC), datetime(2026, 3, 2, tzinfo=UTC))


def _check(text: str) -> None:
    assert EXACT.replace("~", "") in text and SAMPLE.replace("~", "") not in text, text


def test_describe_skip_text_quotes_the_exact_cost():
    _check(describe._affordable(NoDb(), _lt(), TR, ["ts"]) or "")  # type: ignore[arg-type]


def test_untimestamped_note_quotes_the_exact_cost():
    _check(coverage.untimestamped_note(NoDb(), _lt(), TR) or "")  # type: ignore[arg-type]


def test_time_range_scan_refusal_quotes_the_exact_cost():
    with pytest.raises(ScanTooExpensive) as e:
        filters.data_range(NoDb(), _lt(), {"ts": "TIMESTAMP WITH TIME ZONE"})  # type: ignore[arg-type]
    _check(str(e.value))
