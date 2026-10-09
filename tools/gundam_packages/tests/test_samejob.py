"""Same job (shared/samejob.py). Cases are the ones worked out with the user."""
from __future__ import annotations

from shared.basetypes import Trait
from shared.samejob import Matcher, Pilot, Standing, Verdict, effect_features, native_keywords, pilots_from
from tools.gundam_cards.models import CardModel, Color, CommandCard, Keyword, names_of
from tools.gundam_packages.tests.helpers import base, command, pilot, unit

REPAIR = "<Repair 1> (At the end of your turn, this Unit recovers the specified number of HP.)"
MARIDA = pilot("GD01-093", "Marida Cruz", traits=("Neo Zeon", "Cyber-Newtype"), color=Color.RED)
PLE_TWELVE = pilot("ST12-012", "Ple-Twelve", traits=("Earth Federation", "Cyber-Newtype"), color=Color.PURPLE,
                   text="This card's name is also treated as [Marida Cruz].\n【Burst】Add this card to your hand.")  # fmt: skip

BIG = unit("GD01-044", "Kshatriya", link="Marida Cruz", color=Color.RED, ap=5, hp=4, text="【When Paired】Choose 1 enemy Unit. Deal 1 damage to it.")
SMALL = unit("GD01-051", "Kshatriya", link_trait="Cyber-Newtype", color=Color.RED, ap=3, hp=4)
BESSERUNG = unit("GD03-005", "Kshatriya Besserung", link="Marida Cruz", color=Color.BLUE, ap=4, hp=4, text=REPAIR + "\n【Deploy】Draw 1.")
BANSHEE = unit("GD01-010", "Banshee", link="Marida Cruz", color=Color.BLUE, ap=4, hp=3, text="【When Paired】Choose 1 enemy Unit with 3 or less HP. Rest it.")
GEARA = unit("GD05-056", "Rezin's Geara Doga", link_trait="Cyber-Newtype", color=Color.PURPLE, ap=3, hp=4)
DELTA_PLUS = unit("GD01-006", "Delta Plus", link_trait="Earth Federation", color=Color.BLUE, ap=4, hp=3, text=REPAIR + "\n【During Link】This Unit gets HP+1.")


def verdict(x: CardModel, y: CardModel, pilots: tuple[Pilot, ...]) -> Verdict:
    return Matcher(pilots).stands_in(x, y).verdict


def test_a_pilot_answers_to_every_name_it_has() -> None:
    assert names_of(MARIDA) == ("Marida Cruz",)
    assert names_of(PLE_TWELVE) == ("Ple-Twelve", "Marida Cruz")


def test_native_keywords_are_the_ones_the_card_has() -> None:
    assert native_keywords("<Blocker> (Rest this Unit to change the attack target to it.)\n【Deploy】Draw 1.") == {Keyword.BLOCKER}
    assert native_keywords("【Activate･Main】<Support 1> (Rest this Unit. ...)") == {Keyword.SUPPORT}  # after a timing tag
    assert native_keywords("【During Link】This Unit gains <Breach 3>.") == {Keyword.BREACH}  # the normal state of a Linked Unit
    assert native_keywords("【During Pair】【Activate･Main】Exile 4 cards from your trash：This Unit gains <First Strike> and <Suppression>.") == {Keyword.FIRST_STRIKE, Keyword.SUPPRESSION}  # its own, even at a cost
    assert native_keywords("【Deploy】Choose 1 friendly Unit. It gains <Breach 2> during this turn.") == frozenset()  # granted to another Unit
    assert native_keywords("Choose 1 Unit with <Blocker>.") == frozenset()  # a mention


def test_effect_features_ignore_reminder_text_and_numbers() -> None:
    assert effect_features(REPAIR + "\n【Deploy】Draw 1.") == {"draw"}  # the Repair reminder's "recovers" is not an effect
    assert effect_features("【Main】Choose 1 enemy Unit. Deal 2 damage to it. Draw 1.") == {"damage", "draw"}
    assert effect_features("【Attack】Choose 1 Unit. It gets AP+2.") == {"+AP"}
    assert effect_features("【Main】Choose 1 enemy Unit. It gets AP-3. Rest it.") == {"-AP", "rest"}


