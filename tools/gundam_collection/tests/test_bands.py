"""Completeness bands and the cost to the next one."""
from __future__ import annotations

from shared.basetypes import CardNumber
from tools.gundam_collection.bands import THRESHOLDS, Band, Need, ahead, band_of, key_minimum, next_band, share

N = CardNumber


def need(card: str, need: int, have: int, cents: int | None = 100, key: bool = True) -> Need:
    return Need(N(card), need, have, cents, key)


def ten(have: int) -> list[Need]:
    """Ten one-copy cards that are not key cards, `have` of them owned: the share is `have` / 10."""
    return [need(f"A-{i:03}", 1, 1 if i < have else 0, key=False) for i in range(10)]


def test_the_ladder() -> None:
    assert [THRESHOLDS[b] for b in (Band.PERFECT, Band.COMPLETE, Band.PLAYABLE, Band.REACHABLE, Band.LONG_SHOT)] == [1.0, 0.9, 0.75, 0.5, 0.25]
    got = [band_of(ten(h)) for h in (10, 9, 8, 7, 5, 3, 2, 0)]  # 100%, 90%, 80%, 70%, 50%, 30%, 20%, 0%
    assert got == [Band.PERFECT, Band.COMPLETE, Band.PLAYABLE, Band.REACHABLE, Band.REACHABLE, Band.LONG_SHOT, Band.NOT_HAPPENING, Band.NOT_HAPPENING]


def test_the_boundaries_are_inclusive() -> None:
    six_of_eight = [need("A-001", 4, 3, key=False), need("A-002", 4, 3, key=False)]
    assert share(six_of_eight) == 0.75 and band_of(six_of_eight) is Band.PLAYABLE
    assert band_of([need("A-001", 4, 2, key=False)]) is Band.REACHABLE  # exactly 50%
    assert band_of([need("A-001", 4, 1, key=False)]) is Band.LONG_SHOT  # exactly 25%


def test_a_key_card_with_one_or_zero_of_four_caps_the_band_at_reachable() -> None:
    assert [key_minimum(n) for n in (4, 3, 2, 1)] == [2, 2, 1, 1]
    cards = [need("A-001", 4, 1), need("B-001", 4, 4), need("C-001", 4, 4), need("D-001", 4, 4)]  # 13 of 16 = 81%, but A is at 1 of 4
    assert share(cards) > 0.75 and band_of(cards) is Band.REACHABLE
    assert band_of([need("A-001", 4, 2), *cards[1:]]) is Band.PLAYABLE  # 2 of 4 is enough
    assert band_of([need("A-001", 4, 0, key=False), *cards[1:]]) is Band.PLAYABLE  # a staple at zero does not trip the guard (12 of 16)


def test_cost_to_playable_buys_the_forced_key_copies_first_then_the_cheapest() -> None:
    cards = [need("A-001", 4, 0, 5000), need("B-001", 4, 4, 100), need("C-001", 4, 2, 300, key=False), need("D-001", 4, 3, 50, key=False)]
    assert band_of(cards) is Band.REACHABLE  # 9 of 16
    up = next_band(cards)
    assert up is not None and up.band is Band.PLAYABLE and up.copies == 3  # 12 copies are needed
    assert dict(up.buys) == {N("A-001"): 2, N("D-001"): 1}  # 2 x A forced by the guard, then the cheapest missing copy
    assert (up.cost_cents, up.unpriced) == (2 * 5000 + 50, 0)


def test_cost_to_complete_and_to_perfect() -> None:
    cards = [need("A-001", 4, 4), need("B-001", 4, 3, 200, key=False), need("C-001", 4, 3, 100, key=False), need("D-001", 4, 2, 900, key=False)]  # 12 of 16, playable
    assert band_of(cards) is Band.PLAYABLE
    to_complete = next_band(cards)
    assert to_complete is not None and to_complete.band is Band.COMPLETE and to_complete.copies == 3  # 90% of 16 rounds up to 15
    assert dict(to_complete.buys) == {N("C-001"): 1, N("B-001"): 1, N("D-001"): 1}  # the cheapest three
    done = [need("A-001", 4, 4), need("B-001", 4, 4), need("C-001", 4, 4), need("D-001", 4, 3, 900, key=False)]  # 15 of 16, complete
    to_perfect = next_band(done)
    assert to_perfect is not None and to_perfect.band is Band.PERFECT and dict(to_perfect.buys) == {N("D-001"): 1} and to_perfect.cost_cents == 900
    assert next_band([need("A-001", 4, 4)]) is None  # nothing above Perfect


def test_a_copy_with_no_price_is_counted_apart_so_the_cost_is_a_minimum() -> None:
    cards = [need("A-001", 4, 2, None), need("B-001", 4, 4, 100)]  # 6 of 8: playable guard ok (2 of 4); next is complete (8 of 8 needs 90% = 8)
    up = next_band(cards)
    assert up is not None and up.cost_cents == 0 and up.unpriced == 2


def test_lower_bands_also_have_a_next_band() -> None:
    up = next_band(ten(0))
    assert up is not None and up.band is Band.LONG_SHOT and up.copies == 3  # 25% of 10 rounds up to 3


def test_ahead_shows_two_bands_for_reachable_and_playable_and_one_for_the_rest() -> None:
    def targets(needs: list[Need]) -> list[Band]:
        return [step.band for step in ahead(needs)]

    assert targets(ten(10)) == []  # perfect: nothing ahead
    assert targets(ten(9)) == [Band.PERFECT]  # complete: perfect only
    assert targets(ten(8)) == [Band.COMPLETE, Band.PERFECT]  # playable: complete and perfect
    assert targets(ten(5)) == [Band.PLAYABLE, Band.COMPLETE]  # reachable: playable and complete
    assert targets(ten(3)) == [Band.REACHABLE]  # long shot: the next band only
    assert targets(ten(0)) == [Band.LONG_SHOT]  # not happening: the next band only
    steps = ahead(ten(8))
    assert [s.copies for s in steps] == [1, 2] and steps[0].cost_cents == 100 and steps[1].cost_cents == 200  # each from what I own now, not stacked
