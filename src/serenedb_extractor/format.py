"""Result formatting shared by every tool."""

import re
from typing import TypeVar

import psycopg

from serenedb_extractor.catalog.models import UnknownLogTable, UnknownTemplate
from serenedb_extractor.config import ConfigError
from serenedb_extractor.db import QueryTimeout

T = TypeVar("T")
_OWN_ERRORS = (ConfigError, QueryTimeout, UnknownLogTable, UnknownTemplate, ValueError)
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


def plain_error(exc: BaseException) -> str:
    """One plain-language line for any failure; never a traceback."""
    if isinstance(exc, psycopg.OperationalError):
        return "Could not reach SereneDB: " + _one_line(str(exc) or "connection failed") + " Check SERENEDB_READER_URL."
    if isinstance(exc, psycopg.Error):
        return "SereneDB rejected the query: " + _one_line(str(exc))
    if isinstance(exc, _OWN_ERRORS):
        return _one_line(str(exc))
    return "Something went wrong inside the extractor (" + type(exc).__name__ + "): " + _one_line(str(exc))