def test_besserung_is_a_kshatriya_alternative_though_it_is_blue() -> None:
    marida = pilots_from([MARIDA])
    assert verdict(SMALL, BESSERUNG, marida) is Verdict.SAME_JOB  # better: more AP, Repair and a draw
    assert Matcher(marida).stands_in(SMALL, BESSERUNG).standing is Standing.BETTER
    big_match = Matcher(marida).stands_in(BIG, BESSERUNG)  # gives up damage, gets Repair and a draw back; AP 4 is within 1 of 5
    assert big_match.verdict is Verdict.SAME_JOB and big_match.standing is Standing.TRADE_OFF


def test_it_is_directional() -> None:
    marida = pilots_from([MARIDA])
    assert verdict(SMALL, BESSERUNG, marida) is Verdict.SAME_JOB
    assert verdict(BESSERUNG, SMALL, marida) is Verdict.CLOSE  # loses Repair and the draw and gets nothing back


def test_a_vanilla_purple_unit_with_the_same_stats_stands_in_for_the_small_kshatriya_only() -> None:
    marida = pilots_from([MARIDA])
    assert Matcher(marida).stands_in(SMALL, GEARA).standing is Standing.EQUAL
    close = Matcher(marida).stands_in(BIG, GEARA)
    assert close.verdict is Verdict.CLOSE and any("stats" in r for r in close.reasons)  # a 3/4 vanilla is not a 5/4 with an ability


def test_the_stat_band_is_ap_and_hp_not_level_and_cost() -> None:
    marida = pilots_from([MARIDA])
    weak = unit("GD01-099", "Weak", link="Marida Cruz", ap=2, hp=2, level=1, cost=1)
    heavy = unit("GD01-098", "Heavy", link="Marida Cruz", ap=3, hp=4, level=9, cost=9)
    assert verdict(SMALL, weak, marida) is Verdict.CLOSE  # a 3/4 is not swapped for a 2/2
    assert verdict(SMALL, heavy, marida) is Verdict.SAME_JOB  # level and cost never matter


def test_delta_plus_matches_only_in_a_deck_that_runs_ple_twelve() -> None:
    plain = pilots_from([MARIDA])
    with_ple = pilots_from([MARIDA, PLE_TWELVE])
    assert verdict(BIG, DELTA_PLUS, plain) is Verdict.DIFFERENT  # Marida is not Earth Federation
    assert verdict(BIG, DELTA_PLUS, with_ple) is Verdict.SAME_JOB  # Ple-Twelve is Earth Federation and is also named Marida Cruz
    assert verdict(BIG, BESSERUNG, pilots_from([PLE_TWELVE])) is Verdict.SAME_JOB  # her alias satisfies a Marida Link


def test_link_ness_must_match() -> None:
    marida = pilots_from([MARIDA])
    plain = unit("GD01-097", "Plain", ap=4, hp=4)
    assert verdict(SMALL, plain, marida) is Verdict.DIFFERENT and verdict(plain, SMALL, marida) is Verdict.DIFFERENT


def test_critical_keywords_must_be_matched_and_offense_keywords_are_interchangeable() -> None:
    blocker = unit("GD01-001", "Blocker", text="<Blocker> (Rest this Unit to change the attack target to it.)")
    breach = unit("GD01-002", "Breacher", text="<Breach 2> (...)", ap=3, hp=3)
    suppression = unit("GD01-003", "Suppressor", text="<Suppression> (...)")
    high_maneuver = unit("GD01-004", "Maneuverer", text="<High-Maneuver> (...)")
    vanilla = unit("GD01-005", "Vanilla")
    assert verdict(blocker, vanilla, ()) is Verdict.DIFFERENT  # a Blocker's job is blocking
    assert verdict(blocker, breach, ()) is Verdict.DIFFERENT
    assert verdict(breach, suppression, ()) is Verdict.SAME_JOB and verdict(breach, high_maneuver, ()) is Verdict.SAME_JOB
    assert verdict(vanilla, blocker, ()) is Verdict.SAME_JOB  # a better Y is welcome


