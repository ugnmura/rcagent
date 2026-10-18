"""Is a token Drain wants to wildcard a constant word or a value?

Helpers for the rule "only generalise a position to `<*>` when its values are genuinely
variable": a plain word (`Paused`, `privileged`, `dcbf`, `+infinity`, `SOCKS5`) or a direction
(`x+`, `z-`) is part of the message's wording, so a few distinct such words mean distinct events,
not a parameter. A word-like value is not: one capital letter (`Y coordinate`, `Port (C)`), a time
zone between a clock time and a year (`PDT` / `PST`).
Hardware logs pad a key with dots up to a fixed column before its value
(`illegal instruction......0`, `icache prefetch depth....................0`); the word is read
without that padding and value, else the padding width alone makes every key look variable.
"""

import re
from collections.abc import Iterable

from rcagent.templating.masking import LETTERS, LIST, LIST_PLACEHOLDERS, VALUES

# word + dot padding + its value: 2+ dots with an optional value (`instruction......<NUM>`,
# `key...`), or one dot before a number (`touch.<NUM>`, `core.<NUM>`); never `file.map`
_PADDED = re.compile(r"(.*?[^.])(?:\.{2,}(?:<[A-Z]+>|[0-9]+)?|\.(?:<[A-Z]+>|[0-9]+))")
# A plain word with edge punctuation (a leading quote too: the `"GET` of a quoted request line is
# the word GET). The word may be signed (`+infinity`, a torus direction `x+`), joined by hyphens
# (`non-crc`, `job-jar`), or an all-capitals name ending in one digit (`SOCKS5`, `IPV6`, `HTTP2`);
# a lowercase stem with a digit is a device or host (`eth0`, `sit0`, `sda1`, `nagios1`), and more
# digits or one letter before them make an id (`bglio136`, `an14`, `J05`, `C1`).
_WORD = re.compile(
    r"[\"'(\[]?"
    r"([+\-]?[A-Za-z][A-Za-z_]*(?:-[A-Za-z][A-Za-z_]*)*[+\-]?|[A-Z]{2,}[0-9])"
    r"[)\],;:.\"']?"
)
# One capital letter is a value that spells like a word: it names an axis, port or unit
# (`Y coordinate`, `Port (C)`, `wanted: A B C`), so a few different ones are the same event about a
# different place, not different events. A signed letter (`x+`, `z-`) stays wording: a torus
# direction names the link the event is about.
_LETTER_VALUE = re.compile(r"[A-Z]")
# Calendar names inside messages (`status=M Sat Sep 17 ...`) are timestamp parts, not wording.
_CALENDAR = frozenset(
    "Mon Tue Wed Thu Fri Sat Sun Monday Tuesday Wednesday Thursday Friday Saturday Sunday "
    "Jan Feb Mar Apr May Jun Jul Aug Sep Sept Oct Nov Dec January February March April June July "
    "August September October November December".split()
)


def word_core(token: str) -> str:
    """`token` without trailing dot padding and the value after it: `dcbf.........<NUM>` -> `dcbf`."""
    m = _PADDED.fullmatch(token)
    return token if m is None else m.group(1)


def constant_word(token: str) -> str | None:
    """The word a token spells when it is message wording, else None (a value: digits, hex,
    placeholders, paths, ids, calendar names).

    `privileged` -> `privileged`; `instruction......<NUM>` -> `instruction`; `x+` -> `x+`;
    `Connection` -> `Connection`; `bglio136`, `<NUM>`, `J05`, `Sat` -> None."""
    m = _WORD.fullmatch(word_core(token))
    if m is None or m.group(1).strip("+-") in _CALENDAR or _LETTER_VALUE.fullmatch(m.group(1)):
        return None
    return m.group(1)


# Units of measure: after a number they say how big the value is (`<NUM> KB` / `<NUM> MB`,
# `took <NUM> sec.` / `secs.`), so the unit varies with the value and is part of it, not the event.
_UNITS = frozenset(
    "b kb mb gb tb pb kib mib gib tib byte bytes bit bits kbit mbit gbit "
    "ns us ms s sec secs second seconds min mins minute minutes h hr hrs hour hours day days "
    "hz khz mhz ghz".split()
)
# The word naming the value that follows it: `session opened for user cyrus`, `Name: StateSnapshots`.
# A few different words after such a label are different users / hosts / names, not different events.
_LABELS = frozenset(
    "user users username login account owner name host hostname node process".split()
)
_ENDS_IN_NUMBER = re.compile(r".*(?:<NUM>|[0-9])[(\[]?$")


