"""The change statistic every change tool uses (spec: "The change statistic"). Fixed, not tuned.

z = (median_after - median_before) / spread, where spread is 1.4826 * MAD of the baseline, or its
standard deviation when MAD is 0, never less than 1% of |median_before|. The SQL side computes the
aggregates; this module only turns them into a Change, so every tool classifies the same way.
"""

from dataclasses import dataclass
from typing import Literal

MIN_POINTS = 5
MAD_SCALE = 1.4826
FLOOR = 0.01

Kind = Literal["z", "rose_from_zero", "unchanged", "too_little_data"]


@dataclass(frozen=True)
class Change:
    kind: Kind
    median_before: float | None
    median_after: float | None
    n_before: int
    n_after: int
    spread: float | None = None
    z: float | None = None
    peak_after: float | None = None
    peak_z: float | None = None

    @property
    def size(self) -> float:
        """Sort key: |z| for ranked changes, 0 otherwise (the other kinds are listed apart)."""
        return abs(self.z) if self.kind == "z" and self.z is not None else 0.0


def change(
    median_before: float | None,
    mad_before: float | None,
    std_before: float | None,
    n_before: int,
    median_after: float | None,
    n_after: int,
    peak_after: float | None = None,
) -> Change:
    """Classify one series' (or operation's, or rate's) move across the pivot."""
    n_before, n_after = int(n_before or 0), int(n_after or 0)
    if n_before < MIN_POINTS or n_after < MIN_POINTS or median_before is None or median_after is None:
        return Change("too_little_data", median_before, median_after, n_before, n_after, peak_after=peak_after)
    spread = MAD_SCALE * mad_before if mad_before else 0.0
    if spread == 0.0:
        spread = std_before or 0.0
    spread = max(spread, FLOOR * abs(median_before))
    if spread == 0.0:
        # The baseline is exactly zero everywhere: z would be infinite, so it gets its own group.
        moved = median_after != 0 or (peak_after is not None and peak_after != 0)
        kind: Kind = "rose_from_zero" if moved else "unchanged"
        return Change(kind, median_before, median_after, n_before, n_after, 0.0, peak_after=peak_after)
    z = (median_after - median_before) / spread
    peak_z = (peak_after - median_before) / spread if peak_after is not None else None
    return Change("z", median_before, median_after, n_before, n_after, spread, z, peak_after, peak_z)
