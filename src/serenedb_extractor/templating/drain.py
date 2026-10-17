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


@dataclass(frozen=True)
class MaskedGroup:
    """Identical masked messages, with their count and context."""

    masked: str
    count: int
    example: str
    first_seen: datetime | None = None
    last_seen: datetime | None = None
    # role name (service, component, ...) -> value -> count
    breakdown: dict[str, dict[str, int]] = field(default_factory=dict)


@dataclass(frozen=True)
class MergedTemplate:
    template: str
    count: int
    example: str  # taken from the largest member group
    first_seen: datetime | None
    last_seen: datetime | None
    breakdown: dict[str, dict[str, int]]
    members: int  # number of masked groups merged into this template


def _miner(sim_th: float, depth: int) -> TemplateMiner:
    config = TemplateMinerConfig()  # defaults: no masking instructions
    config.masking_instructions = []
    config.parametrize_numeric_tokens = False
    config.drain_sim_th = sim_th
    config.drain_depth = depth
    return TemplateMiner(persistence_handler=None, config=config)


def _min(values: Iterable[datetime | None]) -> datetime | None:
    present = [v for v in values if v is not None]
    return min(present) if present else None


def _max(values: Iterable[datetime | None]) -> datetime | None:
    present = [v for v in values if v is not None]
    return max(present) if present else None


def merge_groups(
    groups: Iterable[MaskedGroup], sim_th: float = 0.5, depth: int = 4
) -> list[MergedTemplate]:
    """Merge groups into templates, weighting by count; sorted by count desc, template."""
    # Drain is order-sensitive: feed biggest groups first, ties by text, so the
    # result is identical for identical input regardless of input order.
    ordered = sorted(groups, key=lambda g: (-g.count, g.masked))
    miner = _miner(sim_th, depth)
    members: dict[int, list[MaskedGroup]] = {}
    for group in ordered:
        cluster_id = miner.add_log_message(group.masked)["cluster_id"]
        members.setdefault(cluster_id, []).append(group)

    merged = []
    for cluster_id, items in members.items():
        breakdown: dict[str, Counter[str]] = {}
        for item in items:
            for role, values in item.breakdown.items():
                breakdown.setdefault(role, Counter()).update(values)
        # Templates generalise as groups arrive, so read the final one.
        template = miner.drain.id_to_cluster[cluster_id].get_template()
        merged.append(
            MergedTemplate(
                template=template,
                count=sum(i.count for i in items),
                example=items[0].example,  # ordered by count desc
                first_seen=_min(i.first_seen for i in items),
                last_seen=_max(i.last_seen for i in items),
                breakdown={r: dict(c) for r, c in breakdown.items()},
                members=len(items),
            )
        )
    merged.sort(key=lambda m: (-m.count, m.template))
    return merged