def unit_after_number(previous: str, token: str) -> bool:
    """`token` is a unit of measure right after a number (`<NUM> KB)`, `took <NUM> secs.`)."""
    word = constant_word(token)
    return (
        word is not None
        and word.lower() in _UNITS
        and _ENDS_IN_NUMBER.fullmatch(previous) is not None
    )


def names_a_value(previous: str) -> bool:
    """`previous` is a label word (`user`, `Name:`) whose next token is the labelled value."""
    word = constant_word(previous)
    return word is not None and word.lower() in _LABELS


# A full clock time (`21:52:10`, `<NUM>:<NUM>:<NUM>`) followed by an all-capitals word and a year is
# a timestamp with its time zone (`14:23:01 EST 2005`, `<NUM>:<NUM>:<NUM> PDT <NUM>`): the zone
# changes with the season or host, not with the event. Without the seconds (`host:port`, `10:05`) or
# the year after it (`<clock> ERROR: ...`, `AM` / `PM`), the word may be wording.
_CLOCK = re.compile(r"(?:<NUM>|[0-9]{1,2}):(?:<NUM>|[0-9]{2}):(?:<NUM>|[0-9]{2}(?:\.[0-9]+)?)")
_ZONE = re.compile(r"[A-Z]{2,5}")
_YEAR = re.compile(r"<NUM>|[0-9]{4}")


def zone_after_time(previous: str, token: str, following: str) -> bool:
    """`token` is a time zone between a clock time and a year (`<NUM>:<NUM>:<NUM> PDT <NUM>`)."""
    return (
        _ZONE.fullmatch(token) is not None
        and _CLOCK.fullmatch(previous) is not None
        and _YEAR.fullmatch(following) is not None
    )


# A list item: a bare placeholder (`<NUM>`, `<HEX>`) or one letter, capital or signed (`A`, `X+`, `z-`).
_VALUE_ITEM = re.compile(r"<[A-Z]+>")
_LETTER_ITEM = re.compile(r"[A-Z][+\-]?|[a-z][+\-]")
MIN_LIST_ITEMS = 2


def _list_of(token: str) -> str | None:
    """The list placeholder a run of items like `token` collapses to, or None if it is no list item."""
    if token in LIST_PLACEHOLDERS:
        return token
    if _VALUE_ITEM.fullmatch(token):
        return VALUES
    if _LETTER_ITEM.fullmatch(token):
        return LETTERS
    return None


def collapse_lists(tokens: list[str]) -> list[str]:
    """Each run of MIN_LIST_ITEMS+ list items of one kind as one list placeholder (`<VALUES>`, `<LETTERS>`).

    A list's length varies with its value (`rows [ <NUM> <NUM> <NUM> <NUM> ]` / eight rows,
    `wanted: A B C X+ X- got: A C X+`), and Drain only compares messages of one length, so without
    this each length would be its own template. `x+` alone between words stays wording.
    """
    out: list[str] = []
    i = 0
    while i < len(tokens):
        kind = _list_of(tokens[i])
        j = i + 1
        while kind is not None and j < len(tokens) and _list_of(tokens[j]) == kind:
            j += 1
        if kind is not None and j - i >= MIN_LIST_ITEMS:
            out.append(kind)
        else:
            out += tokens[i:j]
        i = j
    return out


def list_covering(tokens: Iterable[str]) -> str | None:
    """The list placeholder matching every one of `tokens` (values at one template position) when one
    of them is a list, else None: a single-token `<*>` there would not match the longer lists."""
    tokens = list(tokens)
    if not any(t in LIST_PLACEHOLDERS for t in tokens):
        return None
    kinds = {_list_of(t) for t in tokens}
    if len(kinds) == 1:
        return next(iter(kinds))
    return LIST
