"""The one way every tool matches entries against catalog templates in SQL.

`template_match_sql` is the full match (the template's stored regex, which allows edge whitespace
like Drain does, see templating/regex.py); `fixed_word_prefilter` is the cheap LIKE prefilter of
the templates' fixed words. Every fixed word appears in every entry the template matches, so the
prefilter never drops a match; it only spares the regex the entries that can't match.
"""

from collections.abc import Sequence
from typing import Any

from serenedb_extractor.catalog.models import Template
from serenedb_extractor.templating.regex import compile_template


def _like_pattern(text: str) -> str:
    """A LIKE pattern (ESCAPE '\\') matching `text` anywhere, with its own % and _ taken literally."""
    return "%" + text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def template_match_sql(msg_expr: str, param_name: str) -> str:
    """`msg_expr` (a varchar SQL expression) full-matches the regex passed as %(param_name)s."""
    return f"regexp_full_match({msg_expr}, %({param_name})s)"


def fixed_words_sql(t: Template, msg_expr: str, params: dict[str, Any], prefix: str) -> str:
    """AND of the template's fixed words as LIKE on `msg_expr` ("" when it has none); the patterns
    go into `params` as %(<prefix>_<j>)s."""
    likes = []
    for j, w in enumerate(compile_template(t.template).fixed_words):
        params[f"{prefix}_{j}"] = _like_pattern(w)
        likes.append(f"{msg_expr} LIKE %({prefix}_{j})s ESCAPE '\\'")
    return " AND ".join(likes)


def fixed_word_prefilter(
    templates: Sequence[Template], msg_expr: str, params: dict[str, Any], prefix: str = "fw"
) -> str | None:
    """OR over the templates of (AND of each one's fixed words), or None when some template has no
    fixed word (it could match anything, so nothing can be skipped)."""
    ors = []
    for i, t in enumerate(templates):
        words = fixed_words_sql(t, msg_expr, params, f"{prefix}_{i}")
        if not words:
            return None
        ors.append(f"({words})")
    return "(" + " OR ".join(ors) + ")" if ors else None
