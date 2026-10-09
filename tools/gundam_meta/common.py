"""Rules shared by every tournament source."""
from __future__ import annotations

from datetime import date, timedelta

GRACE_DAYS = 2  # an event is stored once it ended at least this many days ago, so results and decks have settled


def is_complete(event_day: date, today: date) -> bool:
    """True when the event (by its last day) finished at least GRACE_DAYS ago and so is safe to store for good."""
    return event_day + timedelta(days=GRACE_DAYS) <= today
