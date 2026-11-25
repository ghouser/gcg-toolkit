# release-event-promo: design

Spec: `claude-workspace/specs/gcg-toolkit/release-event-promo/spec.md` (PersonalClaude workspace), approved 2026-11-25.

## Approach
**One wording rule, in one place.** A new small module `tools/gundam_cards/events.py` holds the only definition of what "names an
event" means: `names_release_event(where_to_get: str) -> bool`, built on one compiled, case-insensitive regex. `build_printing`
asks it first: a printing whose "Where to get it" names an event gets set code `PROMO` (the code `sets.json` already has), whatever
bracketed code the text mentions; otherwise the set code is read as today (bracket, then package). The export's card-level
reference printing asks the same function, so the two never disagree. Both rebuilds (`reparse`, `refresh`) go through
`build_printing`, so they give the same result by construction.

**The wording the rule recognizes** (matched anywhere in the text, case-insensitive, any run of spaces or a hyphen where the
patterns below show `[-\s]`):
- a **release event**: `release event` or `release events` (`Booster Pack ... [GD05] Release Event ...`, `Starter Deck [ST07]/[ST08] Release Event`);
- a **pre-release event**: `pre-release event(s)`, and the spelling variants `Pre Release Event`, `Prerelease Event` (the pattern is
  `pre[-\s]?release[-\s]+events?`; a bare `release event` is already covered, so "pre-release" needs no pattern of its own beyond
  being a release event);
- **event-participation items**: `items for participants` (`Commemorative Items for Participants`) and `event participation`
  (`Event Participation Items`, `Event-Participation Prize`).
Case never matters (`RELEASE EVENT`, `release event`). The pattern is
`\b(?:(?:pre[-\s]?)?release[-\s]+events?|event[-\s]+participation|items?\s+for\s+participants?)\b`.
Not recognized, so unchanged: a bare "Event" (`Regional Event`, `Store Event`: these are promo-package printings and get PROMO through
their package when they carry no bracket; with a bracket they are out of this spec), "tournament", "participants" alone,
"Edition Beta", and any text that names no event.
The wording is based only on the two wordings in the spec and the small existing fixtures; it was not checked against the real
texts (the owner verifies it with a `reparse` after landing, and the pattern is the one line to adjust if a real text differs).

**Open question 2 (an ordinary text that mentions an event in passing): the event wording wins**, as the spec proposes: the rule
looks only for the wording, so such a printing is PROMO. This is the consequence of a general rule on wording and is accepted.

**Card level.** `ExportCard.set_code` is today the set of the first printing that is not Beta. It becomes the set of the first
printing that is neither Beta nor a release-event printing (`names_release_event(where_to_get)`), in the card's printing order; when
every printing is Beta or an event printing, it falls back to the first non-Beta printing (so the card is PROMO; never invented);
when there is none, omitted as today. A card with a booster printing then an event printing (GD05-042) stays GD05.

**Why not the obvious alternatives.** A per-set list of events is out of scope and would need maintenance for every
pre-release. Deciding the event by package (promo package) fails for the printings in question, which sit in the booster's package
or carry a bracketed code. Storing a flag on `Printing` would change the stored shape (`schema_version`); the card-level rule can
instead re-read `where_to_get`, which the catalog already stores, with the same function.

## Files and interfaces
- `tools/gundam_cards/events.py` (new): `names_release_event(where_to_get: str) -> bool` and the one pattern (private).
- `tools/gundam_cards/build.py`: `_set_code` returns `PROMO` first when `names_release_event(where)`; the `PROMO` code is a named constant.
- `tools/gundam_cards/export.py`: `_reference_set_code` skips event printings as well as Beta, with the fallback above.
- `tools/gundam_cards/models.py`: the `Printing.set_code` comment says an event printing is `PROMO`.
- Docs: `docs/catalog-export.md` (card and printing `set_code` rows), `tools/gundam_cards/design.md` ("Where to get it" finding,
  model comment, export row, price matching note), `docs/commands.md` (one-time anomaly-guard note), `.claude/CLAUDE.md` set-code domain note.
  `shared/data/gundam_cards/sets.json` is not touched.

