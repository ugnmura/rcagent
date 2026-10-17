from serenedb_extractor import format as fmt
from serenedb_extractor.catalog.models import LogTable
from serenedb_extractor.context import AppContext


def _line(t: LogTable) -> str:
    roles = ", ".join(t.roles.present())
    rows = f"{t.row_count:,} rows" if t.row_count is not None else "row count not recorded"
    return f"- {t.name}: {t.source_format} from {t.source} ({t.mode}); {rows}; fields: {roles}"


def describe_logs(ctx: AppContext, log_table: str | None = None) -> str:
    header = fmt.how_measured("exact, read from the extractor catalog")
    if log_table is not None:
        t = ctx.store.get_log_table(log_table)
        return header + "\n" + _line(t)
    tables = ctx.store.list_log_tables()
    if not tables:
        return header + "\nThere are no log tables yet. Set one up to start analysing logs."
    return header + "\n" + "\n".join(_line(t) for t in tables)
