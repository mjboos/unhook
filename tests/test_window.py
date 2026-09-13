"""Tests for digest window arithmetic."""

from datetime import UTC, datetime, timedelta

import pytest

from unhook.window import (
    DEFAULT_ANCHOR,
    DEFAULT_WINDOW_HOURS,
    Window,
    digest_window,
    trailing_window,
)


class TestDigestWindow:
    """Tests for digest_window."""

    def test_window_is_one_period_long(self):
        """The window spans exactly the configured period."""
        window = digest_window(datetime(2026, 9, 14, 18, 0, tzinfo=UTC))
        assert window.hours == DEFAULT_WINDOW_HOURS

    def test_ends_on_the_boundary_just_passed(self):
        """A run at its boundary closes the period that just ended."""
        boundary = DEFAULT_ANCHOR + timedelta(hours=DEFAULT_WINDOW_HOURS * 100)
        window = digest_window(boundary)
        assert window.end == boundary
        assert window.start == boundary - timedelta(hours=DEFAULT_WINDOW_HOURS)

    @pytest.mark.parametrize("lateness_minutes", [0, 1, 7, 45, 240])
    def test_late_runs_get_the_same_window(self, lateness_minutes):
        """Window depends on the calendar, not on when the job started.

        This is the whole point: GitHub Actions fires scheduled jobs late,
        and a window measured from the run would drift by that lateness.
        """
        boundary = DEFAULT_ANCHOR + timedelta(hours=DEFAULT_WINDOW_HOURS * 200)
        on_time = digest_window(boundary)
        late = digest_window(boundary + timedelta(minutes=lateness_minutes))
        assert late == on_time

    def test_consecutive_windows_tile_exactly(self):
        """Successive periods leave no overlap and no gap."""
        start = DEFAULT_ANCHOR + timedelta(hours=DEFAULT_WINDOW_HOURS)
        previous = None
        for step in range(52):  # half a year of runs
            moment = start + timedelta(hours=DEFAULT_WINDOW_HOURS * step)
            window = digest_window(moment)
            if previous is not None:
                assert window.start == previous.end
            previous = window

    def test_default_boundaries_fall_twice_a_week(self):
        """84 hours puts the boundaries on Monday and Friday, forever."""
        seen = set()
        for step in range(60):
            end = digest_window(
                DEFAULT_ANCHOR + timedelta(hours=DEFAULT_WINDOW_HOURS * (step + 1))
            ).end
            seen.add((end.strftime("%A"), end.strftime("%H:%M")))
        assert seen == {("Monday", "18:00"), ("Friday", "06:00")}

    def test_two_periods_make_exactly_one_week(self):
        """The pair repeats weekly, so local delivery times stay put."""
        assert DEFAULT_WINDOW_HOURS * 2 == 7 * 24

    def test_custom_period_and_anchor(self):
        """A different cadence is a different period length."""
        anchor = datetime(2026, 1, 1, tzinfo=UTC)
        window = digest_window(
            datetime(2026, 1, 4, 12, tzinfo=UTC), window_hours=24, anchor=anchor
        )
        assert window.start == datetime(2026, 1, 3, tzinfo=UTC)
        assert window.end == datetime(2026, 1, 4, tzinfo=UTC)

    def test_rejects_non_positive_period(self):
        """A zero or negative period has no meaningful window."""
        with pytest.raises(ValueError, match="must be positive"):
            digest_window(datetime.now(UTC), window_hours=0)


class TestWindowContains:
    """Tests for Window.contains."""

    def test_half_open_delivers_boundary_items_once(self):
        """An item exactly on a boundary belongs to the later window only."""
        boundary = datetime(2026, 9, 14, 18, tzinfo=UTC)
        earlier = Window(boundary - timedelta(hours=84), boundary)
        later = Window(boundary, boundary + timedelta(hours=84))

        assert not earlier.contains(boundary)
        assert later.contains(boundary)

    def test_excludes_items_outside(self):
        """Items before the start or at/after the end are excluded."""
        window = Window(
            datetime(2026, 9, 11, 6, tzinfo=UTC), datetime(2026, 9, 14, 18, tzinfo=UTC)
        )
        assert not window.contains(datetime(2026, 9, 11, 5, 59, tzinfo=UTC))
        assert window.contains(datetime(2026, 9, 12, tzinfo=UTC))
        assert not window.contains(datetime(2026, 9, 14, 18, tzinfo=UTC))


class TestTrailingWindow:
    """Tests for trailing_window."""

    def test_spans_the_requested_days_up_to_now(self):
        """A backfill window is anchored to the caller."""
        now = datetime(2026, 9, 14, 18, tzinfo=UTC)
        window = trailing_window(now, 3.5)
        assert window.end == now
        assert window.start == now - timedelta(days=3.5)

    def test_rejects_non_positive_days(self):
        """A zero or negative backfill has no meaningful window."""
        with pytest.raises(ValueError, match="must be positive"):
            trailing_window(datetime.now(UTC), 0)
