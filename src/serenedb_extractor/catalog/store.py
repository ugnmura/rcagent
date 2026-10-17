"""Reads and writes of the catalog tables. Later tickets add the template methods."""

from datetime import UTC, datetime
from typing import Any

from serenedb_extractor.catalog.models import ROLE_FIELDS, FieldRoles, LogTable, UnknownLogTable
from serenedb_extractor.db import Database

_COLUMNS = (
    "name, source, source_format, mode, relation, "
    + ", ".join(f"role_{f}" for f in ROLE_FIELDS)
    + ", filter_index_name, search_index_name, row_count, timezone, created_at, roles_updated_at"
)


def _log_table(r: dict[str, Any]) -> LogTable:
    roles = FieldRoles(**{f: r[f"role_{f}"] for f in ROLE_FIELDS})
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

    def create_log_table(self, lt: LogTable) -> None:
        """Insert a new log table; the template numbering starts at 1."""
        cols = ["name", "source", "source_format", "mode", "relation"]
        cols += [f"role_{f}" for f in ROLE_FIELDS]
        cols += ["filter_index_name", "search_index_name", "row_count", "timezone", "created_at", "roles_updated_at"]
        vals: dict[str, Any] = {
            "name": lt.name,
            "source": lt.source,
            "source_format": lt.source_format,
            "mode": lt.mode,
            "relation": lt.relation,
            **{f"role_{f}": getattr(lt.roles, f) for f in ROLE_FIELDS},
            "filter_index_name": lt.filter_index_name,
            "search_index_name": lt.search_index_name,
            "row_count": lt.row_count,
            "timezone": lt.timezone,
            "created_at": lt.created_at,
            "roles_updated_at": lt.roles_updated_at,
        }
        placeholders = ", ".join(f"%({c})s" for c in cols)
        self.db.write(f"INSERT INTO extractor.log_tables ({', '.join(cols)}) VALUES ({placeholders})", vals)

    def update_roles(self, name: str, roles: FieldRoles) -> None:
        """Replace the field roles only; nothing else about the log table changes."""
        sets = ", ".join(f"role_{f} = %({f})s" for f in ROLE_FIELDS)
        params: dict[str, Any] = {f: getattr(roles, f) for f in ROLE_FIELDS}
        params.update(name=name, now=datetime.now(UTC).replace(tzinfo=None))
        self.db.write(f"UPDATE extractor.log_tables SET {sets}, roles_updated_at = %(now)s WHERE name = %(name)s", params)

    def template_count(self, name: str) -> int:
        return int(
            self.db.read("SELECT count(*) FROM extractor.templates WHERE log_table = %(n)s", {"n": name}).scalar()
        )
