"""Reads and writes of the catalog tables, including generalization, merges, redirects and renames."""

import json
import re
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from serenedb_extractor.catalog.models import (
    ROLE_FIELDS,
    CandidateTemplate,
    FieldRoles,
    LogTable,
    Param,
    Resolved,
    Template,
    UnknownLogTable,
    UnknownTemplate,
    UpsertResult,
)
from serenedb_extractor.db import Database
from serenedb_extractor.errors import UserFacingError

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


PARAM_NAME = re.compile(r"[a-z][a-z0-9_]*")


def _params_json(params: list[Param]) -> str:
    return json.dumps([{"pos": p.pos, "name": p.name, "kind": p.kind} for p in params])


def _carry_names(old: list[Param], new: list[Param]) -> list[Param]:
    """A renamed parameter keeps its name through generalization when the position and kind still match."""
    by_pos = {p.pos: p for p in old}
    out: list[Param] = []
    taken: set[str] = set()
    for p in new:
        before = by_pos.get(p.pos)
        name = before.name if before is not None and before.kind == p.kind and before.name not in taken else p.name
        while name in taken:
            name += "_"
        taken.add(name)
        out.append(Param(p.pos, name, p.kind))
    return out


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
        """Save surveyed templates.

        Identical template text is `known` (same ID, sightings refreshed). A candidate whose regex
        full-matches other templates' examples is `generalized`: the lowest-numbered match keeps its ID
        and takes the candidate's template, the others are deleted and redirect to it (every redirect
        stays one hop). Anything else is `new` with the next T<n> from the log table's counter (never reused).
        """
        current = {t.template_id: t for t in self.templates(log_table)}
        now = _naive_utc(observed_at)
        merged: dict[str, str] = {}
        state = dict(current)  # what the catalog holds as we apply each candidate
        items: list[tuple[Template, Any]] = []
        for c in found:
            first, last = _naive_utc(c.first_seen), _naive_utc(c.last_seen)
            same = next((t for t in state.values() if t.template == c.template), None)
            if same is not None:
                saved = self._refresh(log_table, same, first, last, c.estimate, now)
                state[saved.template_id] = saved
                items.append((saved, "known"))
                continue
            rx = re.compile(c.regex)
            hits = sorted((t for t in state.values() if rx.fullmatch(t.example)), key=lambda t: _template_number(t.template_id))
            if not hits:
                # One atomic statement reserves the number, so concurrent upserts never collide.
                reserved = self.db.write(
                    "UPDATE extractor.log_tables SET next_template_no = next_template_no + 1 WHERE name = %(n)s "
                    "RETURNING next_template_no",
                    {"n": log_table},
                ).scalar()
                tid = f"T{int(reserved) - 1}"
                self.db.write(
                    "INSERT INTO extractor.templates (log_table, template_id, template, regex, params, example, "
                    "first_seen, last_seen, last_estimate, last_estimate_at, updated_at) VALUES "
                    "(%(lt)s, %(id)s, %(t)s, %(re)s, %(p)s, %(ex)s, %(fs)s, %(ls)s, %(est)s, %(at)s, %(at)s)",
                    {
                        "lt": log_table, "id": tid, "t": c.template, "re": c.regex, "p": _params_json(list(c.params)),
                        "ex": c.example, "fs": first, "ls": last, "est": c.estimate, "at": now,
                    },
                )
                saved = Template(log_table, tid, c.template, c.regex, list(c.params), c.example, first, last, c.estimate, now)
                state[tid] = saved
                items.append((saved, "new"))
                continue
            survivor, absorbed = hits[0], hits[1:]
            firsts = [d for d in (*(t.first_seen for t in hits), first) if d is not None]
            lasts = [d for d in (*(t.last_seen for t in hits), last) if d is not None]
            params = _carry_names(survivor.params, list(c.params))
            self.db.write(
                "UPDATE extractor.templates SET template = %(t)s, regex = %(re)s, params = %(p)s, example = %(ex)s, "
                "first_seen = %(fs)s, last_seen = %(ls)s, last_estimate = %(est)s, last_estimate_at = %(at)s, "
                "updated_at = %(at)s WHERE log_table = %(lt)s AND template_id = %(id)s",
                {
                    "t": c.template, "re": c.regex, "p": _params_json(params), "ex": c.example,
                    "fs": min(firsts, default=None), "ls": max(lasts, default=None), "est": c.estimate, "at": now,
                    "lt": log_table, "id": survivor.template_id,
                },
            )
            for gone in absorbed:
                self.db.write(
                    "DELETE FROM extractor.templates WHERE log_table = %(lt)s AND template_id = %(id)s",
                    {"lt": log_table, "id": gone.template_id},
                )
                self.db.write(
                    "UPDATE extractor.template_redirects SET new_id = %(new)s WHERE log_table = %(lt)s AND new_id = %(old)s",
                    {"new": survivor.template_id, "lt": log_table, "old": gone.template_id},
                )
                self.db.write(
                    "INSERT INTO extractor.template_redirects (log_table, old_id, new_id, merged_at) "
                    "VALUES (%(lt)s, %(old)s, %(new)s, %(at)s)",
                    {"lt": log_table, "old": gone.template_id, "new": survivor.template_id, "at": now},
                )
                del state[gone.template_id]
                for k, v in list(merged.items()):
                    if v == gone.template_id:
                        merged[k] = survivor.template_id
                merged[gone.template_id] = survivor.template_id
            saved = Template(
                log_table, survivor.template_id, c.template, c.regex, params, c.example,
                min(firsts, default=None), max(lasts, default=None), c.estimate, now,
            )
            state[survivor.template_id] = saved
            items.append((saved, "generalized"))
        return UpsertResult(items, merged)

    def _refresh(
        self, log_table: str, known: Template, first: datetime | None, last: datetime | None, estimate: int | None,
        now: datetime | None,
    ) -> Template:
        firsts = [d for d in (known.first_seen, first) if d is not None]
        lasts = [d for d in (known.last_seen, last) if d is not None]
        merged_first, merged_last = min(firsts, default=None), max(lasts, default=None)
        self.db.write(
            "UPDATE extractor.templates SET first_seen = %(fs)s, last_seen = %(ls)s, last_estimate = %(est)s, "
            "last_estimate_at = %(at)s, updated_at = %(at)s WHERE log_table = %(lt)s AND template_id = %(id)s",
            {"fs": merged_first, "ls": merged_last, "est": estimate, "at": now, "lt": log_table, "id": known.template_id},
        )
        return replace(known, first_seen=merged_first, last_seen=merged_last, last_estimate=estimate, last_estimate_at=now)

    def resolve(self, log_table: str, template_id: str) -> Resolved:
        """The live template for an ID, following a merge redirect (one hop by construction)."""
        wanted = template_id.strip()
        rows = self.db.read(
            f"SELECT {_TEMPLATE_COLUMNS} FROM extractor.templates WHERE log_table = %(n)s AND template_id = %(id)s",
            {"n": log_table, "id": wanted},
        ).dicts()
        if rows:
            return Resolved(_template(rows[0]), None)
        hop = self.db.read(
            "SELECT new_id FROM extractor.template_redirects WHERE log_table = %(n)s AND old_id = %(id)s",
            {"n": log_table, "id": wanted},
        ).dicts()
        if hop:
            target = self.db.read(
                f"SELECT {_TEMPLATE_COLUMNS} FROM extractor.templates WHERE log_table = %(n)s AND template_id = %(id)s",
                {"n": log_table, "id": hop[0]["new_id"]},
            ).dicts()
            if target:
                return Resolved(_template(target[0]), wanted)
        raise UnknownTemplate(template_id, self._closest(log_table, wanted))

    def _closest(self, log_table: str, wanted: str) -> list[str]:
        """Templates the unknown ID may have meant: a differently spelled ID, or whose regex matches it as text."""
        known = self.templates(log_table)
        spelled = re.fullmatch(r"[Tt]\s*0*(\d+)", wanted)
        if spelled:
            same = [t.template_id for t in known if t.template_id == f"T{spelled.group(1)}"]
            if same:
                return same
            redirect = self.db.read(
                "SELECT new_id FROM extractor.template_redirects WHERE log_table = %(n)s AND old_id = %(id)s",
                {"n": log_table, "id": f"T{spelled.group(1)}"},
            ).dicts()
            return [r["new_id"] for r in redirect]
        return [t.template_id for t in known if t.template == wanted or re.fullmatch(t.regex, wanted)][:3]

    def rename_parameter(self, log_table: str, template_id: str, old: str, new: str) -> Resolved:
        """Rename one parameter for good; later surveys keep the name. Follows a merge redirect."""
        if not PARAM_NAME.fullmatch(new):
            raise UserFacingError(
                f"'{new}' is an invalid parameter name: use lower-case letters, digits and underscores, starting with a letter."
            )
        resolved = self.resolve(log_table, template_id)
        template = resolved.template
        target = next((p for p in template.params if p.name == old), None)
        if target is None:
            names = ", ".join(p.name for p in template.params) or "none"
            raise UserFacingError(f"{template.template_id} has no parameter named '{old}'. Its parameters: {names}.")
        if new != old and any(p.name == new for p in template.params):
            raise UserFacingError(f"{template.template_id} already has a parameter named '{new}'; pick another name.")
        params = [Param(p.pos, new if p is target else p.name, p.kind) for p in template.params]
        self.db.write(
            "UPDATE extractor.templates SET params = %(p)s, updated_at = %(at)s "
            "WHERE log_table = %(lt)s AND template_id = %(id)s",
            {"p": _params_json(params), "at": datetime.now(UTC).replace(tzinfo=None), "lt": log_table, "id": template.template_id},
        )
        return Resolved(replace(template, params=params), resolved.redirected_from)