def test_giving_up_a_good_to_have_needs_one_back_but_any_kind_will_do() -> None:
    damage = unit("GD01-011", "Damager", text="【Deploy】Deal 1 damage to 1 enemy Unit.")
    draw = unit("GD01-012", "Drawer", text="【Deploy】Draw 1.")
    debuff = unit("GD01-013", "Debuffer", text="【Deploy】Choose 1 enemy Unit. It gets AP-2.")
    both = unit("GD01-014", "Both", text="【Deploy】Deal 1 damage to 1 enemy Unit. Draw 1.")
    vanilla = unit("GD01-015", "Vanilla")
    assert verdict(debuff, draw, ()) is Verdict.SAME_JOB  # -AP for draw is fine
    assert verdict(damage, vanilla, ()) is Verdict.CLOSE  # gives something up and gets nothing
    assert verdict(both, draw, ()) is Verdict.CLOSE  # two lost, one gained
    assert verdict(draw, both, ()) is Verdict.SAME_JOB  # extras are fine


def test_color_is_not_part_of_the_match() -> None:
    red = unit("GD01-021", "Red", text="【Deploy】Draw 1.", color=Color.RED)
    blue = unit("GD01-022", "Blue", text="【Deploy】Draw 1.", color=Color.BLUE)
    assert verdict(red, blue, ()) is Verdict.SAME_JOB


def cmd(number: str, text: str, *, cost: int = 1, pilot_name: str | None = None) -> CommandCard:
    return command(number, f"Command {number}", text=text, color=Color.RED, cost=cost, pilot_name=pilot_name)


def test_effect_vocabulary_and_scope() -> None:
    assert effect_features("【Main】Choose 1 enemy Unit with 2 or less HP. Return it to its owner's hand.") == {"bounce"}
    assert effect_features("【Main】Look at the top 5 cards of your deck. You may reveal 1 Pilot card among them and add it to your hand.") == {"search"}
    assert effect_features("【Action】Choose 1 of your Units. It can't receive battle damage from enemy Units during this battle.") == {"protect"}
    assert effect_features("【Main】Deploy 2 [Zaku Ⅱ]((Zeon)･AP1･HP1) Unit tokens.") == {"tokens"}
    assert effect_features("【Main】Choose 1 Unit card from your trash. Deploy it rested.") == {"revive"}
    assert effect_features("【Action】Choose 1 rested friendly Unit. Change a battling enemy Unit's attack target to it.") == {"attack target"}
    assert effect_features("【Main】Place 1 rested Resource.") == {"ramp"}
    assert effect_features("【Main】Deal damage to it equal to the number of friendly Unit tokens in play.") == {"damage"}
    assert effect_features("【Main】Deal 2 damage to 1 enemy Unit.") == {"damage"}
    assert effect_features("【Main】Deal 1 damage to all enemy Units.") == {"damage all"}  # a different effect from damage to 1
    assert effect_features("【Main】Choose 1 of your Units. It gains <Breach 3> during this turn.", grants=True) == {"grant offense"}
    assert effect_features("【Main】Choose 1 of your Units. It gains <Repair 2> during this turn.", grants=True) == {"grant other"}


def test_a_command_needs_the_same_general_effect_and_scope() -> None:
    one = cmd("GD01-115", "【Main】/【Action】Choose 1 enemy Unit. Deal 1 damage to it.")
    area = cmd("GD01-108", "【Main】Deal 2 damage to all Units with <Blocker>.")
    draw = cmd("GD05-111", "【Main】Discard 1. If you do, draw 2.")
    unknown = cmd("GD01-999", "【Main】Something nobody has parsed yet.")
    unknown2 = cmd("GD01-998", "【Main】Another unparsed one.")
    assert verdict(one, area, ()) is Verdict.DIFFERENT  # damage to all is not damage to 1
    assert verdict(one, draw, ()) is Verdict.DIFFERENT
    assert verdict(unknown, unknown2, ()) is Verdict.DIFFERENT  # empty never equals empty


