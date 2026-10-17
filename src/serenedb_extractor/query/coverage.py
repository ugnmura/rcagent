"""Entries a time range cannot reach: copied-table entries without a timestamp."""

from serenedb_extractor.catalog.models import LogTable
from serenedb_extractor.db import Database
from serenedb_extractor.errors import UserFacingError
from serenedb_extractor.query import cost
from serenedb_extractor.query.filters import TimeRange, role_sql
from serenedb_extractor.query.stats import role_columns

NARROW = "narrow it: a shorter period (start/end) or more filters, then try again."


def untimestamped_text(n: int) -> str:
    """The note for `n` (> 0) entries without a timestamp."""
    if n == 1:
        return "1 entry in this log table has no timestamp and is outside any time range."
    return f"{n:,} entries in this log table have no timestamp and are outside any time range."


def untimestamped_unknown(why: str) -> str:
    return f"Couldn't count entries without a timestamp ({why}); some entries may be outside any time range."


def untimestamped_note(db: Database, lt: LogTable, tr: TimeRange) -> str | None:
    """With a time range on a copied table: a note on the entries without a timestamp, which fall
    outside any range. The count goes through the cost check and the standard read path. When it
    cannot be counted (too expensive, or it timed out) the note says so. None only when there is no
    range, the table is not copied, or no entry lacks a timestamp."""
    if not tr.bounded or lt.mode != "copied" or lt.roles.timestamp is None:
        return None
    columns = role_columns(lt.roles.timestamp)
    stats, decision = cost.check(db, lt, TimeRange(), columns)
    if decision.status != "run" or not decision.plan.exact:
        return untimestamped_unknown(f"counting would need {cost.cost_text(cost.exact_plan(stats, columns))}")
    timeout = cost.run_timeout(decision.plan, db.settings.default_timeout_s, db.settings.max_timeout_s)
    try:
        n = db.read(
            f"SELECT count(*) FROM {lt.relation} WHERE ({role_sql(lt, 'timestamp')}) IS NULL",
            {}, timeout_s=timeout, what=f"counting entries without a timestamp in log table {lt.name}", how_to_narrow=NARROW,
        ).scalar()
    except UserFacingError:
        return untimestamped_unknown("the count ran out of time")
    return untimestamped_text(int(n)) if n else None
