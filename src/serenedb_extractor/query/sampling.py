"""Turning a plan's sample into SQL.

A block sample keeps every k-th block of row numbers (`file_row_number` in place). Written as
`(file_row_number // B) IN (...)` it is pushed into the Parquet scan and whole row groups outside
the chosen blocks are skipped (measured in #10: 5 of 20 row groups read, a quarter of the bytes).
`USING SAMPLE ... (system)` and `reservoir` read every row group, so they save no bytes.
"""

from serenedb_extractor.query.cost import Plan

POSITION = "file_row_number"


def clause(plan: Plan, position: str = POSITION) -> str:
    """A WHERE predicate selecting the plan's sample ("TRUE" when the plan reads everything)."""
    if plan.sampling is None or not plan.blocks:
        return "TRUE"
    listed = ", ".join(str(b) for b in plan.blocks)
    return f"({position} // {plan.block_rows}) IN ({listed})"
