"""Is a token Drain wants to wildcard a constant word or a value?

Helpers for the rule "only generalise a position to `<*>` when its values are genuinely
variable": a plain word (`Paused`, `privileged`, `dcbf`) or a direction (`x+`, `z-`) is part of
the message's wording, so a few distinct such words mean distinct events, not a parameter.
Hardware logs pad a key with dots up to a fixed column before its value
(`illegal instruction......0`, `icache prefetch depth....................0`); the word is read
without that padding and value, else the padding width alone makes every key look variable.
"""

import re

# word + dot padding + its value: 2+ dots with an optional value (`instruction......<NUM>`,
# `key...`), or one dot before a number (`touch.<NUM>`, `core.<NUM>`); never `file.map`
_PADDED = re.compile(r"(.*?[^.])(?:\.{2,}(?:<[A-Z]+>|[0-9]+)?|\.(?:<[A-Z]+>|[0-9]+))")
# a plain word, optionally signed like a torus direction (`x+`, `z-`), with edge punctuation
# (a leading quote too: the `"GET` of a quoted request line is the word GET)
_WORD = re.compile(r"[\"'(\[]?([A-Za-z][A-Za-z_]*[+\-]?)[)\],;:.\"']?")
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
    if m is None or m.group(1).rstrip("+-") in _CALENDAR:
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
