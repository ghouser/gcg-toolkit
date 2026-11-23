# promo-beta-set-codes: design

Spec: `claude-workspace/specs/gcg-toolkit/promo-beta-set-codes/spec.md` (PersonalClaude workspace), approved 2026-11-23.

## Approach
**Printing set code: bracket first, then the package.** `build_printing` keeps reading a bracketed code from "Where to get it"; when
there is none, it takes the code of the first of the printing's `package_ids` (in the order the printing lists them) that a
package-to-code map knows. The map comes from the reviewed `sets.json` only (`bandai_package_id` -> `code`), built by a small pure
function in `store.py` next to `release_dates`, and is passed into `build_catalog` by both rebuilds (`reparse` and `refresh`). A
package the map lacks, or a missing `sets.json` (an empty map), leaves the set code `None` as today, with no issue and no failure.
The provisional sets are deliberately not in the map: the spec ties the fallback to `sets.json`, and every code the map can give is
then in the export's `reference.sets` by construction. Edition Beta needs no special case in the build: `sets.json` maps 616000 to
`BETA`, so AC-2 is AC-1 applied to that package (on the real cache no Beta printing has a bracketed code, so the bracket rule never
hides a Beta printing).
The basic package (616801) maps to `BASIC` the same way, so a starter-deck basic's basic-package printing gets `BASIC`.

**Card set code: the reference printing skips Beta.** The only card-level set code is the export's `ExportCard.set_code`, today
`card.printings[0].set_code`. It becomes the set code of the first printing (catalog order, unchanged) whose set code is not `BETA`;
when there is none (a Beta-only card, which the spec drops as non-existent), the field is omitted, as the contract already allows.
Printings keep `BETA` in the catalog and the export. The starter-deck basics (`EXB-001`, `EXR-001`, `R-001`: Beta first, then the
basic package, then a bracketed `SC01` reprint) therefore resolve to `BASIC` by design: the owner wants the basic cards given in
the starter decks to show `BASIC`, not the first booster `SC01` (spec change log, 2026-11-23). This lives in `export.py` because nothing else reads a card-level set code;
the catalog model is unchanged (the spec changes no stored shape and keeps `schema_version` 1).

**Why not the obvious alternatives.** Writing the fallback into `sets.json` (or adding sets) is out of scope and AC-4 forbids any
write. Using `load_sets()` (tracked plus provisional) would give codes for packages `sets.json` lacks, which AC-4 says stay
code-less. Choosing a card's reference printing by set kind (`SetKind.BETA`) would need the set list in the export's card mapping;
the spec states the rule by code (`BETA`), so the code is compared directly.

## Files and interfaces
- `tools/gundam_cards/build.py`: `build_printing(page, package_codes)` falls back to the first known package's code;
  `build_card(pages, traits, release_dates, package_codes=None)` (None: no package known) and
  `build_catalog(pages, release_dates, package_codes)` (required: both commands must pass it) pass it down.
- `tools/gundam_cards/store.py`: `package_set_codes(sets: tuple[CardSet, ...]) -> dict[PackageId, SetCode]`.
- `tools/gundam_cards/cli.py` (`cmd_reparse`) and `tools/gundam_cards/refresh.py` (`refresh_catalog`): pass
  `package_set_codes(<tracked sets.json>)`.
- `tools/gundam_cards/export.py`: the card's `set_code` is its reference printing's (first non-`BETA`).
- `tools/gundam_cards/models.py`: the `Printing.set_code` comment says where the code comes from.
- `tools/gundam_cards/tests/test_corpus.py` (real-data only): passes the package map like the commands do.
- Docs: `docs/catalog-export.md` (card `set_code` row: the set of its first printing that is not Edition Beta; the printing row:
  from the bracket, else the package), `tools/gundam_cards/design.md` (printing model comment, "Where to get it" finding, the export
  row), the set-code line of `.claude/CLAUDE.md`'s domain notes (`docs/glossary.md` and `docs/commands.md` do not describe set
  codes), and the superseded statement in
  `.claude/feature-design/shared-data-contracts.md` marked inline, as the repo marks superseded decisions (`tools/gundam_collection/design.md`).
  `docs/catalog-export.example.json` stays as it is: its ST01 cards are unchanged, and its `R-001` is a cut-down card (one
  printing, no set code) that shows a card without a `set_code`, which the contract still allows; it names no `SC01` or `BETA`.

