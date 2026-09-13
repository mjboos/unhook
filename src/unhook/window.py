"""Digest windows that tile the calendar without overlap or gaps.

A digest that keeps no record of what it already sent has to decide what
"new" means from the clock alone.  Measuring back from the moment the job
happens to start makes that decision drift: GitHub Actions fires
scheduled jobs late, so consecutive runs sit more or less than one period
apart, and the windows either overlap (duplicate newsletters) or leave a
hole (lost ones).

So don't measure from the run.  Cut the timeline into fixed periods from
a fixed anchor: every instant then falls in exactly one period, whatever
time the job actually starts, and consecutive digests tile exactly.

With the default 84-hour period the boundaries land on Monday 18:00 and
Friday 06:00 UTC in perpetuity — twice a week, evenly spaced, since two
periods make exactly seven days.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

# A Monday, 18:00 UTC. Any instant on a period boundary works; this one
# puts the boundaries at a convenient hour either side of the weekend.
DEFAULT_ANCHOR = datetime(2024, 1, 1, 18, 0, tzinfo=UTC)

# Half of a week. Two runs per week, 3.5 days apart, no remainder.
DEFAULT_WINDOW_HOURS = 84.0


@dataclass(frozen=True)
class Window:
    """A half-open interval ``[start, end)`` of content to include."""

    start: datetime
    end: datetime

    def contains(self, moment: datetime) -> bool:
        """Whether ``moment`` falls in this window.

        Half-open so that an item landing exactly on a boundary belongs to
        the later window only, and is therefore delivered exactly once.
        """
        return self.start <= moment < self.end

    @property
    def hours(self) -> float:
        return (self.end - self.start).total_seconds() / 3600


def digest_window(
    now: datetime,
    window_hours: float = DEFAULT_WINDOW_HOURS,
    anchor: datetime = DEFAULT_ANCHOR,
) -> Window:
    """Return the most recently closed period at ``now``.

    The result depends only on the calendar, never on how punctual the run
    was: a job scheduled for a boundary and started an hour late gets the
    same window as one that started on time.

    Args:
        now: The moment the digest is being built.
        window_hours: Length of each period. 84 gives two per week.
        anchor: Any instant that sits on a period boundary.

    Returns:
        The ``Window`` whose ``end`` is the latest boundary at or before
        ``now``.
    """
    if window_hours <= 0:
        msg = f"window_hours must be positive, got {window_hours}"
        raise ValueError(msg)

    period = timedelta(hours=window_hours)
    elapsed_periods = math.floor((now - anchor) / period)
    end = anchor + elapsed_periods * period
    return Window(start=end - period, end=end)


def trailing_window(now: datetime, days: float) -> Window:
    """Return the ``days`` leading up to ``now``, for manual backfills.

    Unlike ``digest_window`` this is anchored to the caller, so repeated
    use re-sends content. It exists to fill a gap left by a missed run,
    not to drive the schedule.
    """
    if days <= 0:
        msg = f"days must be positive, got {days}"
        raise ValueError(msg)
    return Window(start=now - timedelta(days=days), end=now)


__all__ = [
    "DEFAULT_ANCHOR",
    "DEFAULT_WINDOW_HOURS",
    "Window",
    "digest_window",
    "trailing_window",
]
