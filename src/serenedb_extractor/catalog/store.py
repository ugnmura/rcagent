"""Reads and writes of the catalog tables, including generalization, merges, redirects and renames."""

import json
import logging
import re
import threading
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any, Literal

import re2  # type: ignore[import-untyped]

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


_log = logging.getLogger("serenedb_extractor")


def full_match(regex: str, text: str) -> bool:
    """Whether a template regex matches `text` in full, with RE2 (SereneDB's engine, as in query/tags.py).
    A regex RE2 rejects matches nothing (and is logged)."""
    try:
        return re2.fullmatch(regex, text) is not None
    except re2.error as exc:
        _log.warning("a template regex does not compile with RE2 and matches nothing: %s", exc)
        return False


_UPSERT_LOCK = threading.Lock()


def _bounds(
    seen: list[Template], first: datetime | None, last: datetime | None
) -> tuple[datetime | None, datetime | None]:
    """Earliest first_seen and latest last_seen over existing templates and a new sighting."""
    firsts = [d for d in (*(t.first_seen for t in seen), first) if d is not None]
    lasts = [d for d in (*(t.last_seen for t in seen), last) if d is not None]
    return min(firsts, default=None), max(lasts, default=None)


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

    def set_index(self, name: str, kind: str, index_name: str | None, columns: list[str] | None = None) -> None:
        """Record (or clear) the filter or search index built for a log table, with the columns it covers."""
        column = {"filter": "filter_index_name", "search": "search_index_name"}[kind]
        self.db.write(
            f"UPDATE extractor.log_tables SET {column} = %(idx)s WHERE name = %(name)s",
            {"idx": index_name, "name": name},
        )
        key = {"lt": name, "kind": kind}
        self.db.write("DELETE FROM extractor.log_index_columns WHERE log_table = %(lt)s AND kind = %(kind)s", key)
        if index_name is not None:
            self.db.write(
                "INSERT INTO extractor.log_index_columns (log_table, kind, columns) VALUES (%(lt)s, %(kind)s, %(cols)s)",
                {**key, "cols": json.dumps(columns or [])},
            )

    def index_columns(self, name: str) -> dict[str, frozenset[str]]:
        """Kind -> the columns the log table's built indexes cover."""
        rows = self.db.read(
            "SELECT kind, columns FROM extractor.log_index_columns WHERE log_table = %(lt)s", {"lt": name}
        ).rows
        return {str(k): frozenset(json.loads(c)) for k, c in rows}

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
        and takes the candidate's template, the others are absorbed and redirect to it (every redirect
        stays one hop). Anything else is `new` with the next T<n> from the log table's counter (never reused).

        A merge writes in an order that keeps every issued ID resolvable after a failure at any step
        (survivor, redirects pointing at the absorbed ID, the absorbed ID's own redirect, and only then
        the delete of the absorbed template), and every step is idempotent: running the same survey again
        finishes the merge. The whole read-modify-write holds a process-wide lock; several server
        processes writing one catalog at the same time are not supported.
        """
        now = _naive_utc(observed_at)
        with _UPSERT_LOCK:
            state = {t.template_id: t for t in self.templates(log_table)}
            merged: dict[str, str] = {}
            items: list[tuple[Template, Literal["new", "known", "generalized"]]] = []
            for c in found:
                first, last = _naive_utc(c.first_seen), _naive_utc(c.last_seen)
                same = next((t for t in state.values() if t.template == c.template), None)
                group = [t for t in state.values() if t is same or full_match(c.regex, t.example)]
                if not group:
                    saved = self._insert(log_table, c, first, last, now)
                    state[saved.template_id] = saved
                    items.append((saved, "new"))
                    continue
                group.sort(key=lambda t: _template_number(t.template_id))
                survivor, absorbed = group[0], group[1:]
                firsts, lasts = _bounds([*group], first, last)
                if not absorbed and same is survivor:
                    saved = replace(survivor, first_seen=firsts, last_seen=lasts, last_estimate=c.estimate, last_estimate_at=now)
                    self._write_template(saved, now)
                    items.append((saved, "known"))
                else:
                    saved = replace(
                        survivor, template=c.template, regex=c.regex, params=_carry_names(survivor.params, list(c.params)),
                        example=c.example, first_seen=firsts, last_seen=lasts, last_estimate=c.estimate, last_estimate_at=now,
                    )
                    self._write_template(saved, now)
                    for gone in absorbed:
                        self._absorb(log_table, gone.template_id, survivor.template_id, now)
                        del state[gone.template_id]
                        for k, v in merged.items():
                            if v == gone.template_id:
                                merged[k] = survivor.template_id
                        merged[gone.template_id] = survivor.template_id
                    items.append((saved, "generalized"))
                state[saved.template_id] = saved
            return UpsertResult(items, merged)

    def _insert(
        self, log_table: str, c: CandidateTemplate, first: datetime | None, last: datetime | None, now: datetime | None
    ) -> Template:
        # One atomic statement reserves the number, so numbers are never reused.
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
        return Template(log_table, tid, c.template, c.regex, list(c.params), c.example, first, last, c.estimate, now)

    def _write_template(self, t: Template, now: datetime | None) -> None:
        self.db.write(
            "UPDATE extractor.templates SET template = %(t)s, regex = %(re)s, params = %(p)s, example = %(ex)s, "
            "first_seen = %(fs)s, last_seen = %(ls)s, last_estimate = %(est)s, last_estimate_at = %(at)s, "
            "updated_at = %(at)s WHERE log_table = %(lt)s AND template_id = %(id)s",
            {
                "t": t.template, "re": t.regex, "p": _params_json(t.params), "ex": t.example, "fs": t.first_seen,
                "ls": t.last_seen, "est": t.last_estimate, "at": now, "lt": t.log_table, "id": t.template_id,
            },
        )

    def _absorb(self, log_table: str, old_id: str, new_id: str, now: datetime | None) -> None:
        """Fold `old_id` into `new_id`. Idempotent; the delete is last, so `old_id` resolves throughout."""
        key = {"lt": log_table, "old": old_id, "new": new_id, "at": now}
        self.db.write(
            "UPDATE extractor.template_redirects SET new_id = %(new)s WHERE log_table = %(lt)s AND new_id = %(old)s", key
        )
        self.db.write("DELETE FROM extractor.template_redirects WHERE log_table = %(lt)s AND old_id = %(old)s", key)
        self.db.write(
            "INSERT INTO extractor.template_redirects (log_table, old_id, new_id, merged_at) "
            "VALUES (%(lt)s, %(old)s, %(new)s, %(at)s)",
            key,
        )
        self.db.write("DELETE FROM extractor.templates WHERE log_table = %(lt)s AND template_id = %(old)s", key)

    def _template_row(self, log_table: str, template_id: str) -> Template | None:
        rows = self.db.read(
            f"SELECT {_TEMPLATE_COLUMNS} FROM extractor.templates WHERE log_table = %(n)s AND template_id = %(id)s",
            {"n": log_table, "id": template_id},
        ).dicts()
        return _template(rows[0]) if rows else None

    def _redirect_target(self, log_table: str, old_id: str) -> str | None:
        rows = self.db.read(
            "SELECT new_id FROM extractor.template_redirects WHERE log_table = %(n)s AND old_id = %(id)s",
            {"n": log_table, "id": old_id},
        ).dicts()
        return str(rows[0]["new_id"]) if rows else None

    def resolve(self, log_table: str, template_id: str) -> Resolved:
        """The live template for an ID, following a merge redirect (one hop by construction)."""
        wanted = template_id.strip()
        live = self._template_row(log_table, wanted)
        if live is not None:
            return Resolved(live, None)
        target_id = self._redirect_target(log_table, wanted)
        target = self._template_row(log_table, target_id) if target_id else None
        if target is not None:
            return Resolved(target, wanted)
        raise UnknownTemplate(template_id, self._closest(log_table, wanted))

    def _closest(self, log_table: str, wanted: str) -> list[str]:
        """Templates the unknown ID may have meant: a differently spelled ID, or whose regex matches it as text."""
        known = self.templates(log_table)
        spelled = re.fullmatch(r"[Tt]\s*0*(\d+)", wanted)
        if spelled:
            canonical = f"T{spelled.group(1)}"
            if any(t.template_id == canonical for t in known):
                return [canonical]
            target = self._redirect_target(log_table, canonical)
            return [target] if target else []
        return [t.template_id for t in known if t.template == wanted or full_match(t.regex, wanted)][:3]

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