def test_command_size_may_be_one_lower_and_cost_one_higher() -> None:
    three = cmd("GD04-111", "【Main】Choose 1 enemy Unit. Deal 3 damage to it.", cost=2)
    two = cmd("GD04-112", "【Main】Choose 1 enemy Unit. Deal 2 damage to it.", cost=3)
    one = cmd("GD04-113", "【Main】Choose 1 enemy Unit. Deal 1 damage to it.", cost=2)
    dear = cmd("GD04-114", "【Main】Choose 1 enemy Unit. Deal 3 damage to it.", cost=4)
    assert verdict(three, two, ()) is Verdict.SAME_JOB  # X-1 and cost +1 are fine
    assert verdict(three, one, ()) is Verdict.CLOSE  # two lower is not almost as good
    assert verdict(three, dear, ()) is Verdict.CLOSE  # two more expensive
    assert verdict(one, three, ()) is Verdict.SAME_JOB  # better is welcome


def test_a_command_may_lose_one_good_to_have_but_not_two() -> None:
    both = cmd("GD01-112", "【Burst】Draw 1.\n【Main】/【Action】Choose 1 enemy Unit. Deal 3 damage to it.\n【Pilot】[Loni Garvey]", pilot_name="Loni Garvey")
    no_burst = cmd("GD01-113", "【Main】/【Action】Choose 1 enemy Unit. Deal 3 damage to it.\n【Pilot】[Loni Garvey]", pilot_name="Loni Garvey")
    bare = cmd("GD01-114", "【Main】/【Action】Choose 1 enemy Unit. Deal 3 damage to it.")
    main_only = cmd("GD01-115", "【Main】Choose 1 enemy Unit. Deal 3 damage to it.")
    assert verdict(both, no_burst, ()) is Verdict.SAME_JOB  # loses Burst: almost as good
    assert verdict(both, bare, ()) is Verdict.CLOSE  # loses Burst and the pilot pairing
    assert verdict(bare, main_only, ()) is Verdict.SAME_JOB  # loses Action timing only
    assert verdict(both, main_only, ()) is Verdict.CLOSE  # Burst, pilot and Action timing


def test_a_pilot_pairing_is_kept_only_if_it_serves_the_same_links_in_the_deck() -> None:
    loni = cmd("GD01-112", "【Main】Choose 1 enemy Unit. Deal 3 damage to it.\n【Pilot】[Loni Garvey]", pilot_name="Loni Garvey")
    nicol = cmd("GD01-116", "【Main】Choose 1 enemy Unit. Deal 3 damage to it.\n【Pilot】[Nicol Amarfi]", pilot_name="Nicol Amarfi")
    bare = cmd("GD01-117", "【Main】Choose 1 enemy Unit. Deal 3 damage to it.")
    serves_loni = unit("GD01-200", "Loni's Unit", link="Loni Garvey").link
    assert serves_loni is not None
    assert Matcher((), (serves_loni,)).stands_in(loni, nicol).verdict is Verdict.SAME_JOB  # lost the pilot pairing, only one thing lost
    assert Matcher((), (serves_loni,)).stands_in(loni, bare).verdict is Verdict.SAME_JOB
    assert Matcher().stands_in(loni, nicol).standing is Standing.EQUAL  # with no deck, any pilot pairing counts


def test_a_units_own_activated_grant_counts_as_its_keyword() -> None:
    banshee = unit("ST12-006", "Banshee", link="Marida Cruz", ap=5, hp=4, text="【During Pair】【Activate･Main】Exile 4 cards from your trash：This Unit gains <First Strike> and <Suppression>.")
    big = unit("GD01-044", "Kshatriya", link="Marida Cruz", ap=5, hp=4, text="【When Paired】Choose 1 enemy Unit. Deal 1 damage to it.")
    assert verdict(big, banshee, pilots_from([MARIDA])) is Verdict.SAME_JOB  # gives up damage, gets First Strike and an Offense keyword


