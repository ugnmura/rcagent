"""Team ownership: which team owns which component (or service) of a log table.

The mapping lives in `extractor.ownership`. A fresh database gets the packaged `data/ownership.csv`, a
stand-in (a fictional platform organisation written for this project, see the README) until a real table is
imported with edit_team_ownership. Each rule says: in log tables whose name matches `log_table` (a LIKE pattern),
entries whose `role` (component or service) matches `pattern` (case-insensitive LIKE) belong to `team`. The
most specific pattern wins. Every rule records where it came from (`source`), and every change is logged in
`extractor.ownership_changes`; once anything was imported or edited, the stand-in is never added back.

A log table with rules gets a derived `team` role: a CASE expression over that role, so team can be
filtered on and grouped by like any other role. Entries no rule covers are in team "Unassigned".
"""

import csv
import io
import re
import threading
import time
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from importlib import resources
from typing import TYPE_CHECKING, Iterable

from serenedb_extractor.errors import UserFacingError

if TYPE_CHECKING:
    from serenedb_extractor.db import Database

UNASSIGNED = "Unassigned"
OWNER_ROLES = ("component", "service")
STAND_IN = "stand-in (fictional, shipped with serenedb-extractor)"
CSV_COLUMNS = ("log_table", "role", "pattern", "team", "area")

OWNERSHIP_DDL = """CREATE TABLE IF NOT EXISTS extractor.ownership (
        log_table          VARCHAR NOT NULL,
        role               VARCHAR NOT NULL,
        pattern            VARCHAR NOT NULL,
        team               VARCHAR NOT NULL,
        area               VARCHAR,
        source             VARCHAR,
        PRIMARY KEY (log_table, role, pattern)
    )"""

CHANGES_DDL = """CREATE TABLE IF NOT EXISTS extractor.ownership_changes (
        changed_at         TIMESTAMP NOT NULL,
        action             VARCHAR NOT NULL,
        source             VARCHAR,
        added              INTEGER NOT NULL,
        updated            INTEGER NOT NULL,
        removed            INTEGER NOT NULL
    )"""

_CACHE_S = 30.0


@dataclass(frozen=True)
class Rule:
    log_table: str
    role: str
    pattern: str
    team: str
    area: str | None = None
    source: str | None = None

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.log_table.lower(), self.role, self.pattern.lower())

    def covers_table(self, name: str) -> bool:
        return _like(name, self.log_table)


def _like(value: str, pattern: str) -> bool:
    """SQL LIKE (case-insensitive) in Python: % any run, _ one character."""
    import re

    rx = "".join(".*" if c == "%" else "." if c == "_" else re.escape(c) for c in pattern)
    return re.fullmatch(rx, value, re.IGNORECASE | re.DOTALL) is not None


def packaged_rules() -> list[Rule]:
    text = resources.files("serenedb_extractor").joinpath("data/ownership.csv").read_text(encoding="utf-8")
    rows = csv.DictReader(text.splitlines())
    return [
        Rule(r["log_table"], r["role"], r["pattern"], r["team"], r.get("area") or None, STAND_IN) for r in rows
    ]


def upgrade(db: "Database") -> None:
    """Databases made before rules recorded their source get the column (their rules are the stand-in)."""
    try:  # through the writer, which owns the schema (the reader may not have been granted it yet)
        db.write("SELECT source FROM extractor.ownership LIMIT 0")
    except Exception:
        db.write("ALTER TABLE extractor.ownership ADD COLUMN source VARCHAR")
        db.write("UPDATE extractor.ownership SET source = %(s)s WHERE source IS NULL", {"s": STAND_IN})


def seed(db: "Database") -> None:
    """Add the packaged stand-in rules that extractor.ownership lacks, until the first import or edit. After
    that the table is yours: nothing is added back, so an imported table is never mixed with the stand-in."""
    if db.read("SELECT count(*) FROM extractor.ownership_changes WHERE action <> 'stand-in'", {}).rows[0][0]:
        return
    rows = db.read("SELECT log_table, role, pattern FROM extractor.ownership", {}).rows
    have = {Rule(str(r[0]), str(r[1]), str(r[2]), "").key for r in rows}
    missing = [r for r in packaged_rules() if r.key not in have]
    if missing:
        _insert(db, missing)
        log_change(db, "stand-in", STAND_IN, len(missing), 0, 0)


def _insert(db: "Database", rules: list[Rule]) -> None:
    db.copy_rows(
        "extractor.ownership",
        ["log_table", "role", "pattern", "team", "area", "source"],
        [(r.log_table, r.role, r.pattern, r.team, r.area, r.source) for r in rules],
    )


