# Gundam Packages

**Status:** Agreed, implemented (see "Implementation status")
**Folder:** `tools/gundam_packages/`
**Backlog item:** workspace backlog > Packages and archetypes

## Purpose
Show how decks are really built. Per-card popularity (what Egman's meta page shows) is misleading in a game where decks are assembled from **packages**: Barbatos Adapt is "in 94% of purple decks" because it's one piece of the Barbatos package, not because it's the best card. This tool organizes decks **first into packages, then into archetypes**, and separates **solo** cards. Questions it answers:

- What are the popular packages, and which variants are played?
- How do packages combine into decks (archetypes)?
- Which cards are free-floating (good on their own), which are synergy with a package, and which do the same thing as each other?
- For one card: *what package is it part of, and in which archetypes?*
- How does a new era (new cards) change the packages?

## Definitions (decided)
Three **relations** between cards, all read from the card catalog (never from decks):

| Relation | Meaning | Where it comes from |
|----------|---------|---------------------|
| **Combo** | Must be played together: an ability that only works with another card, names another card, or needs a specific pilot | A Unit's named Link satisfied by a Pilot (`[Mikazuki Augus]`; a Command with a pilot effect counts as a pilot); card text that names another card (`a Unit with "Master Gundam" in its card name`). |
| **Synergy** | Work better together: similar keywords, similar abilities, or abilities that work together | An ability that **needs other cards** with a trait (Tekkadan); a trait Link; the same effect or native keyword on cards at a **different** level/cost. |
| **Functional reprint** (becoming **same job**: see the classification plan in the workspace backlog) | Cards that do the same job in a deck, so players run some of each. They are redundant, not substitutes: each keeps its own role. | Today: the same or a contained effect, or the same native keyword, at a similar level/cost, plus a same-name/kind/color rule that is a known mistake and is to be replaced by the structural job match. |

*(Superseded by "Same job" below: level and cost no longer decide it; AP/HP, Link, keywords and effect features do.)* **Reprint vs synergy** is decided by level and cost. The same ability at very different levels and costs means the cards aren't substitutes; they're meant to be played together. Tekkadan's "choose 1 of your Units and 1 enemy Unit, deal 1 damage to both" sits on Gusion Rebake (Lv5/cost4), Barbatos Adapt (Lv4/cost2) and Lupus (Lv7/cost6): **synergy**, and they can't carry a deck alone. Darkness Finger (Lv4/cost1) contains Close Combat's (Lv2/cost2) whole effect, but their levels differ by two: **synergy**, not a reprint. Close Combat and Battle of Aces (Lv3/cost2) are **reprints**. "Similar" is each within `SIMILAR_STATS_MAX_DIFF = 1` (a named constant in `functional.py`).

**Trait rule.** A trait is a synergy only when an ability needs **other** cards with it, and it involves more than one card. There is no size limit on traits. A card without the trait always needs others. A card with the trait counts only if the sentence says "another"/"other" or looks in the trash, hand or deck: Barbatos Lupus ("Choose 3 (Tekkadan)/(Teiwaz) Unit cards from your trash") ties the Tekkadan cards; Kapool ("a friendly (Marine) Unit is in play") is satisfied by Kapool itself, so there is no Marine package.

**Packages are one color.** A deck plays two colors, so a linked group that spans colors is split by color (the Master Asia group is a red package and a white Domon Shining package). Cross-color ties are not lost: they connect packages (below).

Three **tiers** for cards in a window:

| Tier | Meaning | Evidence required |
|------|---------|-------------------|
| **Package** | Cards that go together | Co-play (each implies the other in 80% of decks) **and** a tie of any relation. |
| **Synergy** | A card outside the package tied to it and played in its decks (Darkness Finger names "Master Gundam"). A card in a deck is there for a reason: it is part of a package or linked to one. | A tie of any relation to a member, and **any** appearance in the package's decks. Its **score** is the share of those decks (Flauros 75% of Tekkadan, Hobby Hizack 25% of Char). |
| **Free floating** | Good on its own, slotted in by color (Airframe Seizure, Overflowing Affection, Gundam Exia Repair) | No tie. Reported with **affinity**: which packages it is often played with, as information only. |

**Package synergy.** Two packages are *synergistic* when they are tied and decks run both: a direct tie between members, or a **bridge** card (outside both) with a tie to each that is in at least half of the decks running both. Strike Freedom (blue) + Tekkadan (purple): Strike Rouge (Ootori) is a Blocker that goes with both. It is in Tekkadan's decks only because they also run Strike Freedom (0 of the 4 Tekkadan decks without it), so it is reported as a bridge and **not** as Tekkadan's synergy card; it still stands on its own in Strike Freedom's decks (61% of those without Tekkadan). The rule: a synergy card is moved to bridge for package P when P's decks without the other package (at least 3 of them) are below 50% for that card.

An **archetype** is the set of packages a deck runs (Mikazuki Barbatos + Char Aznable). A **variant** is which optional members come with a package's core. **Reprint groups** list played cards that are functional reprints of each other, with the share of decks running at least one.

**Appearance rates** (why a card is played: package rate, card rate in a package, combined package rates, bridge rates, direct card and package lookup) are specified in [appearance-rates.md](appearance-rates.md) (agreed and implemented: `rates.json`, `package` and `card` lookups).

## Same job (decided 2026-10-08; replaces the text-overlap and same-name rules)

A **same-job** card is one that does what another card does in a deck, *almost as well*. Players run 4 of each, so same-job cards are **redundant, not substitutes**: each keeps its own role and copy need (goal 4 in `tools/gundam_collection/design.md`). The match is **directional**: "Y can stand in for X" does not mean the reverse (Kshatriya Besserung can stand in for the vanilla Kshatriya; the vanilla one cannot stand in for Besserung). Decks recorded in competition are assumed to play the best available, so the aim is alternatives that are *almost as good or better*. Better is welcome (more AP/HP, extra keywords or effects): only a worse card is rejected. The match records how Y compares with X (equal, better, or slightly worse) so a report can show upgrades, and since the aim is the cheapest acceptable card, a cheaper better card is a find. Structure, not text: no trigger, target or wording comparison, and no numbers inside effects ("deal X damage" is one feature whatever X is).

**Tier 1, hard gates (all must pass).**
- **Kind** is the same (Unit, Command, Pilot, Base).
- **Link-ness** matches: both have a Link or neither does (a Linked Unit is stronger than a plain one). If both do, Y's Link must be satisfied by the pilots that satisfy X's Link in the deck (or the package, when no deck is given). A pilot-name Link and a trait Link can both be satisfied by the same pilot (GD01-044 links to Marida Cruz; GD01-051 links to the trait Cyber-Newtype, which Marida has). **A pilot answers to every name it has**: a card that says "This card's name is also treated as [X]" (only Quattro Bajeena = Char Aznable, Milliardo Peacecraft = Zechs Merquise and Ple-Twelve = Marida Cruz so far) satisfies Links to X as well as its own name and traits. The alias is read from the card text by a helper (like `traits_of`) and every pilot in the deck is tested under all its names. Link satisfaction is therefore judged against the pilots the deck actually runs, so the same card can be an alternative in one deck and not in another.
- **Critical keywords.** Y must have every critical class X has. Classes: **Blocker**; **Offense = Breach, Suppression or High-Maneuver** (interchangeable: all of them push extra damage to shields).

**Tier 2, stat band** (Units only). Y's AP and HP are each at least X's minus 1 (more is fine). Level and cost never matter here; they are shown as information only. A 4/5 is never swapped for a 2/2.

**Tier 3, good-to-haves.** The good-to-have set of a card is its **keywords First Strike, Repair, Support, Development** and its **effect features**: deal damage, draw, +AP, -AP, destroy, recover HP, rest/set active. If Y lacks any good-to-have X has, Y must get back at least as many good-to-haves or critical keywords that X does not have (one for one: damage for draw is fine, -AP for draw is fine). Gaining extras is fine. Effect features come from a small vocabulary matched in the card text; they are not parsed further, and X is never compared.

**Color is not a gate.** A deck uses two colors and packages combine, so a blue Unit can stand in for a red one. It is valid only when the deck's colors include it; otherwise the report says "needs <color>" and does not count it.

**Commands have their own rules (decided 2026-10-08).** For Units the ability is a bonus ("we want *an* ability"); for Commands the ability is the card, so the effect must match and the looseness goes into the good-to-haves.
- **Same kind**, and the **same general effect**: only the 【Main】/【Action】 text counts (Burst and Pilot sections are separate). Y must share at least one core effect with X (draw with draw, damage with damage).
- **Scope is part of the effect.** An effect on *all* Units is a different effect from one on 1 Unit and is never interchangeable with it: damage / damage all, destroy / destroy all, +AP / +AP all, -AP / -AP all, recover / recover all, rest / rest all. It is the sentence of the effect that decides ("to all enemy Units", "all Units with <Blocker>", "each").
- **Size:** compare the main number of the shared effect; Y's must be at least X's minus 1 (more is fine). Targeting restrictions and wording are ignored.
- **Cost:** Y's cost is at most X's plus 1 (cheaper is fine). Level is ignored.
- **Good-to-haves for Commands:** Burst, a pilot pairing, Action timing (playable in 【Action】), and every other core effect X has that Y lacks. **Net loss of one is fine** (Burst for a pilot pairing is "almost as good"); losing two is not. Gains offset losses; better is welcome. A pilot pairing counts as kept only if Y's pilot satisfies a Link that X's pilot satisfies in the deck (with no deck, any pilot pairing counts).
- Units keep their rule: giving up a good-to-have needs one back (the Command rule is looser about *which* extras, stricter about the main effect).
- **Command effect vocabulary** (from reading all 157 Commands): damage, draw, +AP, -AP, destroy, recover, rest, plus bounce (return an enemy Unit to hand), search/retrieve (look at the top N and add to hand, or take a card from the trash), protect (cannot receive damage, reduce damage), tokens (deploy a Unit token), revive (deploy a Unit from the trash), attack-target control (redirect an attack, let a Unit choose an active target), grant keyword (*offense*: Breach / Suppression / High-Maneuver; *other*: anything else), ramp (place a Resource or EX Resource), deploy a Base. "Deal damage equal to the number of ..." counts as damage. A Command with no recognized effect never matches anything (never "empty equals empty"). Units use the same vocabulary for their effect features.

**Applying it to the package graph (decided: yes).** The package classifier will use the same rules instead of the text-overlap ones, with one check built in: the first version of this match tied 600 to 5,000 card pairs because Command matching was too coarse. The stricter Command rules above must bring the tie count down to a handful of groups per era (the old graph had 10 to 23 reprint groups); the build prints the counts before and after and the groups for review, and if they are still too many, the graph requires both directions to match (mutual) before it changes anything else.

**Squads (decided 2026-10-08; replaces "reprint groups").** A **squad** is a set of cards in which *every pair* are **peers**, and a card may be in several squads (Delta Plus sits with the Banshee in one and with Amuro's Gundam in another; they never share one). Two Units are **peers** when either can stand in for the other *and* their AP and HP are each within 1 of each other in both directions, so a 5/4 with an ability is a peer of another big Marida Unit with an ability (the purple Unicorn ST12-006, the blue Banshee GD01-003, Besserung) but not of the 3/4 vanilla Kshatriya, which stays a deck-level one-way alternative. Commands and Bases are peers when each can stand in for the other. Squads come from the peer relation as maximal cliques; the same relation drives the package graph. Measure first: if packages move noticeably, report it before changing anything else.

**Pilots: two different associations (decided 2026-10-08).** Pilots work *with* Units, so there are two relations and they must not be confused:
1. **Pairing** (a pilot and a Unit it Links; "who goes with whom"): not "replace". For a Unit it highlights the pilots that satisfy its Link (by name, alias or trait: Pilot cards *and* Commands with a Pilot effect), ranked by how often decks run them with it and by price; for a pilot it highlights the Units it Links. Getting the pair matters: a Linked Unit is stronger than a plain one, so an unpaired Link Unit is a gap in a deck. Pairing already exists as the `combo` ties (LINK_PILOT, LINK_TRAIT); the work is to surface it in `card` and in the deck report.
2. **Same job** (a pilot that can replace another): text is ignored (the pool is small). Y can stand in for X when it satisfies the same Links: in a deck, every Unit Link X satisfies among the deck's Units is also satisfied by Y; with no deck, they share a name (an alias counts) or a *Link-relevant* trait (a trait some Unit's Link asks for; flavor traits such as Support or Durability do not count). Y's AP and HP bonuses are each at least X's minus 1. Commands that carry a Pilot effect are pilots for this purpose (their name, traits and bonuses). Level and cost never matter.

**Bases (decided 2026-10-08): like Commands.** A Base is matched on its effect with the Command rules: a shared core effect (draw with draw), the size of the main number at most 1 lower, and net loss of one good-to-have. The baseline lines every Base has (the Burst "Deploy this card" and "Add 1 of your Shields to your hand") are not effects. Starting default, to confirm: Y's HP at least X's minus 1; cost ignored.

**Close, not same job.** A pair that passes the gates but fails the stat band or the swap rule is listed as *close* for review and kept as synergy. If a tier produces no matches at all, loosen it deliberately (it was set tight first).

**Evidence, never definition.** Observed co-play (decks running both, or one in place of the other) is shown alongside a match as support, and a same-job pair that no deck ever plays together is flagged; neither decides the match.

**Acceptance cases (they are the tests).** Kshatriya Besserung (GD03-005, blue 4/4, Repair 1, Deploy draw 1, $0.16) is a same-job alternative for both Kshatriya GD01-044 (red 5/4, $44.29) and GD01-051 (red 3/4, $0.11). For a blue/purple Marida deck, the purple Unicorn Gundam 02 Banshee (Destroy Mode) ST12-006 (5/4, First Strike, Suppression) the blue Besserung and the blue Unicorn Gundam 02 Banshee (Unicorn Mode) GD01-010 (4/3, rests an enemy Unit; HP 3 is on the edge of the band, $0.53) stand in for GD01-044, GD01-010 and Besserung also better the vanilla GD01-051; Delta Plus GD01-006 (blue 4/3, Repair, links to the trait Earth Federation) must NOT match in a plain Marida deck but MUST match in a deck that runs Ple-Twelve ST12-012, whose traits include Earth Federation and Cyber-Newtype and whose name is also treated as Marida Cruz, and the purple Rezin's Geara Doga GD05-056 (3/4 vanilla) stands in for GD01-051. Both Char's Zaku II and Close Combat / Improved Technique / Battle of Aces / Gundam Ariel's rest-a-Unit damage must come out as same job. Anything the rules disagree with the data on is printed for review, not decided silently.

**Built (2026-10-08): `shared/samejob/`** (one package: `vocabulary`, `result`, `matcher`, and one rule module per kind, `units`, `commands`, `pilots`, `bases`; entry point `Matcher.stands_in(x, y)`, directional; tests in `tests/test_samejob.py`). Units, Commands, Pilots (incl. Commands with a Pilot effect) and Bases all have rules; pilots ignore text, AP and HP; Bases ignore HP, effect size and cost. **Squads** replace reprint groups (`squads` in `packages.json`, schema 2; `squads` command): maximal sets in which every pair are peers (Units: either can stand in and AP/HP within 1 both ways; Commands and Bases: mutual; Pilots: either), a card may be in several. The package graph uses the same peer ties; one earlier tie is kept (Units with the same native role keywords are shared-keyword synergy whatever their Link). **Pairing** is separate (`pairing.py`, `pairs` command): the pilots that make a Unit Link and the Units a pilot Links, ranked by how often decks run them together. Result on GD05: 14 packages, 9 synergistic pairs, 32 archetypes (all as before), 125 ties; online: 33 packages, 23 pairs, 113 archetypes, about 128 squads (many overlap). Squads list *played* cards only; unplayed alternatives (Besserung for the big Kshatriya) come from the deck-level check. Not built yet: the collection tool's redundancy rework (reprints never merge slots; same-job alternatives only for cards real decks do not play in that role), which will call `Matcher`.

## Method (deterministic, no AI judgment)
Input: counted decks from `gundam_meta`'s **de-duplicated** events, **main deck only** (sideboards are separate tech), major and local tiers together, for one era.

1. **Link cards** that imply each other: strength = the smaller of P(a given b) and P(b given a) is at least 0.8, for cards in at least 6 decks. The minimum keeps staples out.
2. **Packages**: linked groups whose members are also tied (any relation); members with no tie to the rest fall out of the group (they become synergy or free floating).
3. **Deck runs a package** when it has at least 75% of its members and at least two ("cutting 1 card out of 4 is fine; running half isn't running the package").
4. **Synergy**, **free floating**, **roles** (core: in 90% of the package's decks; else optional), **variants**, **archetypes**, **reprint groups** as above.
5. **Color**: split each linked group by color first (a package is one color). **Package synergy**: pairs of packages with a direct tie or a bridge card, running together in at least half of the smaller one's decks (and at least 3 decks).
5b. **Drift**: take one era's packages as given and look at a later era's decks (below).
6. **Names**: pilot given name + unit core name (`Kira Strike Freedom`, `Mikazuki Barbatos`, `Ple-Twelve Unicorn`); the pilot's full name when they share a word (`Master Asia`, never "Master Master"); a package with no pilot is named after what its ties share (`Tekkadan`). `names.json` overrides any name by package id.

The effect and keyword matching is a **heuristic on card text** (content words after removing reminder text, timing tags and filler; dice >= 0.8 or containment >= 0.9 with at least 4 content words; native keywords are the `<Keyword>` lines at the top of the text). `card` shows the reason for every tie so it can be checked by eye; thresholds are named constants in `functional.py`.

## Windows and drift (decided)
Packages and archetypes are long-lived but change as cards arrive (Char is old, but new Zaku units he pairs with changed the Char package since GD04). So: **discover packages and archetypes for GD05, then measure how GD05.5 drifts.** For the new era's decks the tool reports:
- how many still run each package (before and after), and which core members fell out;
- **new cards** (introduced since the base era, from set release dates) that now go with a package: a tie plus presence in most of its decks;
- existing cards newly tied to a package (the **same synergy and bridge rules as the base window**: a tie, any appearance, bridges between packages that run together);
- every new card seen, with the package it mainly goes with, or "free floating so far" (Kapool);
- **emerging packages**: groups in the new decks that contain a new card and share fewer than two cards with an existing package (sharing two or more means an existing package growing).
A new era is small right after a release, so the minimum is relaxed to 3 decks. **Low samples are accepted and flagged**: metas change constantly, and a small window is still the best picture we have. Tracking this over time is a backlog item.

## What it found (GD05, 253 decks, 30 events)
14 packages (all one color), 9 synergistic package pairs, 124 synergy ties (with scores; `synergy --min-share 0.5` shows the strong ones), 30 free-floating cards (96 too rare to classify), 10 reprint groups, 32 archetypes. Synergistic pairs include Strike Freedom + Aile Strike, Master Asia + Domon Shining (always together), Mikazuki Barbatos + Tekkadan, and Strike Freedom + Tekkadan (bridge: Strike Rouge (Ootori)).

| Package | Decks | Members (ties) |
|---------|-------|----------------|
| Kira Strike Freedom | 110 (43%) | Strike Freedom Gundam, Kira Yamato (combo) |
| Kira Aile Strike | 94 (37%) | Aile Strike Gundam, Kira Yamato (ST04) (combo); Gundam Lfrith and Rick Dias as optional members (reprints of each other, and shared-keyword synergy with Aile Strike: white Blockers at different levels) |
| Amuro Ray | 85 (34%) | Gundam, Amuro Ray (combo) |
| Mikazuki Barbatos | 54 (21%) | Barbatos 1st Form, Barbatos Adapt, Mikazuki Augus (combo). Always all three. |
| Master Asia (red) + Domon Shining (white) | 42 (17%) each | Master Gundam + Master Asia (red); Shining Gundam, Gundam Maxter, Rising Gundam, Domon Kasshu, Shining Finger, Cyclone Punch (white). Always run together, so synergistic packages. |
| Üso V-Dash | 38 (15%) | Victory Gundam, V-Dash Gundam, Üso Ewin, Zoloat, Reineforce Jr. |
| Amuro Nu | 31 (12%) | Nu Gundam, Re-GZ, Jegan, Amuro Ray (GD05), Kayra's Re-GZ, Ra Cailum |
| Char Aznable | 28 (11%) | Char's Zaku II (two numbers: a reprint of itself), Zeong, Char Aznable |
| Tekkadan | 24 (9%) | Barbatos Lupus, Graze Custom, Hyakuren, Gusion Rebake: **3 synergy ties and nothing else** (an ability that needs other Tekkadan/Teiwaz cards) |
| Suletta Aerial Rebuild, Marida Kshatriya (red; the blue Unicorn 02 is synergy at 100%), Nyaan GQuuuuuuX, Andrew Waldfeld | 8-12 each | |

**Reprint groups** (an earlier name for **squads**: the `squads` command, `"squads"` in `packages.json`; the list below is from the old rule): white Blockers at similar level/cost (Aile Strike, Silver Bullet, Sword Strike, Freedom, Perfect Strike); Gundam Lfrith, Rick Dias, Flat, Gaplant; Unforeseen Incident and Cyclone Punch; blue Repair Units (Gundam, NT-1, V2 Gundam); Close Combat, Improved Technique and Battle of Aces; the same card under two numbers (Char's Zaku II, Zaku II, Victory Gundam).

**Cards you named.** *Kapool* has no package (its Marine check counts itself); in GD05.5 it is a new free-floating card in 26% of decks. *Airframe Seizure* and *Gundam Exia Repair* are free floating (no tie; Exia Repair's only tie is a Link to Setsuna, who isn't in these decks). *Darkness Finger* is synergy with the Master Asia package (its text names "Master Gundam", a combo tie; in 100% of its decks) and has **similar-ability synergy** with Close Combat and the other "deal damage" cards; it is not a reprint of any of them (different level/cost).

**GD05.5 drift** (6 events, 42 decks, low sample): Mikazuki Barbatos 21% -> 36%, Char Aznable 11% -> 21%, Amuro Nu 12% -> 0%; Suletta Mercury + Gundam Aerial (ST13) form an emerging package, a refresh of Suletta Aerial Rebuild.

## Usage
```
python3 -m tools.gundam_packages.cli build [--era gd05] [--tier all|major|local]   # discover and save
python3 -m tools.gundam_packages.cli packages | archetypes | package-synergy | synergy | free | squads | pairs
python3 -m tools.gundam_packages.cli card GD05-110     # package, archetypes, or free floating; plus its functional reprints
python3 -m tools.gundam_packages.cli drift --from gd05 --to gd05_5
python3 -m tools.gundam_packages.cli report --from gd05 --to gd05_5   # shared/data/gundam_packages/gd05_meta_report.md: decks by color combination + packages, then GD05.5 adjustments
```
(Run with `.venv/bin/python -m ...` from the repo root.)

## Outputs: `shared/data/gundam_packages/`
`packages.json` (`PackagesFile`: window, params, packages, package synergies with bridge cards, synergy cards, free floaters, archetypes, reprint groups) and `drift.json` (`DriftFile`). Typed models in `models.py` (frozen pydantic, `mypy --strict`). Package ids are `pkg:` plus the lowest member card number, so a package keeps its id across rebuilds. `tools/gundam_packages/names.json` holds hand-maintained nicknames.

## Decisions (confirmed with user)
1. Discover packages and archetypes for **GD05**, then measure **GD05.5 drift**. Low samples are accepted.
2. Thresholds: 80% mutual, at least 6 decks, a deck runs a package at 75% of its members and at least two.
3. **Sideboards are separate tech** and not used to discover packages.
4. **Package means synergy**, in three tiers: packages, synergy, free floating.
5. Names: pilot + unit pairs; shared words collapse.
6. **Three relations** with these meanings: combo (must be played together: an ability that only works with another card, names another card, or needs a specific pilot), synergy (work better together: similar keywords, similar abilities, abilities that work together), functional reprint (basically the same thing at a similar level and cost). The same ability at very different levels/costs is synergy, not a reprint. Functional reprints are strong ties (4 of A + 4 of B).
7. **Trait rule**: an ability that needs other cards, involving more than one card; **no size limit** on traits. A single card checking its own trait (Kapool/Marine) is not a package.

8. **Packages are one color; package synergy** links packages (a direct tie, or a bridge card). A card carried in by another package is a bridge, not synergy with the package it only rides along with. Cross-color keyword and ability synergy stays (a blue Blocker with a purple Blocker package).

9. **Synergy is any appearance with a tie, scored by share** (a card in a deck is there for a reason; Guntank-style stand-alone synergy is just a low score). Drift uses the same rules.

## Acceptance Checks (your examples are the tests, in `tests/test_corpus.py`)
- The Barbatos trio is one package, always all three. Strike Freedom + Kira, the Master Asia/Shining group, the Char, Marida and Nu Gundam groups are recovered. Tekkadan is a package of abilities that need other Tekkadan/Teiwaz cards.
- Kapool has no ties from its own text. Airframe Seizure, Gundam Exia Repair, A Show of Resolve, Overflowing Affection and Argama are free floating; Darkness Finger is synergy with the Master Asia package.
- Darkness Finger and Close Combat are in one reprint group; Gundam Lfrith and Rick Dias (white Blockers) join the Aile Strike package.
- Every package is one color. Strike Rouge (Ootori) bridges the Strike Freedom and Tekkadan packages and is not Tekkadan's synergy card.
- Every card is in at most one package; every package has at least one tie and at least 6 decks; a free-floating card is never also synergy.
- A deck runs a package with 3 of 4 members but not with 2 of 4.
- Rebuilding gives identical output; files round-trip through the typed models.
- GD05.5 drift: Kapool is a new, free-floating card; only cards introduced since GD05.5 began are "new"; the Barbatos package grew.

## Implementation status
Done: appearance rates (`rates.py`, `rates.json`, `package` lookup, rates in `card`), structural graph with three relations, discovery, one-color packages, package synergy and bridges, reprints, naming, archetypes, drift, CLI, tests (325 across the repo, `mypy --strict` clean). Not done: sideboard analysis; a `names.json` with real nicknames (the file exists and is empty); tracking packages over time.

## Online example decks, added 2026-10-08
The same analysis runs on **online decks**: the example decks, curated lists weighted by how much of the online field each matches (weights = archetype games x list share, and each archetype's list shares add up to 1, see `tools/gundam_meta/design.md`, "Example decks"). Our own discovery runs on them: packages, bridge cards, synergy and free-floating cards, archetypes, reprint groups, and all the appearance rates.

**How weights become decks.** The weights are turned into **10,000 whole "online decks"** by largest-remainder rounding (`build.apportion`: exact total, ties to the earlier list), each list repeated in proportion to its weight. Then the unchanged discovery and rates code applies, and every count reads as "out of 10,000 online decks" (one deck = 0.01% of the field). The unit is a stand-in for a share of the field, not a real deck; reports say "per 10,000 online decks".

**Parameters.** `ONLINE_PARAMS`: a card must be in at least 50 of the 10,000 decks (0.5% of the field; tournaments use 6 of about 250, a sample-size guard that does not carry over) to be considered; the 80% mutual co-play, 75% run share and 50% bridge share are unchanged.

**Outputs.** `packages_online.json` and `rates_online.json` (same models as the tournament files; `source: "online"`, and a window with no era or events). `build --source online` writes both; every lookup (`packages`, `package`, `card`, `synergy`, `package-synergy`, `free`, `reprints`, `archetypes`) takes `--source online`. `compare` matches the two sets of packages by shared cards (at least half of their combined cards are the same) and shows each package's rate in both.

**First results (example decks of 2026-10-08, GD05).** 523 lists carry weight; 33 packages, 22 package pairs with bridge cards, 317 synergy ties, 62 free-floating cards, 113 archetypes. Against tournaments: Marida Kshatriya is 21.1% of online decks but 4.3% of GD05 top-cut decks; Kira Strike Freedom 10.5% against 43.5%; Mikazuki Barbatos is the same (20.7% against 21.3%). Tekkadan and Nyaan GQuuuuuuX appear only in tournament decks; Suletta Aerial, Haman Qubeley, Full Neo Zeong and Athrun Aegis only online.

**Limits.** The lists are curated tournament decks used as stand-ins for the decks nearest to them; the resolution is 523 lists, so a card or pairing not in any list cannot appear. A package definition that needs all its members (the 75% rule on a 2-card package) reads lower than a signature-card count. These are approximations of the online field, good for ordering and for comparing with tournaments, not exact online play rates.

## Out of Scope
- Win rates, matchups, placement weighting (every top-cut deck counts equally).
- Online decks beyond the example lists: only per-card rates exist for the online field, not full lists.
- Prices and buying decisions (the store recommender will consume this).

## Open Questions
- **"Similar level/cost" is each within 1.** Is that the right tolerance? Close Combat (Lv2/cost2) and Battle of Aces (Lv3/cost2) pass; Darkness Finger (Lv4/cost1) doesn't.
- **The Master Asia package** is named "Domon Shining" (its most-played pilot/unit pair). To override, put `{"pkg:GD05-033": "Master Asia"}` under `data` in `tools/gundam_packages/names.json` (the file exists and is empty).
- **Ability-level synergy** (one card gives -X AP and another destroys units with 1 or less AP) is not detected. It would need per-ability parsing of card text; out of scope for now (backlog: more deterministic card-text understanding).
