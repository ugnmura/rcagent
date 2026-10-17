from pathlib import Path

import pytest

from serenedb_extractor.templating.masking import (
    MASK_RULES,
    PLACEHOLDER_CAPTURE,
    mask_py,
    mask_sql,
)

CASES = [
    ("timeout after 3021ms for user 8812", "timeout after <NUM>ms for user <NUM>"),
    ("req 8f3a2c1e-9b4d-4e2a-8c1f-0a2b3c4d5e6f done", "req <UUID> done"),
    ("connect 10.0.4.12:5432 refused", "connect <IP> refused"),
    ("GET https://x.io/a?b=1 200", "GET <URL> <NUM>"),
    ("open /var/log/app.log failed", "open <PATH> failed"),
    ("addr 0x7ffde3a1 bad", "addr <HEX> bad"),
    ("user 'alice' not found", "user <STR> not found"),
    ("R02-M1-N0-C:J12-U11 ok", "R02-M1-N0-C:J12-U11 ok"),
    ("mail bob.smith+x@example.com bounced", "mail <EMAIL> bounced"),
    ("blob 113d3a99c3da401fbd62cc2caa5b96d2 stored", "blob <HEX> stored"),
    ("epoch 1117838570 took 0.25s", "epoch <NUM> took <NUM>s"),
    ('"GET /v2/a/servers/detail HTTP/1.1" status: 200', '"GET <PATH> HTTP/<NUM>" status: <NUM>'),
    ("HTTP/1.1 ok", "HTTP/<NUM> ok"),
    ("user's thing and user's other", "user's thing and user's other"),
]

FIXTURES = Path(__file__).parent.parent / "fixtures"


def _fixture_lines(name: str, n: int = 20) -> list[str]:
    return (FIXTURES / name).read_text().splitlines()[:n]


SAMPLES = (
    [raw for raw, _ in CASES]
    + _fixture_lines("bgl_sample.log")
    + _fixture_lines("openstack_sample.log")
)


@pytest.mark.parametrize("raw,masked", CASES)
def test_mask_py(raw: str, masked: str) -> None:
    assert mask_py(raw) == masked


def test_rule_order_and_placeholders() -> None:
    assert [r.placeholder for r in MASK_RULES] == [
        "<URL>", "<EMAIL>", "<UUID>", "<IP>", "<PATH>", "<HEX>", "<STR>", "<NUM>",
    ]


def test_every_placeholder_has_a_capture_regex() -> None:
    assert PLACEHOLDER_CAPTURE["<NUM>"] == r"(-?\d+(?:\.\d+)?)"
    assert PLACEHOLDER_CAPTURE["<*>"] == r"(\S+)"
    for rule in MASK_RULES:
        assert rule.placeholder in PLACEHOLDER_CAPTURE


def test_rules_avoid_syntax_re2_lacks() -> None:
    for rule in MASK_RULES:
        for banned in ("(?=", "(?!", "(?<=", "(?<!", "*+", "++", "?+", "(?P="):
            assert banned not in rule.regex
        assert "%" not in rule.regex  # would collide with psycopg placeholders
        assert r"\s" not in rule.regex  # RE2 and Python disagree on \v


def test_masked_text_is_stable() -> None:
    once = mask_py("timeout after 3021ms at /a/b 10.0.0.1")
    assert mask_py(once) == once


def test_mask_sql_shape() -> None:
    sql = mask_sql("msg")
    assert sql.startswith("regexp_replace(")
    assert "'g'" in sql


@pytest.mark.db
def test_sql_equals_python(database) -> None:  # type: ignore[no-untyped-def]
    for raw in SAMPLES:
        assert database.read(f"SELECT {mask_sql('%(m)s')}", {"m": raw}).scalar() == mask_py(raw)


def test_placeholder_kind():
    from serenedb_extractor.templating.masking import placeholder_kind

    assert [placeholder_kind(p) for p in ("<*>", "<NUM>", "<IP>")] == ["any", "num", "ip"]


def test_tagging_matches_entries_with_edge_whitespace_like_sql():
    """query/tags.py agrees with the SQL matchers: no special case, the regex itself allows edge whitespace."""
    from serenedb_extractor.catalog.models import Template
    from serenedb_extractor.query.tags import tag_entries
    from serenedb_extractor.templating.regex import compile_template

    c = compile_template("disk full on <NUM>")
    t = Template("x", "T1", "disk full on <NUM>", c.regex, list(c.params), "", None, None, None, None)
    assert tag_entries([t], [" disk full on 3", "disk full on 3 \n", "nope"]) == ["T1", "T1", None]