## Tests
Unit tests call `build_card` with fixture pages whose "Where to get it" and `package_ids` are set by hand; CLI tests run `sync`,
`reparse`, `refresh` and `export` through `main` against the in-memory Bandai fake (`test_catalog_refresh.FakeBandai`) in the root
conftest's temp folders. Expected values are worked out by hand from the fixture map: 616101 GD01, 616102 GD02, 616301 SC01,
616801 BASIC, 616901 PROMO, 616000 BETA.
- AC-1 (`tools/gundam_cards/tests/test_package_set_codes.py`)
  - bracketed code wins (happy): text `[GD01]`, package 616901 -> GD01.
  - promo package fallback (happy): text names an event, package 616901 -> PROMO.
  - "-" case (happy): text `-`, package 616102 -> GD02.
  - unknown package (unhappy): text without bracket, package 616999 -> no set code, no issue, card built.
  - no package ids at all (unhappy): -> no set code.
  - empty map, the missing `sets.json` case (unhappy): promo package -> no set code.
  - several package ids (both orders): (616999, 616102, 616901) -> GD02; (616901, 616102) -> PROMO; an unknown one listed first is skipped.
- AC-2
  - Beta package (happy): text `Edition Beta`, package 616000 -> BETA, and the printing equals the one built without the map except
    for `set_code` (every other field unchanged).
- AC-3 (`tools/gundam_cards/tests/test_export.py`)
  - Beta first, then a BASIC-package printing, then a bracketed SC01 (happy, the starter-deck basics): card `set_code` BASIC (not
    SC01, not BETA); the Beta printing still carries BETA in the export, the others BASIC and SC01.
  - first printing not Beta (both sides): [GD01, BETA] -> GD01, unchanged.
  - existing test: a first printing with no set code (and no Beta) -> card has no `set_code`.
  - Beta-only card (edge the spec drops): `set_code` omitted, no failure.
- AC-4 (`test_package_set_codes.py`, CLI)
  - `reparse` and `refresh` (parametrized) leave the tracked `sets.json` byte-identical, with a printing in a package `sets.json`
    lacks (a new `[GD99]` package that the rebuild records as provisional): that printing has no set code (its text has no bracket),
    and the provisional record and report line are what they would be anyway (GD99 provisional, the "N sets on Bandai's list, M
    provisional" line with hand-counted N and M).
  - missing `sets.json` (unhappy): `sync` then `reparse` exit 0, no printing gets a package code, and no `sets.json` is created.
- AC-5 (`test_package_set_codes.py`, CLI, after `reparse` and after `refresh`)
  - `export` exits 0 and the file validates as `CatalogExport`; every printing and card set code is in `reference.sets`.
  - printing level: the promo printing PROMO, the Beta printing BETA, the "-" printing GD02, a bracketed printing its bracket code.
  - card level: the Beta-first card (Beta, then a "Basic Cards" package printing with no bracket, then a bracketed SC01) BASIC, a
    plain card its first printing's code; printing level, its basic-package printing BASIC and its SC01 reprint SC01.
  - docs (`docs/catalog-export.md` wording, example file unchanged): checked by review, since tests do not scan docs (`docs/testing.md`).
- Real data (counts only, reported, not a test): cards without a card-level code and printings without a code before/after, PROMO,
  BETA and fallback GD02 counts, the card codes of EXB-001, EXR-001, R-001, R-018, R-019, T-012, and `sets.json` bytes unchanged.

## Risks
- **The starter-deck basics resolve to BASIC by design.** EXB-001, EXR-001 and R-001 skip their Beta printing and land on their
  basic-package printing (`BASIC`), not their later bracketed `SC01` reprint. That is the owner's decision, not an accident of
  printing order; the AC-3 tests pin it.
- **More printings are dated.** A printing with a fallback code now has a release date where its set has one (BETA 2024-12-07, the
  "-" printings' GD02). Text versions' `as_of`, the "which text wins" ranking within a block, and the packages tool's
  `introduced_dates` read printing set codes, so they can shift for those cards. Beta is block β (lowest rank) and its date is the
  oldest, so a Beta printing cannot make a wording newer; the "-" printings are resources and tokens. The real-data check counts
  the cards whose stored data changes beyond printing set codes.
- **Price matching.** `printing_prices` matches a price row to the one non-alt printing in the row's set; a printing that now has a
  code (GD02 resources) can now be priced where it was not. TCGPlayer's Beta and promo group codes (`GD01_b`, promo groups) differ
  from BETA/PROMO, so those never match, as before. Counted in the real-data check.
- **Package order.** "First known package" follows the printing's `package_ids` order (Bandai's package filter order on a rebuild,
  stored-then-listed on a refresh). On the real cache no printing has more than one package today.
- Contracts made stricter: none. The export's field, type and presence rule are unchanged (`schema_version` 1); `build_catalog`
  gains a required argument, and both of its callers (`cli.cmd_reparse`, `refresh.refresh_catalog`) and the real-data corpus test
  pass it.
