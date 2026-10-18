import pytest

from serenedb_extractor.templating.words import (
    constant_word,
    names_a_value,
    unit_after_number,
    word_core,
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
