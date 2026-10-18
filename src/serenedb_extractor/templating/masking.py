"""Generic value masking, identical in Python and in SereneDB SQL.

Patterns use only syntax valid in both RE2 and Python `re` (no lookaround, no
backreferences, no possessive quantifiers) and contain no `%` (psycopg params).
Python runs them with re.ASCII so \\b, \\w, \\d match RE2's ASCII semantics.
"""

import re
from dataclasses import dataclass

_HEX = "[0-9a-fA-F]"
_DIGIT = "[0-9]"
_HEX_LETTER = "[a-fA-F]"
# RE2's \s lacks \v while Python's ASCII \s has it, so never use \s in rules.
_WS = " \\t\\n\\r\\f\\v"
# A run of ASCII whitespace as a regex fragment, identical in RE2 and Python.
WHITESPACE_RUN = f"[{_WS}]+"
# Optional ASCII whitespace: what a template allows at the edges of a message (Drain strips it).
EDGE_WHITESPACE = f"[{_WS}]*"


@dataclass(frozen=True)
class MaskRule:
    placeholder: str
    regex: str  # replaces matches; may use group 1 (\1) in `replacement`
    replacement: str
    capture: str  # matches an original value of this kind inside a template regex


def _mixed_hex() -> str:
    """Hex runs of >= 8 chars containing both a digit and a letter a-f.

    RE2 has no lookahead, so enumerate by the length k of the leading digit
    (or letter) run, which a letter (or digit) must follow.
    """
    branches = []
    for lead, other in ((_DIGIT, _HEX_LETTER), (_HEX_LETTER, _DIGIT)):
        for k in range(1, 8):
            branches.append(f"{lead}{{{k}}}{other}{_HEX}{{{7 - k},}}")
        branches.append(f"{lead}{{8,}}{other}{_HEX}*")
    return "|".join(branches)


_URL = rf"""[A-Za-z][A-Za-z0-9+.\-]*://[^{_WS}'"<>)\]]+"""
_EMAIL = r"[A-Za-z0-9._+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}"
_UUID = rf"{_HEX}{{8}}-{_HEX}{{4}}-{_HEX}{{4}}-{_HEX}{{4}}-{_HEX}{{12}}"
_IP_ONE = r"\d{1,3}(?:\.\d{1,3}){3}(?::\d{1,5})?"
# A comma-separated list of addresses (a forwarded-for chain) is one value, whatever its length.
_IP = rf"{_IP_ONE}(?:,{_IP_ONE})*"
_PATH = r"(?:/[A-Za-z0-9_.@~:+\-]+)+/?"
_PATH_PREFIX = rf"""(^|[{_WS}'"=(\[,])"""
_HEXVAL = rf"0[xX]{_HEX}+|{_mixed_hex()}"
# Only whitespace-free quoted values; multi-word quotes are left to other rules.
_STR = rf'''\'[^{_WS}\']+\'|"[^{_WS}"]+"'''
_NUM = r"\d+(?:\.\d+)?"

MASK_RULES: tuple[MaskRule, ...] = (
    MaskRule("<URL>", rf"\b{_URL}", "<URL>", f"({_URL})"),
    MaskRule("<EMAIL>", _EMAIL, "<EMAIL>", f"({_EMAIL})"),
    # A path before UUIDs and IPs, so an id inside a path stays part of the one path value.
    MaskRule("<PATH>", _PATH_PREFIX + _PATH, r"\1<PATH>", f"({_PATH})"),
    MaskRule("<UUID>", rf"\b{_UUID}\b", "<UUID>", f"({_UUID})"),
    MaskRule("<IP>", rf"\b{_IP}\b", "<IP>", f"({_IP})"),
    MaskRule("<HEX>", rf"\b(?:{_HEXVAL})\b", "<HEX>", f"({_HEXVAL})"),
    MaskRule("<STR>", rf"\B(?:{_STR})\B", "<STR>", f"({_STR})"),
    MaskRule("<NUM>", rf"\b{_NUM}", "<NUM>", f"(-?{_NUM})"),
)

# Placeholder in a template -> capture regex that matches the original values.
PLACEHOLDER_CAPTURE: dict[str, str] = {r.placeholder: r.capture for r in MASK_RULES} | {
    "<*>": r"(\S+)"
}

def placeholder_kind(placeholder: str) -> str:
    """`<NUM>` -> `num`; Drain's `<*>` -> `any`."""
    return "any" if placeholder == "<*>" else placeholder[1:-1].lower()


_COMPILED = tuple((re.compile(r.regex, re.ASCII), r.replacement) for r in MASK_RULES)


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
        out = f"regexp_replace({out}, {_sql_literal(rule.regex)}, {_sql_literal(rule.replacement)}, 'g')"
    return out