def log_change(db: "Database", action: str, source: str | None, added: int, updated: int, removed: int) -> None:
    db.write(
        "INSERT INTO extractor.ownership_changes (changed_at, action, source, added, updated, removed) "
        "VALUES (%(at)s, %(a)s, %(s)s, %(ad)s, %(u)s, %(r)s)",
        {"at": datetime.now(timezone.utc).replace(tzinfo=None), "a": action, "s": source, "ad": added, "u": updated, "r": removed},
    )


@dataclass
class Change:
    added: list[Rule]
    updated: list[tuple[Rule, Rule]]  # (before, after)
    removed: list[Rule]

    @property
    def empty(self) -> bool:
        return not (self.added or self.updated or self.removed)


def plan_change(current: list[Rule], put: Iterable[Rule], drop: Iterable[Rule] = ()) -> Change:
    """What putting `put` (insert or replace by key) and dropping `drop` (by key) would change."""
    have = {r.key: r for r in current}
    gone = {r.key: have[r.key] for r in drop if r.key in have}
    added: list[Rule] = []
    updated: list[tuple[Rule, Rule]] = []
    seen: set[tuple[str, str, str]] = set()
    for r in put:
        if r.key in seen:
            continue
        seen.add(r.key)
        gone.pop(r.key, None)
        old = have.get(r.key)
        if old is None:
            added.append(r)
        elif (old.team, old.area) != (r.team, r.area):
            updated.append((old, r))
    return Change(added, updated, list(gone.values()))


def apply_change(db: "Database", change: Change, action: str, source: str | None) -> None:
    for r in [*change.removed, *(old for old, _ in change.updated)]:
        db.write(
            "DELETE FROM extractor.ownership WHERE lower(log_table) = %(t)s AND role = %(r)s AND lower(pattern) = %(p)s",
            {"t": r.key[0], "r": r.key[1], "p": r.key[2]},
        )
    put = [*change.added, *(new for _, new in change.updated)]
    if put:
        _insert(db, put)
    log_change(db, action, source, len(change.added), len(change.updated), len(change.removed))


def changes(db: "Database", limit: int = 5) -> list[tuple[datetime, str, str | None, int, int, int]]:
    rows = db.read(
        "SELECT changed_at, action, source, added, updated, removed FROM extractor.ownership_changes "
        "ORDER BY changed_at DESC LIMIT %(n)s",
        {"n": limit},
    ).rows
    return [tuple(r) for r in rows]  # type: ignore[misc]


# ---- CSV ------------------------------------------------------------------------------------------

_TABLE_HEADERS = ("log_table", "dataset", "table", "log", "source_table")
_VALUE_HEADERS = ("pattern", "value", "component", "service", "module", "logger")
_TEAM_HEADERS = ("team", "owner", "owning_team", "team_name", "owner_team")
_AREA_HEADERS = ("area", "description", "notes", "note", "comment")


