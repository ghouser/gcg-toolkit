# The catalog export (contract for other apps)

The toolkit publishes its card catalog as one JSON file for apps that only read it (the UI). This document is the contract: the identifier shapes, every field, the version policy and where the file lives. Two files beside it are meant to be copied into other apps' tests:

- `docs/catalog-export.example.json`: a small, valid export.
- `docs/identifier-examples.json`: valid and invalid card numbers, printing ids and set codes, for parser tests. The toolkit's own types are tested against it (`shared/test_identifier_examples.py`).

## Writing it

    .venv/bin/python -m tools.gundam_cards.cli export

Only this command writes the file, and only when it is run (a refresh does not). It goes to `$GCG_CATALOG_FILE`, or `~/.gcg/catalog.json` when the variable is unset. It is written to a temporary file and renamed over the old one, so a reader never sees a half-written file and a failed run leaves the earlier export as it was. The command refuses to write (exit 1, naming the codes) when a printing carries a set code that is not in `reference.sets`.

## Identifiers

These are the only definitions of the identifier shapes; the toolkit's `shared/basetypes.py` implements them. All are case-sensitive and match the whole string (no surrounding spaces).

| Identifier | Shape (regular expression) | Examples | Identifies |
|---|---|---|---|
| Card number | `[A-Z]+[0-9]*-[0-9]{3}` | `ST01-001`, `GD05-111`, `R-016` (resource), `T-022` (token), `EXB-002`, `EXBP-001` | a card: one name and text, whatever its printings |
| Printing id | `[A-Z]+[0-9]*-[0-9]{3}(_p[0-9]+)?` | `ST01-001` (base printing), `ST01-001_p5` (variant 5) | one printing of a card; the part before `_p` is its card number |
| Set code | `[A-Z][A-Z0-9]+` | `GD05`, `ST11`, `EB01`, `SC01`, `PB03`, `EVX01`, `PROMO`, `BETA` | a set (product or package); synthetic codes such as `PROMO`, `BETA`, `BASIC`, `OTHER` stand for packages without one |

A printing id without `_p<N>` is the card's base printing. A few cards are listed only as variants (`R-001_p4`), so a card's first printing is not always a base printing.

## The file

A JSON object. **A field that does not apply is left out; the file never contains `null`.** Dates are `YYYY-MM-DD`; times are ISO 8601 in UTC. Money is integer US cents.

| Field | Type | Meaning |
|---|---|---|
| `schema_version` | integer | `1` (see Version policy) |
| `generated_at` | time | when the export was written |
| `reference` | object | the toolkit's vocabularies (below); an app reads them from here and never hardcodes them |
| `cards` | array of card | every card in the catalog, by card number, including cards the source no longer lists |

### `reference`

| Field | Type | Meaning |
|---|---|---|
| `sets` | array of set | every known set, by code; every set code in `cards` is one of them |
| `kinds` | array of `{kind, deck}` | every card kind, with `deck: true` for those that go in a deck (`unit`, `pilot`, `command`, `base`) and `false` for the others (`ex_base`, `resource`, `ex_resource`, `unit_token`, `base_token`) |
| `colors` | array of string | the card colors (`blue`, `green`, `white`, `red`, `purple`) |
| `rarities` | array of string | the rarities (`C`, `U`, `R`, `LR`, `P`). Alt-art marks (`+`, `++`) and Link art (`LK`) are not rarities: see a printing's `alt_art_level` and `link_art` |

A set:

| Field | Type | Present | Meaning |
|---|---|---|---|
| `code` | set code | always | |
| `name` | string | always | display name ("Newtype Rising") |
| `kind` | string | always | `booster`, `starter`, `extra_booster`, `deck_build_box`, `promo`, `beta` or `other` |
| `release_date` | date | when known | may be in the future (announced sets) |
| `provisional` | `true` | only when true | found by a catalog refresh but not yet in the toolkit's reviewed set list; its `name` is Bandai's |

### A card

| Field | Type | Present | Meaning |
|---|---|---|---|
| `number` | card number | always | |
| `name` | string | always | |
| `kind` | string | always | one of `reference.kinds` |
| `no_longer_listed` | `true` | only when true | the source no longer lists the card; its last known data is kept |
| `set_code` | set code | when known | the set of its first printing that is not Edition Beta (set code `BETA`, teaching copies never bought or sold); absent when that printing has no set code or every printing is Edition Beta |
| `color`, `level`, `cost` | string, integer, integer | deck kinds only | |
| `printings` | array of printing | always (at least one) | the base printing first, then by variant number |

### A printing

| Field | Type | Present | Meaning |
|---|---|---|---|
| `id` | printing id | always | |
| `rarity` | string | always | one of `reference.rarities` |
| `set_code` | set code | when known | the set this printing comes from (a reprint's differs from the card's): the code Bandai names in brackets, else the set of its package (`PROMO` for promos, `BETA` for Edition Beta) |
| `variant` | integer | not on a base printing | `N` of `_pN` |
| `alt_art_level` | integer | not on a base printing | `0` normal art, `1` "+", `2` "++" |
| `link_art` | boolean | not on a base printing | Link art ("LK"): shows the linked pilot with the Unit |
| `image_url` | string | when known | Bandai's image of this printing |
| `price_cents` | integer | when priced | latest TCGPlayer market price of this printing |
| `price_as_of` | date | with `price_cents` | when that price was pulled |

There is no card-level price, and no card text, stats, traits or keywords (later versions may add them; see below).

Until the toolkit stores prices per printing, it holds one price per card (its cheapest non-alt-art TCGPlayer product, with that product's set); that price is given to the card's one non-alt-art printing from that set, and to no printing when there is no such printing or more than one.

## Version policy

- `schema_version` changes only for a **breaking** change: a field removed or renamed, made required where it was optional, or its type or meaning changed.
- Not breaking: adding an optional field (readers ignore fields they do not know), and new sets, kinds, colors or rarities, which appear in `reference` (readers take them from there).
- A reader accepts the versions it was written for and refuses any other with a clear message; it never guesses.
- Each version is documented here; the example file always shows the current one.
