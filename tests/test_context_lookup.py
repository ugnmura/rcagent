"""C2 (final review): what the occurrence lookup of get_context is priced as."""

from datetime import UTC, datetime

import pytest

from serenedb_extractor.catalog.models import FieldRoles, LogTable
from serenedb_extractor.errors import UserFacingError
from serenedb_extractor.query.stats import GroupStat, ScopeStats
from serenedb_extractor.tools.context import _lookup_scope


def _lt(mode: str, fmt: str) -> LogTable:
    now = datetime.now(UTC)
    return LogTable("t", "/x", fmt, mode, "rel", FieldRoles(message='"m"', timestamp='"ts"'), None, None, 1000, "UTC", now, now)


GROUPS = tuple(GroupStat(i * 100, 100, {"m": 1000}) for i in range(10))
PARQUET = ScopeStats(1000, 1000, {"m": 10_000}, False, False, False, False, can_sample=True, groups=GROUPS)


def test_single_parquet_lookup_reads_only_the_rows_group():
    st, sql = _lookup_scope(_lt("in_place", "parquet"), PARQUET, {"occ_file": "/x", "occ_row": 250})
    assert st.bytes_for(["m"]) == 1000 and sql == " AND file_row_number BETWEEN 200 AND 299"


def test_a_row_past_the_file_is_no_entry_and_reads_nothing():
    with pytest.raises(UserFacingError, match="No entry"):
        _lookup_scope(_lt("in_place", "parquet"), PARQUET, {"occ_file": "/x", "occ_row": 5000})


def test_copied_entry_lookup_is_a_key_lookup_of_one_entry():
    st = ScopeStats(1000, 1000, {"m": 10_000}, False, False, False, False)
    one, sql = _lookup_scope(_lt("copied", "raw"), st, {"occ_row": 7})
    assert one.bytes_for(["m"]) == 10 and sql == ""
