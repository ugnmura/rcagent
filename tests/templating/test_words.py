import pytest

from rcagent.templating.words import (
    collapse_lists,
    constant_word,
    list_covering,
    names_a_value,
    unit_after_number,
    word_core,
    zone_after_time,
)


@pytest.mark.parametrize(
    "token,core",
    [
        ("instruction......<NUM>", "instruction"),
        ("dcbf.........<NUM>", "dcbf"),
        ("touch.<NUM>", "touch"),
        ("core.<NUM>", "core"),
        ("depth....................0", "depth"),
        ("key...", "key"),
        ("file.map", "file.map"),
        ("v1.<NUM>.<NUM>", "v1.<NUM>"),
        ("plain", "plain"),
    ],
)
def test_word_core_strips_dot_padding_and_value(token: str, core: str) -> None:
    assert word_core(token) == core


@pytest.mark.parametrize(
    "token,word",
    [
        ("privileged", "privileged"),
        ("instruction......<NUM>", "instruction"),
        ("icbi.........<NUM>", "icbi"),
        ("x+", "x+"),
        ("z-", "z-"),
        ("Connection", "Connection"),
        ("severed,", "severed"),
        ("(Paused)", "Paused"),
        ("bglio136", None),
        ("<NUM>", None),
        ("<*>", None),
        ("J05", None),
        ("C1", None),
        ("<PATH>/torus.rts:", None),
        ("Sat", None),
        ("Sep", None),
        # signed and hyphenated words, names ending in one digit
        ("+infinity", "+infinity"),
        ("-infinity", "-infinity"),
        ("non-crc", "non-crc"),
        ("job-jar", "job-jar"),
        ("SOCKS5", "SOCKS5"),
        ("IPV6", "IPV6"),
        # a lowercase stem with a digit is a device or host
        ("awdl0", None),
        ("sit0", None),
        ("eth0", None),
        ("nagios1", None),
        ("an14", None),
        # one capital letter names an axis or port: a value
        ("Y", None),
        ("(C)", None),
        ("a", "a"),
    ],
)
def test_constant_word(token: str, word: str | None) -> None:
    assert constant_word(token) == word


def test_quoted_and_sentence_end_words_are_words():
    assert constant_word('"GET') == "GET"
    assert constant_word("successfully.") == "successfully"


@pytest.mark.parametrize(
    ("previous", "token", "unit"),
    [
        ("<NUM>", "KB,", True),
        ("(<NUM>", "MB)", True),
        ("<NUM>", "secs.", True),
        ("12", "ms", True),
        ("<NUM>", "destroyed", False),
        ("as", "bytes", False),
        ("size", "KB", False),
    ],
)
def test_unit_after_number(previous: str, token: str, unit: bool) -> None:
    assert unit_after_number(previous, token) is unit


@pytest.mark.parametrize(
    ("previous", "label"),
    [
        ("user", True),
        ("Name:", True),
        ("host", True),
        ("VM", False),
        ("for", False),
        ("<NUM>", False),
    ],
)
def test_names_a_value(previous: str, label: bool) -> None:
    assert names_a_value(previous) is label


@pytest.mark.parametrize(
    ("previous", "token", "following", "zone"),
    [
        ("<NUM>:<NUM>:<NUM>", "PDT", "<NUM>", True),
        ("21:52:10", "PST", "2005", True),
        ("14:23:01", "EST", "2005", True),
        # no year after it: a level or AM/PM, wording
        ("<NUM>:<NUM>:<NUM>", "ERROR:", "<NUM>", False),
        ("<NUM>:<NUM>:<NUM>", "INFO", "connection", False),
        ("10:23:01", "PM", "on", False),
        # no seconds: a host:port or hour:minute
        ("10:05", "UTC", "2005", False),
        ("<NUM>:<NUM>", "UTC", "<NUM>", False),
        ("<NUM>:<NUM>:<NUM>", "and", "<NUM>", False),
        ("<NUM>", "PDT", "<NUM>", False),
        ("at", "UTC", "<NUM>", False),
    ],
)
def test_zone_after_time(previous: str, token: str, following: str, zone: bool) -> None:
    assert zone_after_time(previous, token, following) is zone


@pytest.mark.parametrize(
    ("text", "collapsed"),
    [
        ("Controlling BG/L rows [ <NUM> <NUM> <NUM> <NUM> ]", "Controlling BG/L rows [ <VALUES> ]"),
        ("softheader=<HEX> <NUM> <HEX> <HEX>)", "softheader=<HEX> <VALUES> <HEX>)"),
        ("wanted: A B C X+ X- got: C X+", "wanted: <LETTERS> got: <LETTERS>"),
        ("Fan speeds ( <NUM> <NUM> **** <NUM> )", "Fan speeds ( <VALUES> **** <NUM> )"),
        # one item is no list; a direction between words stays wording; lowercase letters are words
        ("<NUM> torus receiver z+ input pipe", "<NUM> torus receiver z+ input pipe"),
        ("from <IP> port <NUM>", "from <IP> port <NUM>"),
        ("a b c", "a b c"),
    ],
)
def test_collapse_lists(text: str, collapsed: str) -> None:
    assert " ".join(collapse_lists(text.split())) == collapsed


def test_list_covering() -> None:
    assert list_covering(["C", "<LETTERS>"]) == "<LETTERS>"
    assert list_covering(["<NUM>", "<VALUES>"]) == "<VALUES>"
    assert list_covering(["word", "<VALUES>"]) == "<LIST>"
    assert list_covering(["<IP>", "host"]) is None  # no list there: a plain <*>
