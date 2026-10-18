import pytest

from serenedb_extractor.templating.words import constant_word, word_core


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
