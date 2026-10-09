"""Discovery on a synthetic world with a known answer."""
from __future__ import annotations

from shared.basetypes import CardNumber
from tools.gundam_packages.discover import DEFAULT_PARAMS, Discovery, discover, runs_package
from tools.gundam_packages.models import PackageId, Params, Role, SynergyEdge, SynergyKind
from tools.gundam_packages.synergy import SynergyGraph

N = CardNumber
A1, A2, A3 = N("GD01-001"), N("GD01-002"), N("GD01-003")  # package A: two units around one pilot
B1, B2, B3, B4 = N("GD02-001"), N("GD02-002"), N("GD02-003"), N("GD02-004")  # package B: a 4-card chain
S1, S2 = N("GD03-001"), N("GD03-002")  # staples: everywhere, no structural ties
F1, F2 = N("GD04-001"), N("GD04-002")  # a pair that always appears together but has no synergy
H, O = N("GD05-001"), N("GD05-002")  # H: tied to A1 (synergy); O: always with A but no tie to it

PARAMS = Params(min_decks=3, mutual_threshold=0.8, run_share=0.75, bridge_share=0.5)


def edge(a: CardNumber, b: CardNumber, kind: SynergyKind = SynergyKind.LINK_PILOT, detail: str = "x") -> SynergyEdge:
    return SynergyEdge(a=a, b=b, kind=kind, detail=detail)


GRAPH = SynergyGraph([
    edge(A1, A2), edge(A3, A2),
    edge(B1, B2, SynergyKind.TRAIT_REFERENCE), edge(B2, B3, SynergyKind.TRAIT_REFERENCE), edge(B3, B4, SynergyKind.TRAIT_REFERENCE),
    edge(H, A1, SynergyKind.NAME_REFERENCE, "Alpha"),
])  # fmt: skip


def world() -> list[frozenset[CardNumber]]:
    decks: list[frozenset[CardNumber]] = []
    for i in range(25):  # 20 A-only decks then 5 that also run B
        deck = {A1, A2, A3, O}
        if i % 2 == 0:
            deck.add(S2)
        if i < 14:
            deck.add(H)
        if i < 15:
            deck |= {F1, F2}
        if i >= 20:
            deck |= {B1, B2, B3, B4}
        decks.append(frozenset(deck))
    decks += [frozenset({B1, B2, B3, B4, S1}) for _ in range(21)]
    decks += [frozenset({B1, B2, B3, S1}) for _ in range(4)]  # 3 of 4: still runs the package (one card out is fine)
    decks += [frozenset({B1, B2, S1}) for _ in range(2)]  # 2 of 4: half the package is not running it
    decks += [frozenset({S1, N(f"GD06-{i:03d}")}) for i in range(8)]  # no package at all
    return decks


def run(decks: list[frozenset[CardNumber]] | None = None, params: Params = PARAMS) -> Discovery:
    return discover(decks if decks is not None else world(), GRAPH, params, {}, lambda pid, members, edges: str(pid))


def test_packages_need_both_co_play_and_synergy() -> None:
    result = run()
    packages = {p.id: p for p in result.packages}
    assert set(packages) == {PackageId("pkg:GD01-001"), PackageId("pkg:GD02-001")}
    a, b = packages[PackageId("pkg:GD01-001")], packages[PackageId("pkg:GD02-001")]
    assert {m.card_number for m in a.members} == {A1, A2, A3}
    assert {m.card_number for m in b.members} == {B1, B2, B3, B4}
    assert len(a.edges) == 2 and len(b.edges) == 3


def test_a_card_that_always_comes_along_but_has_no_synergy_is_not_in_the_package() -> None:
    result = run()
    assert O not in {m.card_number for p in result.packages for m in p.members}  # co-plays with A 100%, no structural tie
    floater = next(f for f in result.free_floating if f.card_number == O)
    assert floater.decks == 25 and [(a.package, a.share) for a in floater.affinities] == [(PackageId("pkg:GD01-001"), 1.0)]


