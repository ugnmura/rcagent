"""Creating and filling the copied tables `extractor.lt_<name>` (shared by raw and structured copies)."""

from typing import Any

from serenedb_extractor.context import AppContext
from serenedb_extractor.db import quote_ident

BATCH_ENTRIES = 2000


def drop_table(ctx: AppContext, relation: str) -> None:
    ctx.db.write(f"DROP TABLE IF EXISTS {relation}", {})


def create_table(ctx: AppContext, relation: str, columns: list[tuple[str, str]], key: str | None = "entry_id") -> None:
    """(Re)create the table; `key` names the primary-key column, if any."""
    defs = ", ".join(f"{quote_ident(n)} {t}" + (" PRIMARY KEY" if n == key else "") for n, t in columns)
    drop_table(ctx, relation)
    ctx.db.write(f"CREATE TABLE {relation} ({defs})", {})


class Writer:
    """Buffers entries and inserts them in batches."""

    def __init__(self, ctx: AppContext, relation: str, columns: list[str]) -> None:
        self.ctx, self.relation, self.columns = ctx, relation, columns
        self.rows: list[tuple[Any, ...]] = []
        self.total = 0

    def add(self, row: tuple[Any, ...]) -> None:
        self.rows.append(row)
        if len(self.rows) >= BATCH_ENTRIES:
            self.flush()

    def flush(self) -> None:
        if self.rows:
            self.total += self.ctx.db.copy_rows(self.relation, self.columns, self.rows)
            self.rows = []
