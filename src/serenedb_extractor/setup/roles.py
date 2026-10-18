"""Field-role detection and validation.

Roles are SQL expressions that later get interpolated into queries, so a stored role is
restricted to an existing column or `<existing column> ->> '<literal>'`.
"""

import json
import re
from collections.abc import Mapping, Sequence

from serenedb_extractor.catalog.models import ROLE_FIELDS, FieldRoles
from serenedb_extractor.db import quote_ident
from serenedb_extractor.errors import UserFacingError

HELPER_COLUMNS = ("filename", "file_row_number")

# OpenTelemetry names first, then the common ones (matched case-insensitively, whole name).
CANDIDATES: dict[str, tuple[str, ...]] = {
    "timestamp": ("timestamp", "ts", "time", "@timestamp"),
    "message": ("body", "message", "msg", "log"),
    "level": ("severitytext", "level", "lvl", "severity"),
    "service": ("servicename", "service", "app"),
    "host": ("host", "hostname", "node", "pod"),
    "component": ("component", "logger", "module"),
    "trace": ("traceid", "trace_id", "request_id", "req_id"),
}
_SIMPLE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_QUOTED = re.compile(r'^"((?:[^"]|"")+)"$')
_JSON_PATH = re.compile(r"^(?P<col>\"(?:[^\"]|\"\")+\"|[^\s\"']+)\s*->>\s*'(?P<lit>(?:[^']|'')*)'$")
_ROLE_ORDER = ("timestamp", "message", "level", "service", "host", "component", "trace", "order")


def unquote_ident(text: str) -> str:
    """`"a""b"` -> `a"b`; text that is not a quoted identifier is returned unchanged."""
    m = _QUOTED.match(text)
    return m.group(1).replace('""', '"') if m else text


def resolve_column(name: str, columns: Mapping[str, str]) -> str | None:
    """The column called `name`: exact match first, then a unique case-insensitive one."""
    if name in columns:
        return name
    ci = [c for c in columns if c.lower() == name.lower()]
    return ci[0] if len(ci) == 1 else None


def is_temporal(type_name: str) -> bool:
    t = type_name.upper()
    return t.startswith("TIMESTAMP") or t == "DATE"


def is_text(type_name: str) -> bool:
    t = type_name.upper()
    return t.startswith("VARCHAR") or t in ("TEXT", "STRING") or t.startswith("CHAR")


_NESTED_TYPE = re.compile(r"^(MAP|STRUCT|UNION|JSON)\b|\[\]$|^LIST\b", re.I)


def is_nested(type_name: str) -> bool:
    """A struct, map, list or JSON column: it holds fields, not one value to show or filter on."""
    return bool(_NESTED_TYPE.search(type_name.strip()))


def _split_top(text: str) -> list[str]:
    """Split on commas outside brackets and double quotes."""
    parts, depth, quoted, cur = [], 0, False, ""
    for ch in text:
        if ch == '"':
            quoted = not quoted
        elif not quoted and ch in "([":
            depth += 1
        elif not quoted and ch in ")]":
            depth -= 1
        elif not quoted and depth == 0 and ch == ",":
            parts.append(cur.strip())
            cur = ""
            continue
        cur += ch
    return parts + ([cur.strip()] if cur.strip() else [])


def struct_fields(type_name: str) -> list[tuple[str, str]]:
    """(name, type) of the top-level fields of a STRUCT(...) type; [] for any other type."""
    t = type_name.strip()
    if not t.upper().startswith("STRUCT(") or not t.endswith(")"):
        return []
    out = []
    for part in _split_top(t[len("STRUCT(") : -1]):
        m = re.match(r'^("(?:[^"]|"")+"|\S+)\s+(.+)$', part)
        if m:
            out.append((unquote_ident(m.group(1)), m.group(2).strip()))
    return out


def _json_objects(values: Sequence[str]) -> list[dict[str, object]]:
    out = []
    for v in values:
        try:
            obj = json.loads(v)
        except (TypeError, ValueError):
            continue
        if isinstance(obj, dict):
            out.append(obj)
    return out


def _nested_fields(
    columns: Sequence[tuple[str, str]], samples: Mapping[str, Sequence[str]]
) -> dict[tuple[str, str], list[str]]:
    """{(column, field): sample values} for the text fields inside struct and JSON columns. A struct's fields come
    from its type, a JSON or map column's from the sample entries (shown as JSON text)."""
    out: dict[tuple[str, str], list[str]] = {}
    for col, typ in columns:
        if not is_nested(typ):
            continue
        objs = _json_objects(samples.get(col, []))
        fields = struct_fields(typ)
        if fields:
            names = [f for f, ft in fields if is_text(ft) or ft.upper() == "JSON"]
        else:
            names = list(dict.fromkeys(k for o in objs for k, v in o.items() if isinstance(v, str)))
        for name in names:
            out[(col, name)] = [str(o[name]) for o in objs if isinstance(o.get(name), str)]
    return out


def _json_path(col: str, field: str) -> str:
    return f"{quote_ident(col)} ->> '{field.replace(chr(39), chr(39) * 2)}'"


def _pick(columns: Sequence[tuple[str, str]], names: tuple[str, ...], taken: set[str], temporal: bool) -> str | None:
    by_lower = {c.lower(): c for c, t in columns if c not in taken and not is_nested(t)}
    types = dict(columns)
    for n in names:
        col = by_lower.get(n)
        if col is None:
            continue
        if temporal and not is_temporal(types[col]):
            continue
        return col
    return None


