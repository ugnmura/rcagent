"""Reads and writes of the catalog tables. Later tickets add generalize/merge/redirect/rename."""

import json
from datetime import UTC, datetime
from typing import Any

from serenedb_extractor.catalog.models import (
    ROLE_FIELDS,
    CandidateTemplate,
    FieldRoles,
    LogTable,
    Param,
    Template,
    UnknownLogTable,
    UpsertResult,
)
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

_TEMPLATE_COLUMNS = (
    "log_table, template_id, template, regex, params, example, first_seen, last_seen, last_estimate, last_estimate_at"
)


def _naive_utc(dt: datetime | None) -> datetime | None:
    return dt.astimezone(UTC).replace(tzinfo=None) if dt is not None and dt.tzinfo is not None else dt


def _template(r: dict[str, Any]) -> Template:
    raw = r["params"]
    items = json.loads(raw) if isinstance(raw, str) else raw
    return Template(
        log_table=r["log_table"],
        template_id=r["template_id"],
        template=r["template"],
        regex=r["regex"],
        params=[Param(int(p["pos"]), p["name"], p["kind"]) for p in items],
        example=r["example"],
        first_seen=r["first_seen"],
        last_seen=r["last_seen"],
        last_estimate=r["last_estimate"],
        last_estimate_at=r["last_estimate_at"],
    )


def _template_number(template_id: str) -> int:
    return int(template_id[1:]) if template_id[1:].isdigit() else 0


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

    def set_timezone(self, name: str, timezone: str) -> None:
        self.db.write(
            "UPDATE extractor.log_tables SET timezone = %(tz)s WHERE name = %(name)s", {"tz": timezone, "name": name}
        )

    def template_count(self, name: str) -> int:
        return int(
            self.db.read("SELECT count(*) FROM extractor.templates WHERE log_table = %(n)s", {"n": name}).scalar()
        )

    def templates(self, log_table: str) -> list[Template]:
        rows = self.db.read(
            f"SELECT {_TEMPLATE_COLUMNS} FROM extractor.templates WHERE log_table = %(n)s", {"n": log_table}
        )
        return sorted((_template(r) for r in rows.dicts()), key=lambda t: _template_number(t.template_id))

    def upsert_survey_templates(
        self, log_table: str, found: list[CandidateTemplate], observed_at: datetime
    ) -> UpsertResult:
        """Save surveyed templates: identical template text is `known` (same ID, sightings refreshed),
        anything else is `new` with the next T<n> from the log table's counter (never reused)."""
        by_text = {t.template: t for t in self.templates(log_table)}
        fresh = [c for c in dict.fromkeys(c.template for c in found) if c not in by_text]
        first_no = 0
        if fresh:
            first_no = int(
                self.db.read(
                    "SELECT next_template_no FROM extractor.log_tables WHERE name = %(n)s", {"n": log_table}
                ).scalar()
            )
            self.db.write(
                "UPDATE extractor.log_tables SET next_template_no = %(next)s WHERE name = %(n)s",
                {"next": first_no + len(fresh), "n": log_table},
            )
        numbers = {text: first_no + i for i, text in enumerate(fresh)}
        now = _naive_utc(observed_at)
        items: list[tuple[Template, Any]] = []
        for c in found:
            first, last = _naive_utc(c.first_seen), _naive_utc(c.last_seen)
            known = by_text.get(c.template)
            if known is None:
                tid = f"T{numbers[c.template]}"
                self.db.write(
                    "INSERT INTO extractor.templates (log_table, template_id, template, regex, params, example, "
                    "first_seen, last_seen, last_estimate, last_estimate_at, updated_at) VALUES "
                    "(%(lt)s, %(id)s, %(t)s, %(re)s, %(p)s, %(ex)s, %(fs)s, %(ls)s, %(est)s, %(at)s, %(at)s)",
                    {
                        "lt": log_table, "id": tid, "t": c.template, "re": c.regex,
                        "p": json.dumps([{"pos": p.pos, "name": p.name, "kind": p.kind} for p in c.params]),
                        "ex": c.example, "fs": first, "ls": last, "est": c.estimate, "at": now,
                    },
                )
                saved = Template(log_table, tid, c.template, c.regex, list(c.params), c.example, first, last, c.estimate, now)
                by_text[c.template] = saved
                items.append((saved, "new"))
                continue
            firsts = [d for d in (known.first_seen, first) if d is not None]
            lasts = [d for d in (known.last_seen, last) if d is not None]
            merged_first, merged_last = min(firsts, default=None), max(lasts, default=None)
            self.db.write(
                "UPDATE extractor.templates SET first_seen = %(fs)s, last_seen = %(ls)s, last_estimate = %(est)s, "
                "last_estimate_at = %(at)s, updated_at = %(at)s WHERE log_table = %(lt)s AND template_id = %(id)s",
                {"fs": merged_first, "ls": merged_last, "est": c.estimate, "at": now, "lt": log_table, "id": known.template_id},
            )
            refreshed = Template(
                log_table, known.template_id, known.template, known.regex, known.params, known.example,
                merged_first, merged_last, c.estimate, now,
            )
            by_text[c.template] = refreshed
            items.append((refreshed, "known"))
        return UpsertResult(items, {})
