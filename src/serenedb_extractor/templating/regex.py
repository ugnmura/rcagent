"""Compile a template (text with placeholders) into an anchored regex.

The regex has one capture group per placeholder and uses only syntax valid in
both RE2 and Python `re`: literal text is escaped by hand (never with
re.escape) and whitespace runs become `\\s+`.
"""

import re
from dataclasses import dataclass

from serenedb_extractor.catalog.models import Param
from serenedb_extractor.templating.masking import PLACEHOLDER_CAPTURE

MAX_FIXED_WORDS = 3
MIN_FIXED_WORD_LEN = 4

_PLACEHOLDER = re.compile("|".join(re.escape(p) for p in PLACEHOLDER_CAPTURE))
_WHITESPACE = re.compile(r"\s+")
_META = frozenset("\\.+*?()|[]{}^$")
_KEY = re.compile(r"([A-Za-z_][A-Za-z0-9_.\-]*)[=:]$")
_WORD = re.compile(r"[A-Za-z]+$")
_OPENERS = " \t\r\n\f\v'\"([{"


@dataclass(frozen=True)
class CompiledTemplate:
    regex: str
    params: tuple[Param, ...]
    fixed_words: tuple[str, ...]


def _escape(literal: str) -> str:
    out = []
    for piece in re.split(r"(\s+)", literal):
        if not piece:
            continue
        if piece.isspace():
            out.append(r"\s+")
        else:
            out.append("".join("\\" + c if c in _META else c for c in piece))
    return "".join(out)


def _label(preceding: str) -> str | None:
    """`key=` / `key:` before the placeholder, else the preceding plain word."""
    parts = preceding.rstrip(_OPENERS).split()
    if not parts:
        return None
    token = parts[-1]
    if key := _KEY.fullmatch(token):
        return key.group(1)
    if _WORD.fullmatch(token):
        return token
    return None


def _unique(name: str, taken: set[str]) -> str:
    candidate, n = name, 1
    while candidate in taken:
        n += 1
        candidate = f"{name}_{n}"
    taken.add(candidate)
    return candidate


def _fixed_words(literals: list[str]) -> tuple[str, ...]:
    seen: dict[str, None] = {}
    for literal in literals:
        fragment = _WHITESPACE.sub(" ", literal).strip()
        if len(fragment) >= MIN_FIXED_WORD_LEN:
            seen.setdefault(fragment)
    longest_first = sorted(seen, key=len, reverse=True)  # stable: ties keep order
    return tuple(longest_first[:MAX_FIXED_WORDS])


def compile_template(template: str) -> CompiledTemplate:
    parts: list[str] = []
    params: list[Param] = []
    literals: list[str] = []
    taken: set[str] = set()
    last = 0
    for match in _PLACEHOLDER.finditer(template):
        literal = template[last : match.start()]
        literals.append(literal)
        parts.append(_escape(literal))
        placeholder = match.group()
        parts.append(PLACEHOLDER_CAPTURE[placeholder])
        kind = "any" if placeholder == "<*>" else placeholder[1:-1].lower()
        pos = len(params) + 1
        name = _label(literal) or f"{kind}_{pos}"
        params.append(Param(pos, _unique(name, taken), kind))
        last = match.end()
    tail = template[last:]
    literals.append(tail)
    parts.append(_escape(tail))
    return CompiledTemplate(
        regex="^" + "".join(parts) + "$",
        params=tuple(params),
        fixed_words=_fixed_words(literals),
    )
