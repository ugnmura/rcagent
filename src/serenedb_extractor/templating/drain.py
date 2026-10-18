"""Merge already-masked, already-grouped messages into templates with Drain.

SQL masking has replaced obvious values with placeholders (`<NUM>`, `<PATH>`, ...)
and grouped identical masked strings with counts. Drain then merges groups that
differ only in plain words (`user alice` / `user bob`) into `user <*>`. Each
masked string is fed to Drain once; counts are carried by us, not by Drain.
"""

import logging
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime

from serenedb_extractor.templating.words import (
    collapse_lists,
    constant_word,
    list_covering,
    names_a_value,
    unit_after_number,
    zone_after_time,
)
from drain3 import TemplateMiner  # type: ignore[import-untyped]
from drain3.template_miner_config import TemplateMinerConfig  # type: ignore[import-untyped]

# drain3 logs progress through the root-adjacent "drain3" loggers; keep output quiet.
logging.getLogger("drain3").setLevel(logging.WARNING)


# role name (service, component, ...) -> value -> count
Breakdown = dict[str, dict[str, int]]


@dataclass(frozen=True)
class MaskedGroup:
    """Identical masked messages, with their count and context."""

    masked: str
    count: int
    example: str
    first_seen: datetime | None = None
    last_seen: datetime | None = None
    breakdown: Breakdown = field(default_factory=dict)


@dataclass(frozen=True)
class MergedTemplate:
    """A Drain template; `members` is the number of masked groups merged."""

    template: str
    count: int
    example: str  # taken from the largest member group
    first_seen: datetime | None
    last_seen: datetime | None
    breakdown: Breakdown
    members: int  # number of masked groups merged into this template
    masks: tuple[str, ...] = ()  # the masked strings merged into it, biggest first


def _miner(sim_th: float, depth: int) -> TemplateMiner:
    config = TemplateMinerConfig()  # defaults: no masking instructions
    config.masking_instructions = []
    # Route tokens with digits (`attempt_1445_m_000003_0`, `job_..._0020Job`) through Drain's
    # wildcard branch of its prefix tree, so one event's lines with different leading ids meet in
    # one cluster instead of one cluster per id (templates still compare the tokens themselves).
    config.parametrize_numeric_tokens = True
    config.drain_sim_th = sim_th
    config.drain_depth = depth
    return TemplateMiner(persistence_handler=None, config=config)


# A word position is an enum (part of the event's wording) rather than a variable when all its
# values are constant words (templating.words), at most MAX_ENUM_VALUES distinct ones. `VM Paused` /
# `VM Resumed` and `"GET` / `"POST` stay apart; a position with many different words (user names)
# or with ids, numbers or placeholders still becomes `<*>`. So does a position whose words are units
# after a number (`<NUM> KB` / `<NUM> MB`), time zones between a clock time and a year
# (`<NUM>:<NUM>:<NUM> PDT <NUM>` / `PST`) or follow a label naming the value (`user cyrus` / `user news`).
MAX_ENUM_VALUES = 6
_DIGITS = "0123456789"


def _split_enums(
    tokens: list[str], items: list[MaskedGroup], texts: dict[str, str]
) -> list[tuple[list[str], list[MaskedGroup]]]:
    """Split a Drain cluster by the words at its enum-like `<*>` positions.

    Drain merges messages that differ in a word (`Instance spawned successfully` / `Instance
    destroyed successfully`); that word names a different event, so the cluster splits by it and
    each part's template keeps the tokens all its members share.
    """
    member_tokens = [texts[i.masked].split() for i in items]
    if any(len(t) != len(tokens) for t in member_tokens):
        return [(tokens, items)]
    enum_positions = []
    for pos, token in enumerate(tokens):
        if token != "<*>":
            continue
        values = {constant_word(t[pos]) for t in member_tokens}
        if None in values or len(values) > MAX_ENUM_VALUES:
            continue
        if len({v.rstrip(_DIGITS) for v in values if v}) < len(values):
            continue  # `CPU0` / `CPU1`, `IRQ0` / `IRQ9`: one name numbered, an index
        if pos and any(
            names_a_value(t[pos - 1]) or unit_after_number(t[pos - 1], t[pos]) for t in member_tokens
        ):
            continue
        if 0 < pos < len(tokens) - 1 and all(
            zone_after_time(t[pos - 1], t[pos], t[pos + 1]) for t in member_tokens
        ):
            continue
        enum_positions.append(pos)
    if not enum_positions:
        return [(tokens, items)]
    by_key: dict[tuple[str, ...], list[tuple[list[str], MaskedGroup]]] = {}
    for toks, item in zip(member_tokens, items, strict=True):
        key = tuple(constant_word(toks[p]) or "" for p in enum_positions)
        by_key.setdefault(key, []).append((toks, item))
    out = []
    for members in by_key.values():
        template = [
            tok if all(m[0][pos] == tok for m in members) else tokens[pos]
            for pos, tok in enumerate(members[0][0])
        ]
        out.append((template, [m[1] for m in members]))
    return out


