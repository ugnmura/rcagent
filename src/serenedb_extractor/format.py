"""Result formatting shared by every tool."""

import logging
import re
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
