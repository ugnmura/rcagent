"""Result formatting shared by every tool."""

import logging
import math
import re
from dataclasses import dataclass
from typing import TypeVar

from serenedb_extractor.errors import UserFacingError

T = TypeVar("T")
PREFIX = "How this was measured: "


def how_measured(
    kind: str,
    period: str | None = None,
    filters: str | None = None,
    sample: str | None = None,
    index_used: str | None = None,
    tz: str = "UTC",
) -> str:
    parts = [
        kind,
        f"period: {period}" if period else "period: all time",
        f"filters: {filters}" if filters else "no filters",
        sample if sample else "no sampling",
        f"index used: {index_used}" if index_used else "no index used",
        f"times in {tz}",
    ]
    return PREFIX + "; ".join(parts) + "."


def clamp_limit(requested: int | None, default: int, cap: int) -> int:
    if requested is None or requested < 1:
        return default
    return min(requested, cap)


def cut(items: list[T], limit: int, noun: str) -> tuple[list[T], str | None]:
    if len(items) <= limit:
        return items, None
    return items[:limit], f"showing {limit} of {len(items)} {noun}"


def shorten(text: str, max_chars: int = 500) -> str:
    return text if len(text) <= max_chars else text[:max_chars] + "…(cut)"


def _one_line(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def plain_error(exc: BaseException, tool: str = "the tool") -> str:
    """One plain-language line for any failure; never a traceback.

    Only UserFacingError messages are shown; anything else is logged to stderr and replaced
    by a generic line without the exception type or text.
    """
    if isinstance(exc, UserFacingError):
        return _one_line(str(exc))
    logging.getLogger("serenedb_extractor").error("unexpected failure in %s", tool, exc_info=exc)
    return f"Something went wrong while running {tool}; details were logged."


MIN_HITS = 10


@dataclass(frozen=True)
class Measured:
    """A number with how it was obtained; estimates never render as bare numbers."""

    value: float
    exact: bool
    sample_size: int | None = None
    hits: int | None = None
    margin_rel: float | None = None


def estimate(hits: int, sample_size: int, population: int) -> Measured:
    """Scale `hits` sampled matches up to `population`; the 95% relative margin is 1.96*sqrt((1-p)/(n*p))."""
    if hits <= 0 or sample_size <= 0:
        return Measured(0.0, False, sample_size, hits, None)
    p = hits / sample_size
    margin = 1.96 * math.sqrt((1 - p) / (sample_size * p))
    return Measured(p * population, False, sample_size, hits, margin if hits >= MIN_HITS else None)


def _sig3(value: float) -> int:
    if value < 1000:
        return round(value)
    digits = int(math.log10(value)) + 1
    return int(round(value, 3 - digits))


def _sample_label(n: int) -> str:
    return f"{n // 1000}k" if n >= 1000 and n % 1000 == 0 else f"{n:,}"


def _margin_label(margin: float) -> str:
    pct = margin * 100
    return f"{pct:.0f}" if pct >= 1 else (f"{pct:.1f}" if pct >= 0.1 else "<0.1")


def render(m: Measured) -> str:
    if m.exact:
        return f"{round(m.value):,} (exact)"
    if m.margin_rel is None:
        return f"too rare to estimate reliably: {m.hits or 0} sampled hits"
    return f"≈{_sig3(m.value):,} (estimated from a {_sample_label(m.sample_size or 0)} sample, ±{_margin_label(m.margin_rel)}%)"
