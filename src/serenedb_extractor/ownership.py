"""Team ownership: which team owns which component (or service) of a log table.

The mapping lives in `extractor.ownership`, seeded from the packaged `data/ownership.csv` the first time
the schema is created (a fictional platform organisation; see the README). Each rule says: in log tables
whose name matches `log_table` (a LIKE pattern), entries whose `role` (component or service) matches
`pattern` (case-insensitive LIKE) belong to `team`. The most specific pattern wins.

A log table with rules gets a derived `team` role: a CASE expression over that role, so team can be
filtered on and grouped by like any other role. Entries no rule covers are in team "Unassigned".
"""

import csv
import threading
import time
from dataclasses import dataclass
from importlib import resources
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from serenedb_extractor.db import Database

UNASSIGNED = "Unassigned"
OWNER_ROLES = ("component", "service")

OWNERSHIP_DDL = """CREATE TABLE IF NOT EXISTS extractor.ownership (
        log_table          VARCHAR NOT NULL,
        role               VARCHAR NOT NULL,
        pattern            VARCHAR NOT NULL,
        team               VARCHAR NOT NULL,
        area               VARCHAR,
        PRIMARY KEY (log_table, role, pattern)
    )"""

_CACHE_S = 30.0


@dataclass(frozen=True)
class Rule:
    log_table: str
    role: str
    pattern: str
    team: str
    area: str | None = None

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
    return [Rule(r["log_table"], r["role"], r["pattern"], r["team"], r.get("area") or None) for r in rows]


def seed(db: "Database") -> None:
    """Add the packaged rules that extractor.ownership lacks; rules already there (including your edits
    to a packaged rule's team) are never overwritten."""
    have = {
        (r[0], r[1], r[2])
        for r in db.read("SELECT log_table, role, pattern FROM extractor.ownership", {}).rows
    }
    for r in packaged_rules():
        if (r.log_table, r.role, r.pattern) in have:
            continue
        db.write(
            "INSERT INTO extractor.ownership (log_table, role, pattern, team, area) "
            "VALUES (%(t)s, %(r)s, %(p)s, %(team)s, %(a)s)",
            {"t": r.log_table, "r": r.role, "p": r.pattern, "team": r.team, "a": r.area},
        )


class Ownership:
    """The rules, read from SereneDB and cached briefly (they change rarely)."""

    def __init__(self, db: "Database | None") -> None:
        self._db = db
        self._lock = threading.Lock()
        self._rules: list[Rule] | None = None
        self._at = 0.0

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
            rows = self._db.read("SELECT log_table, role, pattern, team, area FROM extractor.ownership", {}).dicts()
        except Exception:
            return []
        return [Rule(r["log_table"], r["role"], r["pattern"], r["team"], r["area"]) for r in rows]

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
