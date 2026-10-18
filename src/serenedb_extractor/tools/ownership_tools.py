"""show_team_ownership and edit_team_ownership: the team-ownership table that maps components (or services) to teams.

show_team_ownership lists the rules, where they came from and, per log table, how many entries each team owns and
which components no rule covers. edit_team_ownership imports a CSV (replacing or merging), sets or removes single
rules, removes a team, exports the rules to a CSV file, or resets to the packaged stand-in.
"""

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from serenedb_extractor import format as fmt
from serenedb_extractor import ownership as own
from serenedb_extractor.catalog.models import LogTable
from serenedb_extractor.context import AppContext
from serenedb_extractor.errors import UserFacingError
from serenedb_extractor.ownership import Rule
from serenedb_extractor.query.filters import Filters, parse_time_range
from serenedb_extractor.setup.sniff import readable
from serenedb_extractor.tools.aggregate import _count_one

ACTIONS = ("import", "set", "remove", "export", "reset")
MODES = ("replace", "merge", "replace_all")
MAX_CSV_BYTES = 5_000_000
SHOWN_CHANGES = 40
SHOWN_UNASSIGNED = 15


# ---- show ------------------------------------------------------------------------------------------


def show_team_ownership(
    ctx: AppContext, log_table: str | None = None, coverage: bool = True, confirmed_cost: str | None = None
) -> str:
    rules = ctx.store.ownership.rules()
    tables = [ctx.store.get_log_table(log_table)] if log_table else ctx.store.list_log_tables()
    if log_table:
        rules = [r for r in rules if r.covers_table(log_table)]
    out = [_summary(rules)]
    history = own.changes(ctx.db)
    if history:
        out.append("Recent changes (newest first):")
        for at, action, source, added, updated, removed in history:
            out.append(f"  {at:%Y-%m-%d %H:%M} UTC {action}: +{added} added, {updated} changed, -{removed} removed ({source or 'no source'})")
    out.append("")
    out += _rule_lines(rules)
    if coverage and tables:
        out.append("")
        out.append("Coverage (exact counts over every entry, unless said otherwise):")
        for lt in tables:
            out += _coverage(ctx, lt, confirmed_cost)
    return "\n".join(out)


def _summary(rules: list[Rule]) -> str:
    if not rules:
        return "There are no team ownership rules: no log table has a team. Import a table with edit_team_ownership."
    teams = sorted({r.team for r in rules})
    by_source: dict[str, int] = {}
    for r in rules:
        by_source[r.source or "unknown"] = by_source.get(r.source or "unknown", 0) + 1
    sources = "; ".join(f"{n} from {s}" for s, n in sorted(by_source.items(), key=lambda kv: -kv[1]))
    line = f"{len(rules)} ownership rules for {len(teams)} teams. Where they come from: {sources}."
    if own.STAND_IN in by_source:
        line += (
            "\nNote: the stand-in rules are a fictional organisation written for this project, not an official "
            "mapping. When you name a team from them, say it comes from the stand-in ownership table."
        )
    return line


def _rule_lines(rules: list[Rule]) -> list[str]:
    out: list[str] = []
    groups: dict[tuple[str, str], dict[str, list[Rule]]] = {}
    for r in rules:
        groups.setdefault((r.log_table, r.role), {}).setdefault(r.team, []).append(r)
    for (table, role), teams in sorted(groups.items()):
        out.append(f"log tables matching '{table}', by {role}:")
        for team, rs in sorted(teams.items()):
            out.append(f"  {team} <- {', '.join(sorted(r.pattern for r in rs))}")
    return out


