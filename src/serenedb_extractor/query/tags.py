"""Tag log entries with the catalog template they match (Python-side matching with RE2, the
same engine as SereneDB: linear time whatever the regex or the line)."""

import logging
from collections.abc import Sequence
from typing import Any

import re2  # type: ignore[import-untyped]

from serenedb_extractor.catalog.models import Template

NO_TEMPLATE = "—"
_log = logging.getLogger("serenedb_extractor")


def _number(template_id: str) -> int:
    return int(template_id[1:]) if template_id[1:].isdigit() else 0


def tag_entries(templates: Sequence[Template], messages: Sequence[str]) -> list[str | None]:
    """For each message the ID of the first template (by template number) whose regex matches it
    in full (trailing whitespace ignored), else None. A regex that does not compile is logged."""
    compiled: list[tuple[str, Any]] = []
    for t in sorted(templates, key=lambda t: _number(t.template_id)):
        try:
            compiled.append((t.template_id, re2.compile(t.regex)))
        except re2.error as exc:
            _log.warning("template %s has a regex that does not compile and is skipped when tagging: %s", t.template_id, exc)
    out: list[str | None] = []
    for msg in messages:
        text = msg.rstrip()
        out.append(next((tid for tid, rx in compiled if rx.fullmatch(text)), None))
    return out


def tag_text(tag: str | None) -> str:
    return f"[{tag or NO_TEMPLATE}]"
