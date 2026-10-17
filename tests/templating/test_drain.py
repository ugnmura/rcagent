import re
from datetime import datetime

from serenedb_extractor.templating.regex import compile_template
from serenedb_extractor.templating.drain import MaskedGroup, merge_groups


def g(masked, count, example=None, first_seen=None, last_seen=None, **breakdown):
    return MaskedGroup(
        masked=masked,
        count=count,
        example=example or masked,
        first_seen=first_seen,
        last_seen=last_seen,
        breakdown=breakdown,
    )


def test_word_variation_merges():
    (m,) = merge_groups(
        [
            g("login failed for user alice", 5),
            g("login failed for user bob", 3),
            g("login failed for user carol", 2),
        ]
    )
    assert (m.template, m.count) == ("login failed for user <*>", 10)
    assert m.members == 3


def test_masked_tokens_survive():
    (m,) = merge_groups([g("timeout after <NUM>ms calling payments", 4)])
    assert m.template == "timeout after <NUM>ms calling payments"


def test_breakdowns_summed():
    (m,) = merge_groups(
        [
            g("x a", 2, service={"checkout": 2}),
            g("x b", 1, service={"payments": 1}, component={"db": 1}),
        ]
    )
    assert m.breakdown["service"] == {"checkout": 2, "payments": 1}
    assert m.breakdown["component"] == {"db": 1}


def test_shapes_stay_apart():
    assert len(merge_groups([g("disk full on <PATH>", 1), g("cache miss for key <STR>", 1)])) == 2


def test_seen_range_and_example_from_largest():
    d = datetime
    (m,) = merge_groups(
        [
            g("login failed for user alice", 2, "ex-small", d(2026, 3, 2), d(2026, 3, 3)),
            g("login failed for user bob", 9, "ex-big", d(2026, 3, 1), None),
            g("login failed for user carol", 1, "ex-none"),
        ]
    )
    assert m.example == "ex-big"
    assert (m.first_seen, m.last_seen) == (d(2026, 3, 1), d(2026, 3, 3))


def test_all_unseen_stays_none():
    (m,) = merge_groups([g("only one", 1)])
    assert (m.first_seen, m.last_seen) == (None, None)


def test_sorted_by_count_then_template_and_deterministic():
    groups = [g("b one", 1), g("a two words", 1), g("c three words here", 5)]
    out = [m.template for m in merge_groups(groups)]
    assert out == ["c three words here", "a two words", "b one"]
    assert out == [m.template for m in merge_groups(list(reversed(groups)))]


def test_empty_input():
    assert merge_groups([]) == []


def test_differing_placeholders_become_wildcard_others_kept():
    (m,) = merge_groups(
        [g("failed at <PATH> after <NUM>ms", 3), g("failed at <STR> after <NUM>ms", 2)]
    )
    assert m.template == "failed at <*> after <NUM>ms"


def test_merged_template_round_trips_through_compiler():
    example = "disk  full on\t/dev/sda1"
    (m,) = merge_groups([g("disk  full on\t<PATH>", 1, example)])
    assert re.fullmatch(compile_template(m.template).regex, example)