def test_staples_and_unconnected_pairs_stay_free_floating() -> None:
    result = run()
    free = {f.card_number for f in result.free_floating}
    assert {S1, S2, F1, F2, O} <= free
    assert not {S1, S2, F1, F2} & {m.card_number for p in result.packages for m in p.members}
    pair = {f.card_number: f for f in result.free_floating}
    assert pair[F1].affinities and pair[F1].affinities[0].share == 15 / 25  # often with A, but only a co-play fact


def test_a_card_with_a_structural_tie_is_synergy_and_its_share_is_the_score() -> None:
    result = run()
    (h,) = result.synergy_cards
    assert (h.card_number, h.package, h.decks) == (H, PackageId("pkg:GD01-001"), 14) and h.share == 14 / 25
    assert [e.kind for e in h.edges] == [SynergyKind.NAME_REFERENCE]
    assert H not in {f.card_number for f in result.free_floating}  # classified once


def test_any_appearance_of_a_tied_card_is_synergy_but_an_untied_card_never_is() -> None:
    tied, untied = N("GD07-001"), N("GD07-002")
    graph = SynergyGraph([*GRAPH.edges_among([A1, A2, A3, B1, B2, B3, B4, H]), edge(tied, A2, SynergyKind.SIMILAR_ABILITY, "same effect")])
    decks = [*world(), frozenset({A1, A2, A3, tied, untied})]  # one deck of package A runs each; only `tied` has a tie to it
    result = discover(decks, graph, PARAMS, {}, lambda pid, members, edges: str(pid))
    found = {h.card_number: h for h in result.synergy_cards}
    assert found[tied].decks == 1 and found[tied].share == 1 / 26  # one deck is enough; the score says how rare
    assert untied not in found

def test_a_deck_runs_a_package_with_all_but_one_of_four_but_not_with_half() -> None:
    members = [B1, B2, B3, B4]
    assert runs_package(frozenset({B1, B2, B3}), members, 0.75)  # cutting 1 card out of 4 is fine
    assert not runs_package(frozenset({B1, B2}), members, 0.75)  # running half isn't running the package
    assert not runs_package(frozenset({B1}), [B1, B2], 0.75)  # and a single card never counts
    package = next(p for p in run().packages if p.id == "pkg:GD02-001")
    assert package.decks_running == 30 and package.decks_running_all == 26


def test_core_and_optional_members_and_variants() -> None:
    package = next(p for p in run().packages if p.id == "pkg:GD02-001")
    roles = {m.card_number: m.role for m in package.members}
    assert roles[B1] is Role.CORE and roles[B4] is Role.OPTIONAL  # B4 is in 26 of the 30 decks that run it
    assert {v.optional_members: v.decks for v in package.variants} == {(B4,): 26, (): 4}


def test_archetypes_are_the_combinations_of_packages_decks_run() -> None:
    result = run()
    by_packages = {frozenset(a.packages): a for a in result.archetypes}  # a package order is by popularity; the set is the identity
    a_id, b_id = PackageId("pkg:GD01-001"), PackageId("pkg:GD02-001")
    assert {k: v.decks for k, v in by_packages.items()} == {frozenset({a_id}): 20, frozenset({b_id}): 25, frozenset({a_id, b_id}): 5, frozenset(): 10}
    only_a = by_packages[frozenset({a_id})]
    assert [r.card_number for r in only_a.synergy_cards] == [H] and only_a.name == "pkg:GD01-001"
    assert by_packages[frozenset()].name == "No package"
    assert sum(a.share for a in result.archetypes) == 1.0
    typical_free = {r.card_number: r.share for r in only_a.free_floating}
    assert typical_free[O] == 1.0 and typical_free[S2] == 0.5  # S2 is in exactly half of these decks: typical at the 50% line


