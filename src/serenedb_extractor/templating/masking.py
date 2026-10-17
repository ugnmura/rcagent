"""Generic value masking, identical in Python and in SereneDB SQL.

Patterns use only syntax valid in both RE2 and Python `re` (no lookaround, no
backreferences, no possessive quantifiers) and contain no `%` (psycopg params).
Python runs them with re.ASCII so \\b, \\w, \\d, \\s match RE2's ASCII semantics.
"""

import re
from dataclasses import dataclass

_HEX = "[0-9a-fA-F]"
_DIGIT = "[0-9]"
_LETTER = "[a-fA-F]"


@dataclass(frozen=True)
class MaskRule:
    placeholder: str
    pattern: str
    replacement: str  # may reference group 1 (\1)


def _mixed_hex(min_len: int = 8) -> str:
    """Hex runs of >= min_len chars containing both a digit and a letter a-f.

    RE2 has no lookahead, so enumerate by the length k of the leading digit
    (or letter) run, which a letter (or digit) must follow.
    """
    branches = []
    for lead, other in ((_DIGIT, _LETTER), (_LETTER, _DIGIT)):
        for k in range(1, min_len):
            branches.append(f"{lead}{{{k}}}{other}{_HEX}{{{min_len - 1 - k},}}")
        branches.append(f"{lead}{{{min_len},}}{other}{_HEX}*")
    return "|".join(branches)


_PATH_PREFIX = r"""(^|[\s'"=(\[,])"""

MASK_RULES: tuple[MaskRule, ...] = (
    MaskRule("<URL>", r"""\b[A-Za-z][A-Za-z0-9+.\-]*://[^\s'"<>)\]]+""", "<URL>"),
    MaskRule("<EMAIL>", r"[A-Za-z0-9._+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}", "<EMAIL>"),
    MaskRule(
        "<UUID>",
        rf"\b{_HEX}{{8}}-{_HEX}{{4}}-{_HEX}{{4}}-{_HEX}{{4}}-{_HEX}{{12}}\b",
        "<UUID>",
    ),
    MaskRule("<IP>", r"\b\d{1,3}(?:\.\d{1,3}){3}(?::\d{1,5})?\b", "<IP>"),
    MaskRule("<PATH>", _PATH_PREFIX + r"(?:/[A-Za-z0-9_.@~:+\-]+)+/?", r"\1<PATH>"),
    MaskRule("<HEX>", rf"\b(?:0[xX]{_HEX}+|{_mixed_hex()})\b", "<HEX>"),
    MaskRule("<STR>", r"""\B(?:'[^'\s][^']*'|"[^"\s][^"]*")\B""", "<STR>"),
    MaskRule("<NUM>", r"\b\d+(?:\.\d+)?", "<NUM>"),
)

# Placeholder in a template -> capture regex that matches the original values.
PLACEHOLDER_CAPTURE: dict[str, str] = {
    "<URL>": r"(\S+)",
    "<EMAIL>": r"(\S+@\S+)",
    "<UUID>": r"([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})",
    "<IP>": r"(\d{1,3}(?:\.\d{1,3}){3}(?::\d{1,5})?)",
    "<PATH>": r"(/\S*)",
    "<HEX>": r"(0[xX][0-9a-fA-F]+|[0-9a-fA-F]{8,})",
    "<STR>": r"""('[^']*'|"[^"]*")""",
    "<NUM>": r"(-?\d+(?:\.\d+)?)",
    "<*>": r"(\S+)",
}

_COMPILED = tuple((re.compile(r.pattern, re.ASCII), r.replacement) for r in MASK_RULES)


def mask_py(text: str) -> str:
    for compiled, replacement in _COMPILED:
        text = compiled.sub(replacement, text)
    return text


def _sql_literal(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def mask_sql(expr: str) -> str:
    """A SQL expression masking `expr` (itself a SQL expression) like mask_py."""
    out = expr
    for rule in MASK_RULES:
        out = f"regexp_replace({out}, {_sql_literal(rule.pattern)}, {_sql_literal(rule.replacement)}, 'g')"
    return out
