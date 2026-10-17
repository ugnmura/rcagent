import math

from serenedb_extractor.format import Measured, estimate, render


def test_estimate_margin_formula():
    m = estimate(hits=1000, sample_size=100_000, population=4_800_000)
    p = 0.01
    assert m.value == 48_000 and not m.exact and m.hits == 1000
    assert m.margin_rel is not None and math.isclose(m.margin_rel, 1.96 * math.sqrt((1 - p) / (100_000 * p)))


def test_render_estimate():
    assert render(estimate(1000, 100_000, 4_800_000)) == "≈48,000 (estimated from a 100k sample, ±6%)"
    assert render(Measured(48_000, False, 100_000, 1000, 0.02)) == "≈48,000 (estimated from a 100k sample, ±2%)"


def test_render_odd_sample_size_is_not_abbreviated():
    assert "a 4,873 sample" in render(Measured(10, False, 4873, 50, 0.3))


def test_too_rare():
    m = estimate(hits=9, sample_size=100_000, population=1_000_000)
    assert m.margin_rel is None
    assert render(m) == "too rare to estimate reliably: 9 sampled hits"
    assert "too rare" not in render(estimate(10, 100_000, 1_000_000))


def test_exact_is_not_called_an_estimate():
    assert render(Measured(1234, True)) == "1,234 (exact)"
