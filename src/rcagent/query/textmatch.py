"""The "message contains this text, any case" predicate of search_logs and count_logs.

The meaning is ILIKE '%text%': SereneDB lowercases both sides code point by code point (one code
point to one), then compares. ILIKE is the slow part of a text scan: over TextBench's 60-second S6
window (33 M messages) a count with ILIKE takes 0.64-0.72 s, with a case-insensitive RE2 regexp
0.43-0.48 s, and reading the messages alone 0.30-0.42 s. So a printable-ASCII text is matched with a
regexp that accepts exactly what ILIKE accepts, or, when it can't be exact, at least that, with ILIKE
deciding on the messages it lets through (CASE, so ILIKE only runs on those: S6 0.50 s).

Why the regexp is exact: a message character c matches a text character p under ILIKE when
lower(c) = lower(p); under RE2's (?i) when c is in p's case-folding orbit. For printable ASCII the two
agree on every Unicode code point except: U+0130 (İ), whose lowercase is i but which RE2 does not fold
with i, so every i or I is written as [iİ]; and U+017F (ſ, long s), which RE2 folds with s but whose
lowercase is itself, so a text with an s or S keeps the ILIKE check. (The Kelvin sign U+212A lowercases
to k and RE2 folds it with k anyway; it is listed in k's class all the same.) A match is a run of such
characters, so per character is enough. tests/test_textmatch.py checks this against the server over
all 1,112,063 code points. A non-ASCII text, or one with a control character, is matched with ILIKE alone.
"""

from typing import Any

from rcagent.query.templatematch import _like_pattern

_EXTRA_CASES = {"i": "İ", "k": "K"}  # non-ASCII characters whose lowercase is this ASCII letter
NOT_EXACT = frozenset("sS")  # ASCII characters whose regexp also matches what ILIKE doesn't (U+017F)


def prefilter_regex(text: str) -> str | None:
    """An RE2 pattern matching every message that contains `text` under ILIKE (exactly those, unless
    `text` has a character in NOT_EXACT), or None when `text` is not printable ASCII."""
    if not text or not all(" " <= ch <= "~" for ch in text):
        return None
    parts = []
    for ch in text:
        extra = _EXTRA_CASES.get(ch.lower())
        if extra:
            parts.append(f"[{ch}{extra}]")
        elif ch.isalnum():
            parts.append(ch)
        else:  # any other character as a hex escape, which RE2 reads literally
            parts.append(f"\\x{{{ord(ch):x}}}")
    return "(?i)" + "".join(parts)


def contains_sql(message_sql: str, text: str) -> tuple[str, dict[str, Any]]:
    """`message contains text, any case` (ILIKE semantics) as SQL with its parameters."""
    like = f"({message_sql})::varchar ILIKE %(text_pattern)s ESCAPE '\\'"
    rx = prefilter_regex(text)
    if rx is None:
        return like, {"text_pattern": _like_pattern(text)}
    regexp = f"regexp_matches(({message_sql})::varchar, %(text_regex)s)"
    if not NOT_EXACT.intersection(text):
        return regexp, {"text_regex": rx}
    # CASE, not AND: SereneDB may evaluate an AND's ILIKE on every message (measured: as slow as ILIKE
    # alone on S6), while CASE evaluates THEN only where WHEN held. Both mean regexp AND ILIKE.
    return f"(CASE WHEN {regexp} THEN {like} ELSE false END)", {"text_regex": rx, "text_pattern": _like_pattern(text)}