def _coverage(ctx: AppContext, lt: LogTable, confirmed_cost: str | None) -> list[str]:
    found = ctx.store.ownership.for_table(lt.name, lt.roles.present())
    if found is None:
        roles = [r for r in own.OWNER_ROLES if r in lt.roles.present()]
        why = f"it has {' and '.join(roles)} fields but" if roles else "it has no component or service field, and"
        return [f"  log table {lt.name}: no team ({why} no rule covers it)."]
    role, rules = found
    tr = parse_time_range(None, None, lt.timezone)
    try:
        with readable(f"the source of log table '{lt.name}'"):
            t = _count_one(ctx, lt, tr, Filters(), None, [role], lt.timezone, confirmed_cost)
    except UserFacingError as exc:
        return [f"  log table {lt.name}: coverage not checked ({' '.join(str(exc).split())})"]
    if t.asked:
        return [f"  log table {lt.name}: coverage not checked: TOO EXPENSIVE to count every entry. {t.asked}"]
    if t.total is None:
        return [f"  log table {lt.name}: coverage not checked ({t.note})"]
    exact = t.total.exact
    total = t.total.value or 0.0
    team_n: dict[str, float] = {}
    loose: list[tuple[str, float]] = []
    for key, m in t.groups:
        value = key[0] if key else None
        team = own.team_of(None if value in (None, "None") else value, rules)
        team_n[team] = team_n.get(team, 0.0) + m.value
        if team == own.UNASSIGNED:
            loose.append((str(value), m.value))
    how = "exact" if exact else "estimated from a block sample"
    out = [f"  log table {lt.name} (teams by {role}, {len(t.groups)} distinct values, {_n(total)} entries, {how}):"]
    for team, n in sorted(team_n.items(), key=lambda kv: -kv[1]):
        out.append(f"    {team}: {_n(n)}{_pct(n, total)}")
    if loose:
        loose.sort(key=lambda kv: -kv[1])
        out.append(f"    {len(loose)} {role} value(s) without a team, largest first:")
        for value, n in loose[:SHOWN_UNASSIGNED]:
            out.append(f"      {fmt.shorten(value, 80)}: {_n(n)}")
        if len(loose) > SHOWN_UNASSIGNED:
            out.append(f"      ... and {len(loose) - SHOWN_UNASSIGNED} more")
    else:
        out.append(f"    every {role} value has a team")
    return out


def _n(x: float) -> str:
    return f"{int(round(x)):,}"


def _pct(part: float, whole: float) -> str:
    return f", {100 * part / whole:.1f}%" if whole else ""


# ---- edit ------------------------------------------------------------------------------------------


def edit_team_ownership(
    ctx: AppContext,
    action: str,
    csv_path: str | None = None,
    csv_text: str | None = None,
    mode: str = "replace",
    log_table: str | None = None,
    role: str | None = None,
    rules: list[dict[str, Any]] | None = None,
    team: str | None = None,
    dry_run: bool = False,
) -> str:
    action = (action or "").strip().lower()
    if action not in ACTIONS:
        raise UserFacingError(f"action must be one of {', '.join(ACTIONS)}.")
    if role is not None and role not in own.OWNER_ROLES:
        raise UserFacingError(f"role must be one of {', '.join(own.OWNER_ROLES)}.")
    current = ctx.store.ownership.rules()
    if action == "export":
        return _export(current, csv_path, log_table)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    notes: list[str] = []
    if action == "import":
        if mode not in MODES:
            raise UserFacingError(f"mode must be one of {', '.join(MODES)}.")
        text, name = _csv_input(csv_path, csv_text)
        source = f"imported from {name} on {today}"
        new, notes = own.parse_csv(text, log_table, role, source)
        drop = _replaced(ctx, current, new, mode)
        change = own.plan_change(current, new, drop)
    elif action == "set":
        source = f"set by hand on {today}"
        new = [_rule_from(d, log_table, role, source, need_team=True) for d in rules or []]
        if not new:
            raise UserFacingError('Give the rules to set, e.g. rules=[{"log_table": "bgl", "component": "KERNEL", "team": "Kernel"}].')
        change = own.plan_change(current, new)
    elif action == "remove":
        source = f"removed by hand on {today}"
        drop = [_rule_from(d, log_table, role, source, need_team=False) for d in rules or []]
        if team:
            drop += [r for r in current if r.team.lower() == team.strip().lower() and (not log_table or r.covers_table(log_table))]
            if not any(r.team.lower() == team.strip().lower() for r in current):
                notes.append(f"no rule names the team '{team}'")
        if not drop and not notes:
            raise UserFacingError('Say what to remove: rules=[{"log_table": "bgl", "component": "KERNEL"}] or team="...".')
        missing = [d for d in drop if d.key not in {r.key for r in current}]
        notes += [f"no rule for {d.log_table} {d.role} '{d.pattern}' to remove" for d in missing]
        change = own.plan_change(current, [], drop)
    else:  # reset
        source = own.STAND_IN
        change = own.plan_change(current, own.packaged_rules(), current)
    lines = []
    if change.empty:
        lines.append("Nothing to change: the ownership table already says this.")
    elif dry_run:
        lines.append("Dry run: nothing was changed. Run again with dry_run=False to apply:")
    else:
        own.apply_change(ctx.db, change, action, source)
        ctx.store.ownership.invalidate()
        lines.append(f"Ownership table updated ({action}, {source}):")
    lines += _change_lines(change)
    lines += [f"note: {n}" for n in notes]
    if not change.empty and not dry_run:
        affected = _affected_tables(ctx, change)
        if affected:
            lines.append("")
            lines.append("Coverage after the change (exact counts over every entry, unless said otherwise):")
            for lt in affected:
                lines += _coverage(ctx, lt, None)
        unmatched = sorted({r.log_table for r in change.added if not any(r.covers_table(t.name) for t in ctx.store.list_log_tables())})
        if unmatched:
            lines.append(
                f"note: no log table is named like {', '.join(repr(u) for u in unmatched)} yet; those rules apply once one is "
                "set up with a matching name (or import again with log_table set to the name you use)."
            )
    return "\n".join(lines)


