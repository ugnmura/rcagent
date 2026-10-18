"""Merge already-masked, already-grouped messages into templates with Drain.

SQL masking has replaced obvious values with placeholders (`<NUM>`, `<PATH>`, ...)
and grouped identical masked strings with counts. Drain then merges groups that
differ only in plain words (`user alice` / `user bob`) into `user <*>`. Each
masked string is fed to Drain once; counts are carried by us, not by Drain.
"""

import logging
import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime

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
    config.parametrize_numeric_tokens = False
    config.drain_sim_th = sim_th
    config.drain_depth = depth
    return TemplateMiner(persistence_handler=None, config=config)


# A plain word, possibly ending in punctuation (`Paused`, `disk:`, `GB,`): no digits, no placeholder.
_WORD = re.compile(r"[\"'(\[]?[A-Za-z][A-Za-z_'\-]*[:,.;!?)\]]?")
# A word position is an enum (part of the event's wording) rather than a variable when it takes few
# distinct values, each repeated: distinct values <= MAX_ENUM_VALUES and the entries per value
# >= MIN_ENTRIES_PER_VALUE on average. `VM Paused` / `VM Resumed` stay apart; a user name that
# varies from entry to entry still becomes `<*>`.
MAX_ENUM_VALUES = 8
MIN_ENTRIES_PER_VALUE = 4


def _split_enums(
    tokens: list[str], items: list[MaskedGroup]
) -> list[tuple[list[str], list[MaskedGroup]]]:
    """Split a Drain cluster by the words at its enum-like `<*>` positions.

    Drain merges messages that differ in a word (`Instance spawned successfully` / `Instance
    destroyed successfully`); that word names a different event, so the cluster splits by it and
    each part's template keeps the tokens all its members share.
    """
    member_tokens = [i.masked.split() for i in items]
    if any(len(t) != len(tokens) for t in member_tokens):
        return [(tokens, items)]
    total = sum(i.count for i in items)
    enum_positions = []
    for pos, token in enumerate(tokens):
        if token != "<*>":
            continue
        values = {t[pos] for t in member_tokens}
        if (
            all(_WORD.fullmatch(v) for v in values)
            and len(values) <= MAX_ENUM_VALUES
            and total >= MIN_ENTRIES_PER_VALUE * len(values)
        ):
            enum_positions.append(pos)
    if not enum_positions:
        return [(tokens, items)]
    by_key: dict[tuple[str, ...], list[tuple[list[str], MaskedGroup]]] = {}
    for toks, item in zip(member_tokens, items, strict=True):
        by_key.setdefault(tuple(toks[p] for p in enum_positions), []).append((toks, item))
    out = []
    for members in by_key.values():
        template = [
            tok if all(m[0][pos] == tok for m in members) else tokens[pos]
            for pos, tok in enumerate(members[0][0])
        ]
        out.append((template, [m[1] for m in members]))
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
    for group in ordered:
        cluster_id = miner.add_log_message(group.masked)["cluster_id"]
        by_cluster.setdefault(cluster_id, []).append(group)

    parts: list[tuple[list[str], list[MaskedGroup]]] = []
    for cluster_id, items in by_cluster.items():
        # Templates generalise as groups arrive, so read the final one.
        tokens = list(miner.drain.id_to_cluster[cluster_id].log_template_tokens)
        parts += _split_enums(tokens, items)

    merged = []
    for tokens, items in parts:
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
