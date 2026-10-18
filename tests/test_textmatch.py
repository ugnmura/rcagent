"""The text predicate (query/textmatch.py): a regexp that matches exactly what ILIKE '%text%' matches (or, for a
text with an s, a superset that ILIKE then narrows), so search_logs and count_logs match what they matched before."""

import pytest

from serenedb_extractor.query.templatematch import _like_pattern
from serenedb_extractor.query.textmatch import NOT_EXACT, contains_sql, prefilter_regex

MESSAGES = [
    "error", "ERROR", "Error: x", "an eRRor here", "errors", "err or", "no match", "", None,
    "\u0130ndex failed", "index failed", "INDEX", "\u0131ndex",  # dotted capital I, dotless i
    "\u212aill -9", "kill -9", "KILL", "\u017fkip", "skip", "SKIP",  # Kelvin sign, long s
    "50% done", "50x done", "a_b", "axb", "path\\to", "c:\\temp", "q'uote", "x.y", "xzy", "(paren)", "[br]",
    "tab\there", "caf\u00e9", "CAF\u00c9",
]
TEXTS = ["error", "ERR", "index", "I", "kill", "K", "skip", "S", "50% done", "a_b", "path\\to", "q'uote", "x.y",
         "(paren)", "[br]", "caf\u00e9", "tab\there", " "]


def test_prefilter_regex_shapes():
    assert prefilter_regex("error") == "(?i)error"
    assert prefilter_regex("Kill") == "(?i)[K\u212a][i\u0130]ll"
    assert prefilter_regex("50% x.y") == "(?i)50\\x{25}\\x{20}x\\x{2e}y"
    assert prefilter_regex("caf\u00e9") is None  # non-ASCII: ILIKE alone
    assert prefilter_regex("tab\there") is None  # a control character: ILIKE alone
    assert prefilter_regex("") is None


def test_contains_sql_forms():
    sql, params = contains_sql('"m"', "caf\u00e9")
    assert sql == "(\"m\")::varchar ILIKE %(text_pattern)s ESCAPE '\\'" and "text_regex" not in params
    sql, params = contains_sql('"m"', "error")
    assert sql == "regexp_matches((\"m\")::varchar, %(text_regex)s)" and set(params) == {"text_regex"}
    sql, params = contains_sql('"m"', "disk")
    assert sql.startswith("(CASE WHEN regexp_matches(") and "ILIKE" in sql and set(params) == {"text_regex", "text_pattern"}


@pytest.mark.db
def test_regexp_and_ilike_agree_on_every_code_point(database):
    """Per printable ASCII character, the code points where the regexp and ILIKE disagree: only the long s for
    s and S (NOT_EXACT), which is why a text with an s keeps the ILIKE check."""
    disagree: dict[str, list[int]] = {}
    for o in range(32, 127):
        p = chr(o)
        got = database.read(
            "SELECT list(i ORDER BY i) FILTER (WHERE regexp_matches(c, %(rx)s) <> (c ILIKE %(pat)s ESCAPE '\\')) "
            "FROM (SELECT i, chr(i::INTEGER) AS c FROM range(1, 1114112) t(i) WHERE i NOT BETWEEN 55296 AND 57343)",
            {"rx": prefilter_regex(p), "pat": _like_pattern(p)},
        ).scalar()
        if got:
            disagree[p] = got
    assert disagree == {"S": [0x17F], "s": [0x17F]}
    assert set(disagree) == NOT_EXACT


@pytest.mark.db
def test_the_predicate_matches_exactly_what_ilike_matches(database):
    values = ", ".join(f"({i}, %(m{i})s)" for i in range(len(MESSAGES)))
    base = {f"m{i}": m for i, m in enumerate(MESSAGES)}
    for text in TEXTS:
        sql, params = contains_sql("m", text)
        got = database.read(
            f"SELECT list(i ORDER BY i) FILTER (WHERE {sql}), "
            f"list(i ORDER BY i) FILTER (WHERE (m)::varchar ILIKE %(like)s ESCAPE '\\') "
            f"FROM (VALUES {values}) t(i, m)",
            {**base, **params, "like": _like_pattern(text)},
        ).rows[0]
        assert got[0] == got[1], (text, got)