def test_a_pilot_stands_in_for_another_when_it_serves_the_same_links_in_the_deck() -> None:
    marida_link = unit("GD01-044", "Kshatriya", link="Marida Cruz").link
    trait_link = unit("GD01-051", "Kshatriya", link_trait="Cyber-Newtype").link
    assert marida_link is not None and trait_link is not None
    other = pilot("GD01-070", "Someone Else", traits=("Newtype",))
    deck = Matcher((), (marida_link, trait_link))
    assert deck.stands_in(MARIDA, PLE_TWELVE).verdict is Verdict.SAME_JOB  # her alias serves the Marida Link, her trait the Cyber-Newtype one
    assert deck.stands_in(MARIDA, other).verdict is Verdict.DIFFERENT  # serves neither
    assert deck.stands_in(PLE_TWELVE, MARIDA).verdict is Verdict.SAME_JOB


def test_with_no_deck_pilots_share_a_name_or_a_link_relevant_trait() -> None:
    cyber = pilot("GD01-071", "Cyber Pilot", traits=("Cyber-Newtype", "Support"))
    flavor = pilot("GD01-072", "Support Pilot", traits=("Support",))
    relevant = frozenset({Trait("Cyber-Newtype")})
    matcher = Matcher((), (), relevant)
    assert matcher.stands_in(MARIDA, cyber).verdict is Verdict.SAME_JOB  # both Cyber-Newtype, which a Unit's Link asks for
    assert matcher.stands_in(cyber, flavor).verdict is Verdict.DIFFERENT  # Support is a flavor trait no Link asks for
    assert matcher.stands_in(MARIDA, PLE_TWELVE).verdict is Verdict.SAME_JOB
    assert Matcher().stands_in(cyber, flavor).verdict is Verdict.SAME_JOB  # with no list of relevant traits, any shared trait counts


def test_a_command_with_a_pilot_effect_is_a_pilot_and_text_and_stats_are_ignored() -> None:
    loni = command("GD01-112", "Extreme Hatred", text="【Main】Deal 3 damage.", pilot_name="Marida Cruz", traits=("Cyber-Newtype",))
    assert Matcher().stands_in(MARIDA, loni).verdict is Verdict.SAME_JOB
    assert Matcher().stands_in(loni, MARIDA).verdict is Verdict.SAME_JOB
    plain = command("GD01-113", "Plain Command", text="【Main】Deal 3 damage.")
    assert Matcher().stands_in(MARIDA, plain).verdict is Verdict.DIFFERENT  # no pilot effect: not a pilot


def test_bases_match_on_effect_only() -> None:
    deploy = "【Burst】Deploy this card.\n【Deploy】Add 1 of your Shields to your hand.\n"
    draws = base("GD01-123", "Nahel Argama", text=deploy + "【Once per Turn】When a Unit is destroyed, draw 1.", hp=5, cost=1)
    also_draws = base("GD01-124", "Side 7", text=deploy + "【Activate･Main】Rest this Base：Draw 2.", hp=4, cost=2, level=5)
    damages = base("GD01-125", "Shield Wall", text=deploy + "【Main】Deal 1 damage to all enemy Units.")
    plain = base("GD01-126", "Plain Base", text=deploy)
    matcher = Matcher()
    assert matcher.stands_in(draws, also_draws).verdict is Verdict.SAME_JOB  # HP, cost and size are ignored
    assert matcher.stands_in(draws, damages).verdict is Verdict.DIFFERENT
    assert matcher.stands_in(draws, plain).verdict is Verdict.DIFFERENT  # the baseline every Base has is not an effect
    assert effect_features("【Deploy】Add 1 of your Shields to your hand.") == {"search"}  # (the reader sees it; base_core_text removes it for Bases)
