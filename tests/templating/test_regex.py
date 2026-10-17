import re

import pytest

from serenedb_extractor.catalog.models import Param
from serenedb_extractor.templating.regex import compile_template


def names(template: str) -> list[str]:
    return [p.name for p in compile_template(template).params]


def test_names_and_match():
    c = compile_template("login failed for user <*> from <IP>")
    assert names("login failed for user <*> from <IP>") == ["user", "from"]
    assert re.fullmatch(c.regex, "login failed for user bob from 10.0.0.7")


def test_key_value_names():
    assert names("status=<NUM> len: <NUM>") == ["status", "len"]


def test_fallback_names():
    assert names("<NUM> <NUM> done") == ["num_1", "num_2"]


def test_wildcard_fallback_is_any():
    assert names("<*> exited") == ["any_1"]


def test_params_carry_position_and_kind():
    c = compile_template("login failed for user <*> from <IP>")
    assert c.params == (Param(1, "user", "any"), Param(2, "from", "ip"))


def test_duplicate_names_get_suffix():
    assert names("from <IP> from <IP> from <IP>") == ["from", "from_2", "from_3"]


def test_fallback_name_does_not_collide_with_a_label():
    assert names("num_2=<NUM> <NUM>") == ["num_2", "num_2_2"]


def test_label_wins_over_preceding_word_and_quotes_are_skipped():
    assert names("the user id=<NUM> name '<STR>'") == ["id", "name"]


def test_one_capture_group_per_placeholder_and_values_are_captured():
    c = compile_template("conn <IP> took <NUM>ms (<*>)")
    m = re.fullmatch(c.regex, "conn 10.0.0.7:80 took 12.5ms (ok)")
    assert m and m.groups() == ("10.0.0.7:80", "12.5", "ok")


def test_whitespace_runs_match_any_ascii_whitespace():
    c = compile_template("a   b\tc <NUM>")
    assert re.fullmatch(c.regex, "a b  c\t7")
    assert "\\s" not in c.regex


def test_non_ascii_whitespace_is_a_literal_character():
    c = compile_template("a\u00a0b <NUM>")
    assert "\\s" not in c.regex
    assert re.fullmatch(c.regex, "a\u00a0b 1")
    assert not re.fullmatch(c.regex, "a b 1")


def test_anchored():
    c = compile_template("done <NUM>")
    assert not re.fullmatch(c.regex, "x done 1")
    assert not re.search(c.regex, "done 1 and more")


def test_metachar_round_trip():  # Review Focus 2
    c = compile_template("GET /api/v1/items?id=<NUM> (retry) [x]$")
    assert re.fullmatch(c.regex, "GET /api/v1/items?id=42 (retry) [x]$")


@pytest.mark.parametrize("text", list("\\.+*?()|[]{}^$-&~#%'\"<>"))
def test_every_metachar_matches_itself(text):
    c = compile_template(f"a{text}b <NUM>")
    assert re.fullmatch(c.regex, f"a{text}b 1")
    assert not re.fullmatch(c.regex, "axb 1" if text != "." else "a\nb 1")


def test_unknown_angle_text_stays_literal():
    c = compile_template("tag <foo> <NUM>")
    assert re.fullmatch(c.regex, "tag <foo> 3")
    assert len(c.params) == 1


def test_regex_avoids_syntax_re2_lacks():
    c = compile_template("GET /a?b=<NUM> (x) [y] <URL> <EMAIL> <UUID> <PATH> <HEX> <STR>")
    for bad in ("(?=", "(?!", "(?<", "(?P=", "\\1", "++", "*+"):
        assert bad not in c.regex


def test_fixed_words():
    c = compile_template("disk full on <*> after <NUM> retries")
    assert c.fixed_words == ("retries", "after", "disk")


def test_fixed_words_tie_rule_longer_first_then_first_appearance():
    c = compile_template("zzzz <*> aaaa bbbbbb cccc")
    assert c.fixed_words == ("bbbbbb", "zzzz", "aaaa")


def test_fixed_words_max_three_min_four_and_deduped():
    c = compile_template("aa <*> bbbbbb <*> cccc <*> ddddddddd <*> eeeee <*> ddddddddd")
    assert c.fixed_words == ("ddddddddd", "bbbbbb", "eeeee")


def test_fixed_words_are_whitespace_free_and_never_glued_to_a_placeholder():
    assert compile_template("error: user <*> failed").fixed_words == ("error:", "failed", "user")
    assert compile_template("user=<*> id:<NUM>ms done").fixed_words == ("done",)
    assert compile_template("<NUM>  retry   later <NUM>").fixed_words == ("retry", "later")
    assert compile_template("<NUM> <*>").fixed_words == ()


def test_fixed_words_are_substrings_of_every_matching_line():
    c = compile_template("pre<NUM>post login<*> ok fine")
    line = "pre12post loginXYZ ok fine"
    assert re.fullmatch(c.regex, line)
    assert all(w in line for w in c.fixed_words) and c.fixed_words == ("fine",)


@pytest.mark.parametrize(
    ("template", "expected"),
    [
        ("User <*>", "user"),
        ("a userId=<NUM> x", "userid"),
        ("user.name: <*>", "user_name"),
        ("x-request-id=<UUID>", "x_request_id"),
        ("__a__=<NUM>", "a"),
        ("_=<NUM>", "num_1"),
    ],
)
def test_names_are_lowercase_identifiers(template, expected):
    assert names(template) == [expected]


# C1 (final review): Drain strips edge whitespace, so a template must match an entry whose message
# has leading/trailing whitespace (spaces, tabs, a trailing newline), in Python re2 and re alike.
EDGE_LINES = ["disk full on 3 ", " disk full on 3", "disk full on 3\n", "\tdisk full on 3 \r\n", "disk full on 3"]


def test_merged_template_matches_entries_with_edge_whitespace():
    import re2  # type: ignore[import-untyped]

    from serenedb_extractor.templating.drain import MaskedGroup, merge_groups

    (m,) = merge_groups(
        [MaskedGroup("disk full on <NUM> ", 2, "disk full on 3 ", None, None), MaskedGroup("disk full on <NUM>", 1, "disk full on 4", None, None)]
    )
    c = compile_template(m.template)
    for line in EDGE_LINES:
        assert re.fullmatch(c.regex, line), repr(line)
        assert re2.fullmatch(c.regex, line), repr(line)
        assert re2.fullmatch(c.regex, line).groups() == ("3",)


def test_edge_whitespace_allowance_keeps_the_anchors():
    c = compile_template("disk full on <NUM>")
    assert not re.fullmatch(c.regex, "x disk full on 3")
    assert not re.fullmatch(c.regex, "disk full on 3 x")
    assert "\\s" not in c.regex
