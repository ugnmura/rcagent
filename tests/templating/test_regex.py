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


def test_whitespace_runs_match_any_whitespace():
    c = compile_template("a   b\tc <NUM>")
    assert re.fullmatch(c.regex, "a b  c\t7")
    assert c.regex.startswith("^a\\s+b\\s+c\\s+") and c.regex.endswith("$")


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
    assert compile_template("disk full on <*> after <NUM> retries").fixed_words[0] == "disk full on"


def test_fixed_words_longest_first_max_three_min_four_chars():
    c = compile_template("aa <*> bbbbbb <*> cccc <*> ddddddddd <*> eeeee <*> ddddddddd")
    assert c.fixed_words == ("ddddddddd", "bbbbbb", "eeeee")


def test_fixed_words_collapse_whitespace_and_skip_empty():
    c = compile_template("<NUM>  retry   later <NUM>")
    assert c.fixed_words == ("retry later",)
    assert compile_template("<NUM> <*>").fixed_words == ()
