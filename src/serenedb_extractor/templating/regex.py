"""Compile a template (text with placeholders) into an anchored regex.

The regex has one capture group per placeholder and uses only syntax valid in
both RE2 and Python `re`: literal text is escaped by hand (never with
re.escape) and whitespace runs become `\\s+`.
"""

import re
from dataclasses import dataclass

from serenedb_extractor.catalog.models import Param
from serenedb_extractor.templating.masking import (
    PLACEHOLDER_CAPTURE,
    WHITESPACE_RUN,
    placeholder_kind,
)

MAX_FIXED_WORDS = 3
MIN_FIXED_WORD_LEN = 4

_PLACEHOLDER = re.compile("|".join(re.escape(p) for p in PLACEHOLDER_CAPTURE))
_ASCII_WS = re.compile(WHITESPACE_RUN)
_META = frozenset("\\.+*?()|[]{}^$")
_KEY = re.compile(r"([A-Za-z_][A-Za-z0-9_.\-]*)[=:]$")
_WORD = re.compile(r"[A-Za-z]+$")
_OPENERS = " \t\r\n\f\v'\"([{"
_NAME_JUNK = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True)
class CompiledTemplate:
    regex: str
    params: tuple[Param, ...]
    fixed_words: tuple[str, ...]


def _escape(literal: str) -> str:
    out = []
    pieces = _ASCII_WS.split(literal)
    for i, piece in enumerate(pieces):
        if i:
            out.append(WHITESPACE_RUN)
        out.append("".join("\\" + c if c in _META else c for c in piece))
    return "".join(out)


def _label(preceding: str) -> str | None:
    """`key=` / `key:` before the placeholder, else the preceding plain word.

    Returned as a lower-case identifier `[a-z][a-z0-9_]*`, or None.
    """
    parts = preceding.rstrip(_OPENERS).split()
    if not parts:
        return None
    token = parts[-1]
    if key := _KEY.fullmatch(token):
        raw = key.group(1)
    elif _WORD.fullmatch(token):
        raw = token
    else:
        return None
    name = _NAME_JUNK.sub("_", raw.lower()).strip("_")
    return name if name and name[0].isalpha() else None


def _unique(name: str, taken: set[str]) -> str:
    candidate, n = name, 1
    while candidate in taken:
        n += 1
        candidate = f"{name}_{n}"
    taken.add(candidate)
    return candidate


def _safe_tokens(literal: str, after_placeholder: bool, before_placeholder: bool) -> list[str]:
    """Whitespace-free runs lying wholly inside the literal.

    A run touching a placeholder is dropped: the placeholder's value could
    extend it, so it need not appear in a matching line.
    """
    pieces = _ASCII_WS.split(literal)
    if after_placeholder and pieces[0]:
        pieces[0] = ""
    if before_placeholder and pieces[-1]:
        pieces[-1] = ""
    return [p for p in pieces if p]


def _fixed_words(tokens: list[str]) -> tuple[str, ...]:
    """Longest first; ties keep first appearance; >= 4 chars; max 3; deduped."""
    seen = dict.fromkeys(t for t in tokens if len(t) >= MIN_FIXED_WORD_LEN)
    return tuple(sorted(seen, key=len, reverse=True)[:MAX_FIXED_WORDS])


def compile_template(template: str) -> CompiledTemplate:
    parts: list[str] = []
    params: list[Param] = []
    tokens: list[str] = []
    taken: set[str] = set()
    last = 0
    for match in _PLACEHOLDER.finditer(template):
        literal = template[last : match.start()]
        tokens += _safe_tokens(literal, last > 0, True)
        parts.append(_escape(literal))
        placeholder = match.group()
        parts.append(PLACEHOLDER_CAPTURE[placeholder])
        kind = placeholder_kind(placeholder)
        pos = len(params) + 1
        name = _label(literal) or f"{kind}_{pos}"
        params.append(Param(pos, _unique(name, taken), kind))
        last = match.end()
    tail = template[last:]
    tokens += _safe_tokens(tail, last > 0, False)
    parts.append(_escape(tail))
    return CompiledTemplate(
        regex="^" + "".join(parts) + "$",
        params=tuple(params),
        fixed_words=_fixed_words(tokens),
    )
