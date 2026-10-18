import re
from datetime import datetime

from rcagent.templating.regex import compile_template
from rcagent.templating.drain import MaskedGroup, merge_groups
from rcagent.templating.masking import mask_py


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


def test_signed_words_stay_separate_events():
    # `round toward zero` / `+infinity` / `-infinity` are three events, as are torus directions.
    groups = [g(f"round toward {w}........<NUM>", 68) for w in ("zero", "+infinity", "-infinity")]
    groups += [
        g(f"<NUM> torus receiver {d} input pipe error(s) (dcr <HEX>) detected and corrected", 9)
        for d in ("x+", "y-")
    ]
    assert len(merge_groups(groups)) == 5


def test_hyphenated_and_versioned_words_are_wording():
    out = merge_groups(
        [
            g("<NUM> L3 EDRAM error(s) (dcr <HEX>) detected and corrected", 50),
            g("<NUM> torus non-crc error(s) (dcr <HEX>) detected and corrected", 5),
            g("<*> open through proxy <*> HTTPS", 40),
            g("<*> open through proxy <*> SOCKS5", 2),
        ]
    )
    assert len(out) == 4


def test_numbered_names_are_an_index():
    # `CPU0` .. `CPU3` differ only in the number: one event about four processors.
    (m,) = merge_groups([g(f"Processor [CPU{i}] (supports C1)", 1) for i in range(4)])
    assert m.template == "Processor <*> (supports C1)"


def test_capital_letter_is_a_value():
    (m,) = merge_groups(
        [
            g(f"ciod: {a} coordinate <NUM> exceeds physical dimension <NUM> at line <NUM>", 10)
            for a in "XYZT"
        ]
    )
    assert m.template == "ciod: <*> coordinate <NUM> exceeds physical dimension <NUM> at line <NUM>"


def test_time_zone_after_clock_time_is_a_value():
    (m,) = merge_groups(
        [
            g(f"Ido chip status changed: <HEX> status=M <NUM>:<NUM>:<NUM> {z} <NUM>", 10)
            for z in ("PDT", "PST")
        ]
    )
    assert m.template == "Ido chip status changed: <HEX> status=M <NUM>:<NUM>:<NUM> <*> <NUM>"


def test_lists_of_any_length_are_one_template():
    groups = [
        g("rts tree/torus link training failed: wanted: A B C X+ X- got: A C X+", 4),
        g("rts tree/torus link training failed: wanted: A C X+ X- Y+ Y- got: C X+ Y+", 3),
        g("rts tree/torus link training failed: wanted: B C got: C", 1),
        g("Controlling BG/L rows [ <NUM> <NUM> <NUM> <NUM> ]", 5),
        g("Controlling BG/L rows [ <NUM> <NUM> ]", 2),
    ]
    out = sorted((m.template, m.count) for m in merge_groups(groups))
    assert out == [
        ("Controlling BG/L rows [ <VALUES> ]", 7),
        ("rts tree/torus link training failed: wanted: <LETTERS> got: <LETTERS>", 8),
    ]
    # the masks stay the masked texts themselves (block counts are keyed by them)
    assert {m.masks for m in merge_groups(groups[3:])} == {
        ("Controlling BG/L rows [ <NUM> <NUM> <NUM> <NUM> ]", "Controlling BG/L rows [ <NUM> <NUM> ]")
    }


def test_list_template_matches_every_length():
    examples = ["wanted: A B C X+ X- got: A C X+", "wanted: B C got: C"]
    groups = [g(mask_py(e), 1, e) for e in examples]
    (m,) = merge_groups(groups)
    rx = compile_template(m.template).regex
    assert all(re.fullmatch(rx, e) for e in examples)
    assert not re.fullmatch(rx, "wanted: A B got: nothing here")


def test_level_after_clock_time_stays_wording():
    out = merge_groups(
        [g(f"<NUM>:<NUM>:<NUM> {lv} connection reset by peer", 10) for lv in ("ERROR", "INFO")]
    )
    assert sorted(m.template for m in out) == [
        "<NUM>:<NUM>:<NUM> ERROR connection reset by peer",
        "<NUM>:<NUM>:<NUM> INFO connection reset by peer",
    ]


def test_fixed_arity_values_keep_their_types():
    # `<IP> <NUM>` is two typed values, not a list: extract_params needs the IP and the number apart.
    (m,) = merge_groups([g("conn <IP> <NUM> ok", 10)])
    assert m.template == "conn <IP> <NUM> ok"
    (m,) = merge_groups([g("conn <IP> <NUM> ok to <IP>", 10), g("conn <IP> <NUM> ok to <HOST>", 3)])
    assert m.template == "conn <IP> <NUM> ok to <*>"


def test_varying_length_lists_still_collapse():
    (m,) = merge_groups([g("conn <IP> <NUM> ok", 10), g("conn <IP> <NUM> <NUM> ok", 3)])
    assert m.template == "conn <VALUES> ok"