def propose_roles(
    columns: Sequence[tuple[str, str]],
    samples: Mapping[str, Sequence[str]],
    given: Mapping[str, str | None] | None = None,
) -> tuple[FieldRoles, dict[str, str]]:
    """Propose roles from column names, types and sample values; evidence explains each pick.

    `given` holds validated, storable expressions from the caller; they win over the proposal
    (None clears a role), and a given message means the message need not be guessable.
    """
    given = given or {}
    cols = [(c, t) for c, t in columns if c not in HELPER_COLUMNS]
    taken: set[str] = set()
    picked: dict[str, str] = {}
    evidence: dict[str, str] = {}
    for role in ("timestamp", "message", "level", "service", "host", "component", "trace"):
        col = _pick(cols, CANDIDATES[role], taken, temporal=role == "timestamp")
        if col is not None:
            taken.add(col)
            picked[role] = col
            evidence[role] = f"column name '{col}'"
    # Fields inside struct or JSON columns, e.g. {"log": {"level": ..., "msg": ...}}: used as JSON paths
    # (log ->> 'msg') for the roles no plain column took.
    nested = _nested_fields(cols, samples)
    paths: dict[str, str] = {}
    for role in ("message", "level", "service", "host", "component", "trace"):
        if role in picked:
            continue
        free = [k for k in nested if _json_path(*k) not in paths.values()]
        hit = next((k for want in CANDIDATES[role] for k in free if k[1].lower() == want), None)
        if hit is not None:
            paths[role] = _json_path(*hit)
            ex = list(dict.fromkeys(v[:80] for v in nested[hit] if v))[:3]
            evidence[role] = f"field '{hit[1]}' inside column '{hit[0]}'" + (
                "; e.g. " + ", ".join(repr(v) for v in ex) if ex else ""
            )
    if "message" not in picked and "message" not in paths and not given.get("message"):
        text_cols = [c for c, t in cols if is_text(t) and c not in taken]
        if text_cols:
            widest = max(text_cols, key=lambda c: max((len(v) for v in samples.get(c, [])), default=0))
            picked["message"] = widest
            evidence["message"] = f"widest text column '{widest}'"
    if "message" not in picked and "message" not in paths and not given.get("message"):
        raise UserFacingError(
            "I could not find a text column to use as the log message. Name one with roles "
            "(for example roles={'message': 'text_column'})."
        )
    if any(c == "file_row_number" for c, _ in columns):
        picked["order"] = "file_row_number"
        evidence["order"] = (
            "the reader's file_row_number, a position that keeps the file's order (for CSV a position in the file, "
            "not a row number)"
        )
    for role, col in picked.items():
        samp = list(dict.fromkeys(v for v in samples.get(col, []) if v))[:3]
        if samp:
            evidence[role] += "; e.g. " + ", ".join(repr(s) for s in samp)
    stored: dict[str, str | None] = {r: quote_ident(c) for r, c in picked.items()}
    stored.update(paths)
    for role, expr in given.items():
        stored[role] = expr
        evidence[role] = "given by you" if expr is not None else "removed by you"
    return FieldRoles(**{"message": "", **stored}), evidence  # type: ignore[arg-type]


def validate_role_expr(expr: str, columns: Mapping[str, str]) -> str:
    """Return the storable form of a role expression or raise UserFacingError."""
    text = expr.strip()
    bad = UserFacingError(
        f"'{expr.strip()[:60]}' is not an allowed field. Use the name of an existing column "
        f"(one of: {', '.join(list(columns)[:20])}) or a JSON path like attrs ->> 'key'."
    )
    if not text:
        raise bad
    col = resolve_column(unquote_ident(text), columns)
    if col is not None:
        return quote_ident(col)
    m = _JSON_PATH.match(text)
    if m:
        raw = m.group("col")
        col = resolve_column(unquote_ident(raw), columns)
        if col is not None:
            return f"{quote_ident(col)} ->> '{m.group('lit')}'"
    raise bad


def validate_roles(
    given: Mapping[str, str | None], columns: Mapping[str, str]
) -> dict[str, str | None]:
    """Validate a user-supplied {role: expression}; None clears a role."""
    out: dict[str, str | None] = {}
    for role, expr in given.items():
        key = role.strip().lower()
        if key not in ROLE_FIELDS:
            raise UserFacingError(f"'{role}' is not a field role. Roles are: {', '.join(ROLE_FIELDS)}.")
        if expr is None or not str(expr).strip() or str(expr).strip().lower() in ("absent", "none"):
            if key == "message":
                raise UserFacingError("The message role cannot be removed: every log table needs one.")
            out[key] = None
        else:
            out[key] = validate_role_expr(str(expr), columns)
    return out


def display_role(expr: str | None) -> str:
    """Show a stored role without identifier quotes when the identifier is simple (ruling R1)."""
    if expr is None:
        return "absent"

    def unq(m: re.Match[str]) -> str:
        name = unquote_ident(m.group(0))
        return name if _SIMPLE.match(name) else m.group(0)

    return re.sub(r'^"(?:[^"]|"")+"', unq, expr)


def role_lines(roles: FieldRoles, indent: str = "  ") -> list[str]:
    """One line per role, absent ones listed as absent."""
    return [f"{indent}{r}: {display_role(getattr(roles, r))}" for r in _ROLE_ORDER]


def role_column(expr: str) -> str | None:
    """The plain column a role refers to (None for a JSON path)."""
    return unquote_ident(expr) if _QUOTED.match(expr) else None
