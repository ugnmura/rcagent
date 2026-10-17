"""Tag log entries with the catalog template they match (Python-side regex matching)."""

import re
from collections.abc import Sequence

from serenedb_extractor.catalog.models import Template

NO_TEMPLATE = "—"


def tag_entries(templates: Sequence[Template], messages: Sequence[str]) -> list[str | None]:
    """For each message the ID of the first template (by template number) whose regex matches it
    in full, else None. Template regexes are valid in both RE2 and Python `re`."""
    ordered = sorted(templates, key=lambda t: int(t.template_id[1:]) if t.template_id[1:].isdigit() else 0)
    compiled: list[tuple[str, re.Pattern[str]]] = []
    for t in ordered:
        try:
            compiled.append((t.template_id, re.compile(t.regex)))
        except re.error:
            continue
    out: list[str | None] = []
    for msg in messages:
        out.append(next((tid for tid, rx in compiled if rx.fullmatch(msg)), None))
    return out


def tag_text(tag: str | None) -> str:
    return f"[{tag or NO_TEMPLATE}]"
