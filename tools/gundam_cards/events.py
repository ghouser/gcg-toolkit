"""What "Where to get it" wording marks a printing handed out at an event (release-event-promo).

The one place that decides it: `build.py` gives such a printing the set code PROMO, and `export.py` skips it when choosing a card's
reference printing. The wording is documented in `docs/catalog-export.md` and `tools/gundam_cards/design.md`.
"""
from __future__ import annotations

import re

# Case-insensitive, anywhere in the text. A release event or a pre-release event ("Pre-Release", "Prerelease", "Pre Release"),
# event-participation items ("Event Participation Items", "Commemorative Items for Participants"). A bare "Event" is not enough.
_EVENT_WORDING = re.compile(
    r"\b(?:(?:pre[-\s]?)?release[-\s]+events?|event[-\s]+participation|items?\s+for\s+participants?)\b", re.IGNORECASE
)


def names_release_event(where_to_get: str) -> bool:
    """True when the text names a release event, a pre-release event or event-participation items, whatever else it mentions."""
    return _EVENT_WORDING.search(where_to_get) is not None