## Tests
Small invented fixtures; expected values worked out by hand. Unit tests (`tools/gundam_cards/tests/test_release_event_promo.py`) call
`build_card` with a fixture page and package map as `test_package_set_codes.py` does; one CLI test goes through `sync`/`reparse`/`export`
on the in-memory Bandai fake.
- AC-1
  - GD05 wording (happy): `Booster Pack Freedom Ascension [GD05] Release Event Commemorative Items for Participants` -> PROMO.
  - ST07 wording with two codes (happy): `Starter Deck [ST07]/[ST08] Release Event` -> PROMO.
  - invented pre-release wording (happy, not a list of sets): `Booster Pack Invented Dawn [GD09] Pre-Release Event` -> PROMO; variants `Prerelease Event`,
    `Pre Release Events` and any case (`RELEASE EVENT`) -> PROMO; `Event Participation Items` with a bracket -> PROMO.
  - event wording wins over an ordinary booster package (happy): bracket plus event, package GD05 -> PROMO.
  - non-event cases keep their code (unhappy side): `Booster Pack Freedom Ascension [GD05]` -> GD05; a starter text -> its set;
    `Edition Beta` in the Beta package -> BETA; `-` in the GD02 package -> GD02; `[SC01]` reprint -> SC01; an alt-art printing of a
    booster (rarity `C +`) -> the booster's set; a bare `Regional Event [GD05]` -> GD05 (not matched).
  - after `reparse` and in the export (happy): the printing is PROMO in `cards.json` and in the export at printing level.
  - `refresh` gives the same as `reparse` (happy): a refresh of the same fake data yields the same printing set codes.
- AC-2 (`test_export.py` style, built catalogs)
  - booster then event printing -> card `GD05`; ST07-style starter then event -> `ST07` (both sides).
  - event printing first, booster second -> the booster's set (the skip is by kind, not by position).
  - only event printings -> PROMO; Beta then event -> PROMO (fallback to first non-Beta); Beta only -> omitted (unchanged).
- AC-3
  - after `reparse` and `export` the file validates, every printing and card set code is in `reference.sets`, and the tracked
    `sets.json` bytes are unchanged.
- AC-4 (`test_refresh_prices.py` style)
  - a card with a GD05 booster printing and an event printing mentioning [GD05], one product in the GD05 group with its Number: it
    matches exactly the booster printing, is not reported ambiguous, gets a price row; in the export the booster printing has the
    price and the event printing none. (Also the no-rule baseline reasoning: the same data before the rule would be ambiguous; pinned by the unit test of `printing_prices`.)
- AC-5: docs checked by review (tests do not scan docs, `docs/testing.md`).

## Risks
- **The wording is not verified on the real texts.** A real text whose event wording differs (another spelling, "Launch Event") is
  not caught and keeps its set code; a real ordinary text that contains one of the phrases would become PROMO. The owner's
  `reparse` plus the price run shows the remaining refusals; the pattern is one line in `events.py`.
- **An ordinary text mentioning an event in passing becomes PROMO** (accepted, see the open question).
- **More printings change set code**, so the first `refresh` after this may be refused by the anomaly guard; one time: `reparse`, or
  `refresh --allow-anomaly` after the `--dry-run` report. Noted in `docs/commands.md`.
- **Dating and ranking.** A PROMO printing's release date is PROMO's, not the booster's: text-version `as_of` and the "which text wins" ranking read printing set codes, so a wording that now has only an event printing may date differently.
- **Prices.** Event printings no longer match a product in the booster's group (that is the aim); they get no price, as promos do.
- Contracts made stricter: none. Types, fields and `schema_version` are unchanged; `build_printing`'s signature is unchanged.
