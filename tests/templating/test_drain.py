import re
from datetime import datetime

from rcagent.templating.regex import compile_template
from rcagent.templating.drain import MaskedGroup, merge_groups


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
    users = (
        "alice",
        "bob",
        "carol",
        "dave",
        "erin",
        "frank",
        "grace",
    )  # more words than an enum has
    (m,) = merge_groups([g(f"login failed for user {u}", 1) for u in users])
    assert (m.template, m.count) == ("login failed for user <*>", 7)
    assert m.members == 7


def test_few_words_stay_separate_events():
    out = merge_groups(
        [g("cupsd startup succeeded", 5), g("cupsd shutdown succeeded", 3)]
    )
    assert [m.template for m in out] == [
        "cupsd startup succeeded",
        "cupsd shutdown succeeded",
    ]


def test_few_labelled_values_still_merge():
    # `user cyrus` / `user news`: the word after a label is the labelled value, however few there are.
    out = merge_groups(
        [g("session closed for user cyrus", 43), g("session closed for user news", 36)]
    )
    assert [(m.template, m.count) for m in out] == [("session closed for user <*>", 79)]
    (n,) = merge_groups(
        [
            g("CCDataTap::profileRemoved, Owner: <*> Name: StateSnapshots", 1),
            g("CCDataTap::profileRemoved, Owner: <*> Name: AssociationEventHistory", 1),
        ]
    )
    assert n.template == "CCDataTap::profileRemoved, Owner: <*> Name: <*>"


def test_unit_after_number_is_part_of_the_value():
    out = merge_groups(
        [
            g(
                "Block <*> stored as bytes in memory (estimated size <NUM> B, free <NUM> KB)",
                85,
            ),
            g(
                "Block <*> stored as bytes in memory (estimated size <NUM> KB, free <NUM> KB)",
                64,
            ),
        ]
    )
    assert [m.template for m in out] == [
        "Block <*> stored as bytes in memory (estimated size <NUM> <*> free <NUM> KB)"
    ]


def test_leading_id_does_not_split_the_event_per_id():
    # Ids with digits (`attempt_..._000003_0`) take Drain's wildcard branch, so one event's lines with
    # different ids meet in one cluster and the enum split goes by the state words only.
    groups = [
        g(f"attempt_1445_0020_m_00000{i}_0 TaskAttempt Transitioned from {a} to {b}", 1)
        for i in range(8)
        for a, b in (("NEW", "UNASSIGNED"), ("UNASSIGNED", "ASSIGNED"))
    ]
    assert sorted((m.template, m.count) for m in merge_groups(groups)) == [
        ("<*> TaskAttempt Transitioned from NEW to UNASSIGNED", 8),
        ("<*> TaskAttempt Transitioned from UNASSIGNED to ASSIGNED", 8),
    ]


def test_masked_tokens_survive():
    (m,) = merge_groups([g("timeout after <NUM>ms calling payments", 4)])
    assert m.template == "timeout after <NUM>ms calling payments"


def test_breakdowns_summed():
    (m,) = merge_groups(
        [
            g("x a1", 2, service={"checkout": 2}),
            g("x b2", 1, service={"payments": 1}, component={"db": 1}),
        ]
    )
    assert m.breakdown["service"] == {"checkout": 2, "payments": 1}
    assert m.breakdown["component"] == {"db": 1}


def test_shapes_stay_apart():
    assert (
        len(
            merge_groups(
                [g("disk full on <PATH>", 1), g("cache miss for key <STR>", 1)]
            )
        )
        == 2
    )


def test_seen_range_and_example_from_largest():
    d = datetime
    (m,) = merge_groups(
        [
            g("login failed for user u17", 2, "ex-small", d(2026, 3, 2), d(2026, 3, 3)),
            g("login failed for user u42", 9, "ex-big", d(2026, 3, 1), None),
            g("login failed for user u99", 1, "ex-none"),
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


def test_enum_word_keeps_events_apart():
    # A word with few values, each repeated, names the event: the templates stay apart.
    groups = [
        g(f"[instance: <UUID>] VM {w} (Lifecycle Event)", 20)
        for w in ("Paused", "Resumed", "Stopped")
    ]
    groups += [
        g(f'<IP> "{m} <PATH> HTTP/<NUM>" status: <NUM>', 30)
        for m in ("GET", "POST", "DELETE")
    ]
    templates = sorted(m.template for m in merge_groups(groups))
    assert templates == sorted(
        [
            f"[instance: <UUID>] VM {w} (Lifecycle Event)"
            for w in ("Paused", "Resumed", "Stopped")
        ]
        + [
            f'<IP> "{m} <PATH> HTTP/<NUM>" status: <NUM>'
            for m in ("GET", "POST", "DELETE")
        ]
    )


def test_many_distinct_words_still_merge():
    (m,) = merge_groups([g(f"login failed for user {u}", 10) for u in "abcdefghij"])
    assert m.template == "login failed for user <*>"
