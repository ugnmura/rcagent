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
    one, sql = _lookup_scope(_lt("copied", "raw"), st, {"occ_row": 7}, keyed=True)
    assert one.bytes_for(["m"]) == 10 and sql == ""


def test_copied_entry_lookup_without_a_key_is_priced_as_a_full_read():
    # The source brought its own entry_id column, so setup made no primary key: finding one entry scans.
    st = ScopeStats(1000, 1000, {"m": 10_000}, False, False, False, False)
    full, sql = _lookup_scope(_lt("copied", "parquet"), st, {"occ_row": 7}, keyed=False)
    assert full.bytes_for(["m"]) == 10_000 and full.rows_in_range == 1000 and sql == ""


@pytest.mark.db
def test_entry_id_key_is_read_from_the_table_metadata(database):
    from serenedb_extractor.tools.context import entry_id_is_key

    database.write("CREATE SCHEMA IF NOT EXISTS lookup_probe", {})
    try:
        database.write("CREATE TABLE lookup_probe.keyed (entry_id BIGINT PRIMARY KEY, m VARCHAR)", {})
        database.write("CREATE TABLE lookup_probe.plain (entry_id BIGINT, m VARCHAR)", {})
        now = datetime.now(UTC)
        roles = FieldRoles(message='"m"')

        def lt(rel: str) -> LogTable:
            return LogTable("t", "/x", "parquet", "copied", rel, roles, None, None, 1, "UTC", now, now)

        assert entry_id_is_key(database, lt("lookup_probe.keyed"))
        assert not entry_id_is_key(database, lt("lookup_probe.plain"))
    finally:
        database.write("DROP SCHEMA lookup_probe CASCADE", {})