def _norm(header: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", header.strip().lower()).strip("_")


def _pick(headers: dict[str, str], names: tuple[str, ...]) -> str | None:
    for n in names:
        if n in headers:
            return headers[n]
    return None


def parse_csv(text: str, log_table: str | None, role: str | None, source: str) -> tuple[list[Rule], list[str]]:
    """Rules from CSV text, and notes about rows that were skipped. Headers are matched loosely:
    the log table from log_table/dataset/table (else the `log_table` argument), the value from
    pattern/value/component/service, the team from team/owner, the role from role (else the value
    column's name when it is component or service, else the `role` argument, else component)."""
    text = text.lstrip("\ufeff")
    if not text.strip():
        raise UserFacingError("The CSV is empty.")
    try:
        dialect: type[csv.Dialect] | csv.Dialect = csv.Sniffer().sniff(text.splitlines()[0], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    headers = {_norm(h): h for h in reader.fieldnames or [] if h}
    table_h, value_h = _pick(headers, _TABLE_HEADERS), _pick(headers, _VALUE_HEADERS)
    team_h, area_h, role_h = _pick(headers, _TEAM_HEADERS), _pick(headers, _AREA_HEADERS), headers.get("role")
    found = ", ".join(reader.fieldnames or []) or "none"
    if value_h is None or team_h is None:
        raise UserFacingError(
            "The CSV needs a column naming the component (or service) and one naming the team, e.g. the header "
            f"'dataset,component,team'. Its columns are: {found}."
        )
    if table_h is None and not log_table:
        raise UserFacingError(
            f"The CSV has no log table (or dataset) column (its columns are: {found}); say which log table its "
            "rows are for with log_table."
        )
    default_role = role or (_norm(value_h) if _norm(value_h) in OWNER_ROLES else "component")
    rules: list[Rule] = []
    notes: list[str] = []
    for n, row in enumerate(reader, start=2):
        get = lambda h: (row.get(h) or "").strip() if h else ""  # noqa: E731
        table, value, team = get(table_h) or (log_table or ""), get(value_h), get(team_h)
        r_role = (get(role_h) or default_role).lower()
        if not (table or value or team):
            continue
        if not table or not value or not team:
            missing = [w for w, v in (("log table", table), ("component", value), ("team", team)) if not v]
            notes.append(f"line {n} skipped: no {' or '.join(missing)}")
            continue
        if r_role not in OWNER_ROLES:
            notes.append(f"line {n} skipped: role '{r_role}' is not one of {', '.join(OWNER_ROLES)}")
            continue
        rules.append(Rule(table, r_role, value, team, get(area_h) or None, source))
    if not rules:
        raise UserFacingError("The CSV has no usable rows. " + "; ".join(notes[:5]))
    dupes = len(rules) - len({r.key for r in rules})
    if dupes:
        notes.append(f"{dupes} duplicate row(s) for the same log table and component: the first one is kept")
    return rules, notes


def to_csv(rules: list[Rule]) -> str:
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\n")
    w.writerow([*CSV_COLUMNS, "source"])
    for r in sorted(rules, key=lambda r: (r.log_table, r.role, r.team, r.pattern)):
        w.writerow([r.log_table, r.role, r.pattern, r.team, r.area or "", r.source or ""])
    return out.getvalue()


def overlaps(a: str, b: str, known_tables: list[str]) -> bool:
    """Whether two log-table patterns can apply to the same log table."""
    if a.lower() == b.lower() or _like(a, b) or _like(b, a):
        return True
    return any(_like(t, a) and _like(t, b) for t in known_tables)


def with_source(rules: list[Rule], source: str) -> list[Rule]:
    return [replace(r, source=source) for r in rules]


class Ownership:
    """The rules, read from SereneDB and cached briefly (they change rarely)."""

    def __init__(self, db: "Database | None") -> None:
        self._db = db
        self._lock = threading.Lock()
        self._rules: list[Rule] | None = None
        self._at = 0.0

    def invalidate(self) -> None:
        with self._lock:
            self._rules = None

    def rules(self) -> list[Rule]:
        with self._lock:
            if self._rules is None or time.monotonic() - self._at > _CACHE_S:
                self._rules = self._load()
                self._at = time.monotonic()
            return self._rules

    def _load(self) -> list[Rule]:
        if self._db is None:
            return []
        try:
            rows = self._db.read(
                "SELECT log_table, role, pattern, team, area, source FROM extractor.ownership", {}
            ).dicts()
        except Exception:
            return []
        return [Rule(r["log_table"], r["role"], r["pattern"], r["team"], r["area"], r["source"]) for r in rows]

    def for_table(self, name: str, present_roles: dict[str, str]) -> tuple[str, list[Rule]] | None:
        """(the role the rules match on, the rules) for a log table, or None when no rule applies."""
        rules = [r for r in self.rules() if r.covers_table(name) and r.role in present_roles]
        if not rules:
            return None
        role = max(OWNER_ROLES, key=lambda ro: sum(r.role == ro for r in rules))
        return role, [r for r in rules if r.role == role]


def _literal(text: str) -> str:
    """A string literal left raw like every role expression: `%` is escaped where the role is used (role_sql)."""
    return "'" + text.replace("'", "''") + "'"


def team_expr(role_expression: str, rules: list[Rule]) -> str:
    """CASE over the role's value: the most specific matching pattern's team, else Unassigned.
    Built from literals only, so it can be used anywhere a role expression can."""
    ordered = sorted(rules, key=lambda r: (-len(r.pattern.replace("%", "")), r.pattern))
    whens = " ".join(
        f"WHEN ({role_expression})::varchar ILIKE {_literal(r.pattern)} THEN {_literal(r.team)}" for r in ordered
    )
    return f"(CASE {whens} ELSE {_literal(UNASSIGNED)} END)"


def team_of(value: str | None, rules: list[Rule]) -> str:
    """The team owning one component or service value, by the same precedence as team_expr."""
    if value is None:
        return UNASSIGNED
    for r in sorted(rules, key=lambda r: (-len(r.pattern.replace("%", "")), r.pattern)):
        if _like(value, r.pattern):
            return r.team
    return UNASSIGNED
