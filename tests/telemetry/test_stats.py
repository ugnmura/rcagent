import pytest

from serenedb_extractor.errors import UserFacingError
from serenedb_extractor.telemetry.common import (
    check_prefix,
    coverage_lines,
    fmt_us,
    guess_epoch_unit,
    parse_window,
)
from serenedb_extractor.telemetry.stats import change


def test_step_change_is_scaled_by_mad():
    c = change(median_before=0.2, mad_before=0.01, std_before=0.02, n_before=600, median_after=0.8, n_after=600)
    assert c.kind == "z" and c.z == pytest.approx(0.6 / (1.4826 * 0.01))


def test_mad_zero_falls_back_to_stddev():
    c = change(10.0, 0.0, 2.0, 50, 14.0, 50)
    assert c.kind == "z" and c.z == pytest.approx(2.0)


def test_spread_is_floored_at_one_percent_of_the_median():
    c = change(100.0, 0.0, 0.0, 50, 102.0, 50)
    assert c.z == pytest.approx(2.0)


def test_all_zero_baseline_rises_from_zero_and_is_not_ranked():
    c = change(0.0, 0.0, 0.0, 600, 2.0, 600)
    assert c.kind == "rose_from_zero" and c.z is None and c.size == 0.0


def test_zero_on_both_sides_is_unchanged():
    assert change(0.0, 0.0, 0.0, 600, 0.0, 600, peak_after=0.0).kind == "unchanged"


def test_a_spike_after_a_zero_baseline_counts_as_risen():
    assert change(0.0, 0.0, 0.0, 600, 0.0, 600, peak_after=3.0).kind == "rose_from_zero"


def test_too_little_data_needs_five_points_each_side():
    assert change(1.0, 0.1, 0.1, 4, 2.0, 600).kind == "too_little_data"
    assert change(1.0, 0.1, 0.1, 600, None, 0).kind == "too_little_data"


def test_peak_z():
    c = change(1.0, 0.1, 0.1, 10, 1.0, 10, peak_after=2.4826)
    assert c.peak_z == pytest.approx(10.0)


@pytest.mark.parametrize("value,unit", [(1772359200, "s"), (1772359200123, "ms"), (1772359200123456, "us"), (1772359200123456789, "ns")])
def test_epoch_unit_from_magnitude(value, unit):
    assert guess_epoch_unit(value) == unit


def test_prefix_must_end_with_underscore():
    assert check_prefix("rca_07_") == "rca_07_"
    for bad in ("rca_07", "", "rca-07_", "a b_"):
        with pytest.raises(UserFacingError):
            check_prefix(bad)


def test_window_defaults_to_ten_minutes_each_side():
    w = parse_window("2026-03-01T10:10:00Z")
    assert fmt_us(w.start_us) == "2026-03-01 10:00:00" and fmt_us(w.end_us) == "2026-03-01 10:20:00"
    assert parse_window("2026-03-01T11:10:00", timezone="Europe/Berlin").pivot_us == w.pivot_us


def test_window_rejects_bad_times():
    with pytest.raises(UserFacingError):
        parse_window("yesterday")
    with pytest.raises(UserFacingError):
        parse_window("2026-03-01T10:10:00Z", before_minutes=0)


def test_coverage_says_no_data_is_not_no_change():
    lines = coverage_lines({"logs": {"a"}, "metrics": {"a", "b"}, "traces": set()})
    assert "no data, not no change" in lines[0]
    assert "  a: logs yes, metrics yes, traces no" in lines and "  b: logs no, metrics yes, traces no" in lines