def _csv_input(csv_path: str | None, csv_text: str | None) -> tuple[str, str]:
    if bool(csv_path) == bool(csv_text):
        raise UserFacingError("Give either csv_path (a CSV file on this machine) or csv_text (the CSV itself), not both.")
    if csv_text:
        return csv_text, "pasted CSV"
    path = Path(csv_path or "").expanduser()
    if not path.is_file():
        raise UserFacingError(f"There is no file at {path}.")
    if path.stat().st_size > MAX_CSV_BYTES:
        raise UserFacingError(f"{path.name} is larger than {MAX_CSV_BYTES // 1_000_000} MB; an ownership table should be small.")
    try:
        return path.read_text(encoding="utf-8-sig"), path.name
    except UnicodeDecodeError:
        return path.read_text(encoding="latin-1"), path.name


def _replaced(ctx: AppContext, current: list[Rule], new: list[Rule], mode: str) -> list[Rule]:
    """The current rules an import removes: all (replace_all), none (merge), or those for the log tables the
    imported rules cover (replace), so a file for BGL and OpenStack leaves the rules of other log tables alone."""
    if mode == "merge":
        return []
    if mode == "replace_all":
        return list(current)
    known = [t.name for t in ctx.store.list_log_tables()]
    patterns = {r.log_table for r in new}
    return [r for r in current if any(own.overlaps(r.log_table, p, known) for p in patterns)]


def _rule_from(d: dict[str, Any], log_table: str | None, role: str | None, source: str, need_team: bool) -> Rule:
    if not isinstance(d, dict):
        raise UserFacingError('Each rule is an object like {"log_table": "bgl", "component": "KERNEL", "team": "Kernel"}.')
    low = {own._norm(str(k)): v for k, v in d.items()}
    value_key = next((k for k in ("pattern", "value", "component", "service") if low.get(k)), None)
    table = str(low.get("log_table") or low.get("dataset") or log_table or "").strip()
    r_role = str(low.get("role") or (value_key if value_key in own.OWNER_ROLES else None) or role or "component").lower()
    team = str(low.get("team") or low.get("owner") or "").strip()
    if not table or value_key is None or (need_team and not team):
        need = "log_table, component (or service/pattern)" + (" and team" if need_team else "")
        raise UserFacingError(f"Each rule needs {need}; got {d}.")
    if r_role not in own.OWNER_ROLES:
        raise UserFacingError(f"role must be one of {', '.join(own.OWNER_ROLES)}; got '{r_role}'.")
    area = low.get("area") or low.get("description")
    return Rule(table, r_role, str(low[value_key]).strip(), team, str(area) if area else None, source)


def _change_lines(change: own.Change) -> list[str]:
    items: list[str] = []
    items += [f"  + {r.log_table} {r.role} '{r.pattern}' -> {r.team}" for r in change.added]
    items += [f"  ~ {b.log_table} {b.role} '{b.pattern}': {b.team} -> {a.team}" for b, a in change.updated]
    items += [f"  - {r.log_table} {r.role} '{r.pattern}' (was {r.team})" for r in change.removed]
    head = [f"  {len(change.added)} added, {len(change.updated)} changed, {len(change.removed)} removed"]
    if len(items) > SHOWN_CHANGES:
        return head + items[:SHOWN_CHANGES] + [f"  ... and {len(items) - SHOWN_CHANGES} more"]
    return head + items


def _affected_tables(ctx: AppContext, change: own.Change) -> list[LogTable]:
    touched = [*change.added, *change.removed, *(a for _, a in change.updated)]
    return [lt for lt in ctx.store.list_log_tables() if any(r.covers_table(lt.name) for r in touched)]


def _export(current: list[Rule], csv_path: str | None, log_table: str | None) -> str:
    if not csv_path:
        raise UserFacingError("Give csv_path: the file to write the rules to.")
    rules = [r for r in current if not log_table or r.covers_table(log_table)]
    path = Path(csv_path).expanduser()
    if path.is_dir():
        path = path / "ownership.csv"
    if not path.parent.is_dir():
        raise UserFacingError(f"The folder {path.parent} does not exist.")
    path.write_text(own.to_csv(rules), encoding="utf-8")
    return (
        f"Wrote {len(rules)} ownership rules to {path.resolve()} (columns: {', '.join(own.CSV_COLUMNS)}, source). "
        "Edit it and import it again with edit_team_ownership(action='import', mode='replace')."
    )
