"""A NUL character can't be stored as text: templates show it as ␀ and their regex still matches the real NUL."""

import re2  # type: ignore[import-untyped]

from serenedb_extractor.templating.regex import NUL_MARK, compile_template, without_nul


def test_nul_is_shown_as_a_symbol_and_matched_in_the_data():
    text = without_nul("Assembly Revision: \x00.A, Code <NUM>")
    assert "\x00" not in text and NUL_MARK in text
    compiled = compile_template(text)
    assert "\x00" not in compiled.regex
    assert re2.fullmatch(compiled.regex, "Assembly Revision: \x00.A, Code 7")
    assert all(NUL_MARK not in w for w in compiled.fixed_words)
