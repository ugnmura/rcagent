"""Reads and writes of the catalog tables. Later tickets add the write methods."""

from typing import Any

from serenedb_extractor.catalog.models import FieldRoles, LogTable, UnknownLogTable
from serenedb_extractor.db import Database

_COLUMNS = (
    "name, source, source_format, mode, relation, role_timestamp, role_message, role_level, "
    "role_service, role_host, role_component, role_trace, role_order, filter_index_name, "
    "search_index_name, row_count, timezone, created_at, roles_updated_at"
)


def _log_table(r: dict[str, Any]) -> LogTable:
    roles = FieldRoles(
        message=r["role_message"],
        timestamp=r["role_timestamp"],
        level=r["role_level"],
        service=r["role_service"],
        host=r["role_host"],
        component=r["role_component"],
        trace=r["role_trace"],
        order=r["role_order"],
    )
    return LogTable(
        name=r["name"],
        source=r["source"],
        source_format=r["source_format"],
        mode=r["mode"],
        relation=r["relation"],
        roles=roles,
        filter_index_name=r["filter_index_name"],
        search_index_name=r["search_index_name"],
        row_count=r["row_count"],
        timezone=r["timezone"],
        created_at=r["created_at"],
        roles_updated_at=r["roles_updated_at"],
    )


class CatalogStore:
    def __init__(self, db: Database) -> None:
        self.db = db

    def list_log_tables(self) -> list[LogTable]:
        rows = self.db.read(f"SELECT {_COLUMNS} FROM extractor.log_tables ORDER BY name")
        return [_log_table(r) for r in rows.dicts()]

    def get_log_table(self, name: str) -> LogTable:
        rows = self.db.read(
            f"SELECT {_COLUMNS} FROM extractor.log_tables WHERE name = %(name)s", {"name": name}
        )
        if not rows.rows:
            raise UnknownLogTable(name, [t.name for t in self.list_log_tables()])
        return _log_table(rows.dicts()[0])
