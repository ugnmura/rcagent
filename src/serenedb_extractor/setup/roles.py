"""Field-role detection and validation.

Roles are SQL expressions that later get interpolated into queries, so a stored role is
restricted to an existing column or `<existing column> ->> '<literal>'`.
"""

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
_JSON_PATH = re.compile(r"^(?P<col>\"(?:[^\"]|\"\")+\"|[^\s\"']+)\s*->>\s*'(?P<lit>(?:[^']|'')*)'$")


def is_temporal(type_name: str) -> bool:
    t = type_name.upper()
    return t.startswith("TIMESTAMP") or t == "DATE"


def is_text(type_name: str) -> bool:
    t = type_name.upper()
    return t.startswith("VARCHAR") or t in ("TEXT", "STRING") or t.startswith("CHAR")


def _pick(columns: Sequence[tuple[str, str]], names: tuple[str, ...], taken: set[str], temporal: bool) -> str | None:
    by_lower = {c.lower(): c for c, _ in columns if c not in taken}
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
    columns: Sequence[tuple[str, str]], samples: Mapping[str, Sequence[str]]
) -> tuple[FieldRoles, dict[str, str]]:
    """Propose roles from column names, types and sample values; evidence explains each pick."""
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
    if "message" not in picked:
        text_cols = [c for c, t in cols if is_text(t) and c not in taken]
        if text_cols:
            widest = max(text_cols, key=lambda c: max((len(v) for v in samples.get(c, [])), default=0))
            picked["message"] = widest
            evidence["message"] = f"widest text column '{widest}'"
    if "message" not in picked:
        raise UserFacingError(
            "I could not find a text column to use as the log message. Name one with roles "
            "(for example roles={'message': 'text_column'})."
        )
    if any(c == "file_row_number" for c, _ in columns):
        picked["order"] = "file_row_number"
        evidence["order"] = "the reader's file_row_number position"
    for role, col in picked.items():
        samp = list(dict.fromkeys(v for v in samples.get(col, []) if v))[:3]
        if samp:
            evidence[role] += "; e.g. " + ", ".join(repr(s) for s in samp)
    roles = FieldRoles(**{r: quote_ident(c) for r, c in picked.items()})
    return roles, evidence


def _resolve_column(name: str, columns: Mapping[str, str]) -> str | None:
    if name in columns:
        return name
    lower = [c for c in columns if c.lower() == name.lower()]
    return lower[0] if len(lower) == 1 else None


def validate_role_expr(expr: str, columns: Mapping[str, str]) -> str:
    """Return the storable form of a role expression or raise UserFacingError."""
    text = expr.strip()
    bad = UserFacingError(
        f"'{expr.strip()[:60]}' is not an allowed field. Use the name of an existing column "
        f"(one of: {', '.join(list(columns)[:20])}) or a JSON path like attrs ->> 'key'."
    )
    if not text:
        raise bad
    unquoted = text[1:-1].replace('""', '"') if len(text) > 1 and text[0] == text[-1] == '"' else text
    col = _resolve_column(unquoted, columns)
    if col is not None:
        return quote_ident(col)
    m = _JSON_PATH.match(text)
    if m:
        raw = m.group("col")
        name = raw[1:-1].replace('""', '"') if raw.startswith('"') else raw
        col = _resolve_column(name, columns)
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
        name = m.group(1).replace('""', '"')
        return name if _SIMPLE.match(name) else m.group(0)

    return re.sub(r'^"((?:[^"]|"")+)"', unq, expr)


def role_column(expr: str) -> str | None:
    """The plain column a role refers to (None for a JSON path)."""
    m = re.fullmatch(r'"((?:[^"]|"")+)"', expr)
    return m.group(1).replace('""', '"') if m else None
