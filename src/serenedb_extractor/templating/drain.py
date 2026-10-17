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

    merged = []
    for cluster_id, items in by_cluster.items():
        breakdown: dict[str, Counter[str]] = {}
        for item in items:
            for role, values in item.breakdown.items():
                breakdown.setdefault(role, Counter()).update(values)
        # Templates generalise as groups arrive, so read the final one.
        template = miner.drain.id_to_cluster[cluster_id].get_template()
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
