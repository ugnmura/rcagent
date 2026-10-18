"""I4 (final review): the empty-result diagnosis never replaces a correct "0 matches". Its checks go
through the cost check with a short timeout; one that is too expensive or runs out of time is said
to be unchecked, the others still run."""

from datetime import UTC, datetime

import pytest

from rcagent.catalog.models import FieldRoles, LogTable
from rcagent.config import Settings
from rcagent.db import QueryTimeout, Rows
from rcagent.query import cost, filters
from rcagent.query.filters import Filters, TimeRange
from rcagent.query.stats import ScopeStats

GB = 1_000_000_000
COLS = {"ts": "TIMESTAMP WITH TIME ZONE", "message": "VARCHAR", "level": "VARCHAR"}


def _stats(nbytes: int) -> ScopeStats:
    return ScopeStats(10, 10, {"ts": nbytes, "level": nbytes, "message": nbytes}, False, False, False, False)


def _lt() -> LogTable:
    now = datetime.now(UTC)
    roles = FieldRoles(message='"message"', timestamp='"ts"', level='"level"')
    return LogTable("t", "/x", "table", "in_place", "extractor.lt_t", roles, None, None, 10, "UTC", now, now)


class Db:
    settings = Settings("postgresql://r", "postgresql://w", False, None, None)

    def __init__(self, fail: Exception | None = None) -> None:
        self.fail = fail
        self.timeouts: list[float | None] = []

    def read(self, sql, params=None, timeout_s=None, **_k):
        self.timeouts.append(timeout_s)
        if self.fail is not None:
            raise self.fail
        return Rows(["v"], [])


def test_unaffordable_filter_check_is_said_to_be_unchecked(monkeypatch):
    monkeypatch.setattr(cost, "collect", lambda db, lt, tr: _stats(1000 * GB))
    db = Db(AssertionError("nothing may be read"))
    lines = filters.diagnose_empty(db, _lt(), TimeRange(), Filters.from_dict({"level": "error"}), COLS)  # type: ignore[arg-type]
    assert lines == ["Whether level='error' matches anything wasn't checked (that would need ~1.0 TB read, ~33 min)."], lines


def test_a_timed_out_filter_check_is_said_to_be_unchecked(monkeypatch):
    monkeypatch.setattr(cost, "collect", lambda db, lt, tr: _stats(1000))
    db = Db(QueryTimeout(10, "checking"))
    lines = filters.diagnose_empty(db, _lt(), TimeRange(), Filters.from_dict({"level": "error"}), COLS)  # type: ignore[arg-type]
    assert lines == ["Whether level='error' matches anything wasn't checked (the check ran out of time)."], lines
    assert db.timeouts and all(t is not None and t <= filters.DIAGNOSE_TIMEOUT_S for t in db.timeouts)