def test_rare_cards_are_counted_not_classified() -> None:
    result = run()
    assert result.rare_cards == 8  # the eight one-off filler cards
    assert not {f.card_number for f in result.free_floating} & {N(f"GD06-{i:03d}") for i in range(8)}


def test_results_are_deterministic_and_ordered() -> None:
    first, second = run(), run(list(reversed(world())))
    assert first == second
    assert [p.decks_running for p in first.packages] == sorted((p.decks_running for p in first.packages), reverse=True)
    assert first.free_floating == tuple(sorted(first.free_floating, key=lambda f: (-f.decks, f.card_number)))


def test_stricter_thresholds_find_fewer_packages() -> None:
    strict = Params(min_decks=40, mutual_threshold=0.8, run_share=0.75, bridge_share=0.5)
    assert run(params=strict).packages == ()  # nothing appears in 40 decks that is also tied together
    assert DEFAULT_PARAMS.min_decks == 6 and DEFAULT_PARAMS.mutual_threshold == 0.8 and DEFAULT_PARAMS.run_share == 0.75


# ---- functional reprints count as ties, and are reported as groups -------------------------------------------------
D1, D2 = N("GD07-001"), N("GD07-002")  # two cards that do the same job as each other, and as package A's units


def duplicate_world() -> tuple[list[frozenset[CardNumber]], SynergyGraph]:
    graph = SynergyGraph([edge(A1, A2), edge(A3, A2), edge(A1, D1, SynergyKind.FUNCTIONAL_EFFECT, "same job"), edge(D1, D2, SynergyKind.FUNCTIONAL_EFFECT, "same job"),
                          edge(A1, D2, SynergyKind.FUNCTIONAL_EFFECT, "same job")])  # fmt: skip
    decks = [frozenset({A1, A2, A3, D1, D2}) for _ in range(12)] + [frozenset({A1, A2, A3, D1})] + [frozenset({S1}) for _ in range(5)]
    return decks, graph


def test_a_functional_reprint_that_is_played_with_a_package_joins_it() -> None:
    decks, graph = duplicate_world()
    result = discover(decks, graph, PARAMS, {}, lambda pid, members, edges: str(pid))
    (package,) = result.packages
    assert {m.card_number for m in package.members} == {A1, A2, A3, D1, D2}  # "A strong tie is also an functional reprint"
    assert {e.kind.relation.value for e in package.edges} == {"combo", "functional_reprint"}


def test_peers_are_reported_as_squads() -> None:
    decks, graph = duplicate_world()
    result = discover(decks, graph, PARAMS, {}, lambda pid, members, edges: str(pid))
    (group,) = result.squads
    assert {c.card_number: c.decks for c in group.cards} == {A1: 13, D1: 13, D2: 12}
    assert group.decks_with_any == 13 and group.share_with_any == 13 / 18
    assert [k.value for k in group.kinds] == ["functional_effect"]


def test_a_chain_of_peers_is_two_squads_not_one() -> None:
    # A1-D1 and D1-D2 are peers but A1-D2 are not: D1 sits in two squads and A1 and D2 never share one.
    graph = SynergyGraph([edge(A1, A2), edge(A3, A2), edge(A1, D1, SynergyKind.FUNCTIONAL_EFFECT, "same job"), edge(D1, D2, SynergyKind.FUNCTIONAL_EFFECT, "same job")])
    decks = [frozenset({A1, A2, A3, D1, D2}) for _ in range(12)] + [frozenset({A1, A2, A3, D1})] + [frozenset({S1}) for _ in range(5)]
    result = discover(decks, graph, PARAMS, {}, lambda pid, members, edges: str(pid))
    assert sorted(sorted(c.card_number for c in g.cards) for g in result.squads) == sorted([sorted([A1, D1]), sorted([D1, D2])])


def test_worlds_without_duplicates_report_none() -> None:
    assert run().squads == ()