def _cover_lists(tokens: list[str], items: list[MaskedGroup], texts: dict[str, str]) -> list[str]:
    """The template of a part, with list placeholders only where a list's length varies.

    When every member has as many tokens as every other, no list in it varies in length: the
    template is rebuilt position by position from the masked texts themselves, keeping the typed
    placeholders (`conn <IP> <NUM> ok`, not `conn <VALUES> ok`) and `<*>` where members differ.
    Otherwise each `<*>` where a member has a list becomes a list placeholder (a lone `<*>` matches
    one token, not a list of several)."""
    originals = [i.masked.split() for i in items]
    collapsed = any(texts[i.masked] != i.masked for i in items)
    if collapsed and len({len(o) for o in originals}) == 1:
        return [o[0] if all(x == o[0] for x in o) else "<*>" for o in zip(*originals, strict=True)]
    member_tokens = [texts[i.masked].split() for i in items]
    if any(len(t) != len(tokens) for t in member_tokens):
        return tokens
    out = list(tokens)
    for pos, token in enumerate(tokens):
        if token == "<*>" and (cover := list_covering(t[pos] for t in member_tokens)):
            out[pos] = cover
    return out


def merge_groups(
    groups: Iterable[MaskedGroup], sim_th: float = 0.5, depth: int = 4
) -> list[MergedTemplate]:
    """Merge groups into templates, weighting by count; sorted by count desc, template."""
    # Drain is order-sensitive: feed biggest groups first, ties by text, so the
    # result is identical for identical input regardless of input order.
    ordered = sorted(groups, key=lambda g: (-g.count, g.masked))
    miner = _miner(sim_th, depth)
    by_cluster: dict[int, list[MaskedGroup]] = {}
    # What Drain sees: the masked text with each list as one placeholder (templating.words).
    texts = {g.masked: " ".join(collapse_lists(g.masked.split())) for g in ordered}
    for group in ordered:
        cluster_id = miner.add_log_message(texts[group.masked])["cluster_id"]
        by_cluster.setdefault(cluster_id, []).append(group)

    parts: list[tuple[list[str], list[MaskedGroup]]] = []
    for cluster_id, items in by_cluster.items():
        # Templates generalise as groups arrive, so read the final one.
        tokens = list(miner.drain.id_to_cluster[cluster_id].log_template_tokens)
        parts += _split_enums(tokens, items, texts)

    merged = []
    for tokens, items in parts:
        tokens = _cover_lists(tokens, items, texts)
        breakdown: dict[str, Counter[str]] = {}
        for item in items:
            for role, values in item.breakdown.items():
                breakdown.setdefault(role, Counter()).update(values)
        template = " ".join(tokens)
        seen_first = [i.first_seen for i in items if i.first_seen is not None]
        seen_last = [i.last_seen for i in items if i.last_seen is not None]
        merged.append(
            MergedTemplate(
                template=template,
                count=sum(i.count for i in items),
                example=items[0].example,  # ordered by count desc
                first_seen=min(seen_first, default=None),
                last_seen=max(seen_last, default=None),
                breakdown={r: dict(c) for r, c in breakdown.items()},
                members=len(items),
                masks=tuple(i.masked for i in items),
            )
        )
    merged.sort(key=lambda m: (-m.count, m.template))
    return merged
