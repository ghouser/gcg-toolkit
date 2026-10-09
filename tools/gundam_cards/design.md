# Gundam Cards

**Status:** Agreed, partially implemented (see "Implementation status"); the TCGPlayer price sync was agreed and implemented 2026-10-08
**Folder:** `tools/gundam_cards/`
**Backlog item:** workspace backlog > Gundam Card Catalog tool

## Purpose
Build and keep a local, searchable catalog of **every** Gundam Card Game card (not just ones seen in meta lists), scraped directly from Bandai's official English site. It is the single source of card identity and attributes for the other tools: card number to name, kind, color, stats, keywords, factions, text, set, and printings (including alt-art and promo versions), plus set release dates and a mapping to TCGPlayer products.

## Usage
```
python3 -m tools.gundam_cards.cli sync                       # fetch only cards/sets not already stored
python3 -m tools.gundam_cards.cli sync --package GD05        # one package
python3 -m tools.gundam_cards.cli search --name "Gundam" --color blue --kind unit --level 4
python3 -m tools.gundam_cards.cli search --keyword blocker --keyword main --trait "G Team"
python3 -m tools.gundam_cards.cli search --mentions-trait "Marine" --kind command --pilot   # commands with a pilot section
python3 -m tools.gundam_cards.cli search --text "recovers" --set ST01 --json
python3 -m tools.gundam_cards.cli show ST01-001              # one card with all printings
python3 -m tools.gundam_cards.cli sets                       # sets, kinds, release dates
python3 -m tools.gundam_cards.cli traits                     # trait (faction) vocabulary with counts
python3 -m tools.gundam_cards.cli refetch --card ST01-001    # or --package / --all, when data is suspect
python3 -m tools.gundam_cards.cli reparse                    # rebuild from saved raw HTML, no network
python3 -m tools.gundam_cards.cli sync-tcgplayer [--force]   # latest TCGPlayer market price per card, from tcgcsv (about 58 requests; skips if tcgcsv has nothing new)
python3 -m tools.gundam_cards.cli reparse-tcgplayer          # rebuild prices.json from the saved tcgcsv files, no network
python3 -m tools.gundam_cards.cli price GD05-002 [--explain] # a card's latest price; --explain lists every product considered (from the saved files)
```
`search` runs entirely against the local catalog: no network, instant, any combination of filters. Bandai is only contacted by `sync`/`refetch`.

## Inputs
- Network (only during sync): Bandai card site and product list; tcgcsv.com (a community export of TCGPlayer's catalog) for the TCGPlayer product mapping and market prices. TCGPlayer's own sites and APIs are never contacted (their terms forbid it; see `notes/source-terms.md`).

## Outputs
Shared dataset in `shared/data/gundam_cards/` (owned by this tool; other tools read these files per the contracts below, through the shared models, and never import this tool's parsing code). Raw HTML is cached in `tools/gundam_cards/data/raw/`.

| File | Format | Key | Fields | Consumers |
|------|--------|-----|--------|-----------|
| `cards.json` | JSON (envelope, see tool pattern) | card number | `Card` union below, including `printings` and `faq` | all tools |
| `sets.json` | JSON | set code | `CardSet` below | `gundam_meta` (eras), recommender |
| `prices.json` | JSON (envelope) | card number | `PriceFile` below: per card the **latest TCGPlayer market price in integer cents**, the product it came from, and when it was pulled. Latest only; replaced whole on each sync, never edited by hand. Joined onto the card model on read (`PricedCard`). | `gundam_collection` |
| `traits.json` | JSON | trait | generated vocabulary of traits (factions): name, card count, card numbers | parser (validation), search |
| `source_titles.json` | JSON | source title | generated vocabulary: TV series / game names, counts | parser (validation), search |

Internal schema: our own, not any site's. Card number is the identity. Printings hang off the card. Other tools never depend on Bandai's HTML shape or TCGPlayer's field names. Conventions (envelope, typed models, cents, UTC, no stale derived state) are in `docs/tool-pattern.md`.

## What the survey of the catalog showed
A crawl of all 1,149 base cards on 2026-10-06 (plus 24 sampled alt-art/promo printings) drove the model. Findings that shape it:

- **Eight card kinds, not four.** `UNIT` 600, `COMMAND` 157, `PILOT` 127, `BASE` 72, `RESOURCE` 107, `EX BASE` 29, `EX RESOURCE` 28, and tokens (`UNIT TOKEN` 27 plus a second spelling, `UNIT・TOKEN`, 2). Resources, EX cards, and tokens have no color, level, or cost, and aren't deck cards.
- **Command/Pilot hybrids are `COMMAND` cards with a pilot section** (68 of 157 commands). Their text ends with `【Pilot】[Pilot Name]`, and their `AP`/`HP` are signed bonuses (`+1`/`+1`) for when they're paired. They are not a separate `TYPE`. After playing the command you can pair it to a Unit as if it were that named pilot.
- **Card numbers have many shapes:** `GD05-111`, `ST01-001`, `EB01-076`, `R-016` (resources), `T-022` (tokens), `EXB-002`, `EXBP-001`, `EXR-004`, `EXRP-001`, `RP-001`.
- **Keywords: the Comprehensive Rules §13 is the authority** (v1.9.0). 21 keywords in two groups, both treated as one `Keyword` list. §13-1 "Keyword Effects" (`<...>`): Repair, Breach, Support, Blocker, First Strike, High-Maneuver, Suppression, Development. §13-2 "Keywords" (`【...】`): Activate･Main, Activate･Action, Main, Action, Burst, Deploy, Attack, Destroyed, When Paired, During Pair, When Linked, During Link, Once per Turn. Values (`Repair 2`) are dropped. `Development` rides inside another keyword (`【Deploy・Development 2】` is Deploy plus Development; the effect after `■` only happens if you exile that many of the named trait from your trash). `【Pilot】` is not a keyword; it marks a Command's pilot effect. Two tags can share a line: `【Main】/【Action】`. Some carry a pilot qualification (`【During Pair･(Vulture) Pilot】`, `【When Paired･Purple Pilot】`, `【During Pair･Lv.3 or Lower Pilot】`).
- **Traits** (what you call factions; the rules and Bandai both say "trait") are `(Trait)` tokens, 78 distinct so far (G Generation, Earth Federation, Zeon, ZAFT, Academy, Neo Zeon, Warship, CB, Newtype, Clan, G Team, ...). Units, pilots, bases, and pilot-commands carry them; a Pilot's traits are **not** added to its Unit (rules 2-5-5). Card text also references traits in parentheses (`friendly (G Generation) Unit`, `(Marine) Units`), and `/` in text means "or" (rules 5-19).
- **Link conditions** exist only on Units (rules 2-12, 3-2-6), as `[Pilot Name]`, `(Trait) Trait`, or alternatives separated by ` / ` (`(Newtype) Trait / (Cyber-Newtype) Trait`, `[Christina Mackenzie] / [Amuro Ray]`, `(Trinity) Trait / [Ali al-Saachez]`). Per the rules, a `[Name]` is satisfied when the pilot's card name **contains** that text. A Unit paired with a satisfying pilot is a Link Unit and can attack the turn it is deployed. Pilot names can contain parentheses and non-ASCII (`[Amate Yuzuriha (Machu)]`, `[Üso Ewin]`, `[Shuji Itō]`).
- **Rarity** has the base codes `C`, `U`, `R`, `LR`, `P` (promo). A trailing `+` or `++` (with a space) marks alt-art tiers: `C +`, `LR ++`. An **`LK` prefix** (`LKC +`, `LKU +`, `LKR +`; GD05 only) means **Link art**: an alt art that shows the linked pilot with the Unit. It is modeled as a flag on top of the underlying rarity and counts as an alt art. TCGPlayer writes `C+` and `UC` (for `U`).
- **Printings differ from the base card in more than rarity.** Across the full 2,011 printings: `block` (1, 2, or `β` for Edition Beta), the card text wording (rules rewordings, reminder text dropped, `-` meaning "no text"), and **source title** (an alt art usually shows a different series, sometimes spelled differently: `Mobile Suit Gundam UC` vs `Mobile Suit Gundam Unicorn`, `New Mobile Report Gundam Wing` vs `Mobile Suit Gundam Wing`). A few alt arts even differ in Link or stats (`Trait [Enhanced Human]` vs `(Cyber-Newtype) Trait`; token and Resource stats), and **Edition Beta stats look shifted/unreliable** (a Resource shows AP 3 / HP 1; tokens carry the neighbouring token's stats). So block, text, and source title are **per printing**, and the **newest wording is the card's text** (see "Which text wins").
- **Some card numbers exist only as alt arts**: `R-001`, `EXB-001`, `EXR-001` have no base page (Bandai returns an empty page for them), only `_pN` printings. The lowest-numbered alt art becomes the reference printing.
- **Dirty values:** fullwidth digits in a few stats (`３`, `１`), `-` for "none", names with zero-width spaces, a source title with a duplicated series name (`Mobile Suit Gundam Mobile Suit Gundam GQuuuuuuX`).
- **Where to get it** is free text; for set cards it ends in `[CODE]`, sometimes without a space (`Steel Requiem[GD03]`), for promos it is an event or product name.
- **Block** values: `1`, `2`, `β`, and `-`.
- Zones: `Space`, `Earth`, and `-` (none). Colors: Blue, Green, White, Red, Purple, and `-` (none).

## Data Models

Frozen pydantic v2 models, strict mode, checked with `mypy --strict`. No stringly-typed fields: closed vocabularies are enums, open ones are `NewType`s backed by generated vocabulary files, unions are tagged. Everything below is parsed at the boundary; code past the parser only sees these types. Anything the parser can't classify is quarantined in one explicit place (`unknown_tags` / a run-report warning), never silently coerced.

Terminology follows the **Comprehensive Rules** (v1.9.0, Sep 11 2026): a card's `Trait` is a "trait" everywhere in code, CLI, and docs (no "faction" alias), and keywords are the 21 defined in rules §13.

```python
# ---- shared/basetypes.py (NewTypes with validated formats) ------------------------------------
CardNumber   = NewType(...)  # pattern ^[A-Z]+\d*-\d{3}$   GD05-111, R-016, T-022, EXB-002
PrintingId   = NewType(...)  # CardNumber, optionally + "_p<N>"   ST01-001_p5
SetCode      = NewType(...)  # GD05, ST11, EB01, SC01, PB01, or a synthetic code for non-coded packages
PackageId    = NewType(...)  # Bandai package id "616105"
Trait        = NewType(str)  # open vocabulary; validated against traits.json   "G Generation", "Earth Federation"
PilotName    = NewType(str)  # "Amuro Ray", "Amate Yuzuriha (Machu)"
SourceTitle  = NewType(str)  # open vocabulary; validated against source_titles.json

# ---- closed vocabularies ------------------------------------------------------------------
class CardKind(StrEnum):
    UNIT = "unit"; PILOT = "pilot"; COMMAND = "command"; BASE = "base"
    EX_BASE = "ex_base"; RESOURCE = "resource"; EX_RESOURCE = "ex_resource"; UNIT_TOKEN = "unit_token"
    # "UNIT TOKEN" and "UNIT・TOKEN" both map to UNIT_TOKEN. An unseen TYPE fails the parse loudly.

class Color(StrEnum):   BLUE = "blue"; GREEN = "green"; WHITE = "white"; RED = "red"; PURPLE = "purple"
class Zone(StrEnum):    SPACE = "space"; EARTH = "earth"
class Rarity(StrEnum):  C = "C"; U = "U"; R = "R"; LR = "LR"; P = "P"      # "LK" prefix = Printing.link_art; "+"/"++" = Printing.alt_art_level

class Block(StrEnum):               # Bandai's block icon = the rules era a printing belongs to
    BETA = "β"; ONE = "1"; TWO = "2"
    # `rank` property: BETA 0 < ONE 1 < TWO 2. A new block value (e.g. "3") fails the parse loudly: it signals a new
    # rules era, which is exactly when card text and keywords may change and the enums need review.

class Keyword(StrEnum):             # ONE list, exactly the vocabulary of Comprehensive Rules section 13. No values (Repair 2 == Repair 3).
    # 13-1 Keyword Effects (<...> syntax)
    REPAIR = "repair"; BREACH = "breach"; SUPPORT = "support"; BLOCKER = "blocker"
    FIRST_STRIKE = "first_strike"; HIGH_MANEUVER = "high_maneuver"; SUPPRESSION = "suppression"; DEVELOPMENT = "development"
    # 13-2 Keywords (【...】 syntax)
    ACTIVATE_MAIN = "activate_main"; ACTIVATE_ACTION = "activate_action"; MAIN = "main"; ACTION = "action"
    BURST = "burst"; DEPLOY = "deploy"; ATTACK = "attack"; DESTROYED = "destroyed"
    WHEN_PAIRED = "when_paired"; DURING_PAIR = "during_pair"; WHEN_LINKED = "when_linked"; DURING_LINK = "during_link"
    ONCE_PER_TURN = "once_per_turn"
    # `is_keyword_effect` property: True for the 13-1 group. `【Pilot】` is NOT a keyword; it marks a Command's pilot effect (PilotProfile).

# ---- link condition (Units only, rules 2-12 / 3-2-6) --------------------------------------
class PilotNameLink(BaseModel, frozen=True):
    kind: Literal["pilot_name"]
    fragment: PilotName             # "[Amuro Ray]": satisfied if the pilot's card name CONTAINS this text (rules 3-2-6-4)

class TraitLink(BaseModel, frozen=True):
    kind: Literal["trait"]
    trait: Trait                    # "(G Generation) Trait": satisfied if the pilot has this trait

LinkRequirement = Annotated[PilotNameLink | TraitLink, Field(discriminator="kind")]

class LinkCondition(BaseModel, frozen=True):
    any_of: tuple[LinkRequirement, ...]     # "/" means "or" (rules 5-19): "(Newtype) Trait / [Amuro Ray]"
    def satisfied_by(self, pilot_name: PilotName, pilot_traits: frozenset[Trait]) -> bool: ...
    # A Unit with a pilot that satisfies this is a Link Unit and can attack the turn it is deployed (rules 3-2-6-3).

class PilotProfile(BaseModel, frozen=True):  # a Command's "【Pilot】[Name]" effect (rules 3-4-6): pair it as a Pilot instead of playing it
    name: PilotName
    ap_bonus: int
    hp_bonus: int                           # the pilot's traits are the Command's own `traits`

# ---- printings, text versions, FAQ --------------------------------------------------------
class Printing(BaseModel, frozen=True):
    id: PrintingId                  # "ST01-001" (base) or "ST01-001_p5"
    variant: int | None             # N of _pN; None for the base printing
    rarity: Rarity                  # "C +" -> Rarity.C with alt_art_level=1
    alt_art_level: int              # "+" marks after the rarity: 0 normal, 1 "+", 2 "++"
    link_art: bool                  # "LK" prefix (LKC+, LKU+, LKR+): an alt art that shows the linked pilot   (property alt_art = level > 0 or link_art)
    block: Block | None             # per printing (reprints/promos can belong to a newer block than the base)
    source_title: SourceTitle | None  # per printing: alt arts often show a different series
    where_to_get: str               # raw free text ("Heroic Beginnings [ST01]", "Store Tournament Participant Pack 05")
    set_code: SetCode | None        # parsed from the trailing "[CODE]"; None for promos/events
    package_ids: tuple[PackageId, ...]
    image_url: str

class TextVersion(BaseModel, frozen=True):   # one distinct wording of the card text (printings can differ, like MTG Oracle updates)
    text: str
    printing_ids: tuple[PrintingId, ...]     # printings that carry exactly this wording
    block: Block | None                      # newest block among those printings
    as_of: date | None                       # newest set release_date among those printings; None if all undated (promos)
    substantive: bool                        # differs from the current version after dropping parenthetical reminder text and whitespace

class Faq(BaseModel, frozen=True):
    id: str                         # "Q113" (opaque Bandai id)
    updated: date
    question: str
    answer: str

# ---- cards: one variant per kind, discriminated on `kind` ---------------------------------
class CardBase(BaseModel, frozen=True):
    number: CardNumber              # identity
    name: str                       # NFKC-normalized, zero-width chars stripped
    text_versions: tuple[TextVersion, ...]    # NEWEST FIRST (see "Which text wins"); `text` property = text_versions[0].text
    keywords: frozenset[Keyword]              # keywords found in the CURRENT text; no values, own/granted/referenced alike (see open questions)
    referenced_traits: frozenset[Trait]       # traits mentioned in the current text, e.g. "friendly (G Team) Unit"
    printings: tuple[Printing, ...]           # reference printing first (the base, or the lowest alt art if there is no base page), then by variant
    faq: tuple[Faq, ...]
    unknown_tags: tuple[str, ...]             # the one quarantine: <...>/【...】 tokens outside the Keyword enum; reported on every sync
    fetched_at: datetime

class UnitCard(CardBase):
    kind: Literal[CardKind.UNIT]
    color: Color; level: int; cost: int
    ap: int | None                  # Bandai shows "-" on a few units
    hp: int
    zones: frozenset[Zone]
    traits: tuple[Trait, ...]       # "(Earth Federation) (White Base Team)"
    link: LinkCondition | None      # None when Bandai shows "-"; only Units have one

class PilotCard(CardBase):
    kind: Literal[CardKind.PILOT]
    color: Color; level: int; cost: int
    ap_bonus: int; hp_bonus: int    # "+2" -> 2, granted to the paired Unit
    traits: tuple[Trait, ...]       # not gained by the Unit (rules 2-5-5)

class CommandCard(CardBase):
    kind: Literal[CardKind.COMMAND]
    color: Color; level: int; cost: int
    traits: tuple[Trait, ...]       # the pilot effect's traits when `pilot` is set
    pilot: PilotProfile | None      # set for Command/Pilot hybrids (68 cards); None for plain commands

class BaseCard(CardBase):
    kind: Literal[CardKind.BASE]
    color: Color; level: int; cost: int
    hp: int
    zones: frozenset[Zone]
    traits: tuple[Trait, ...]

class ExBaseCard(CardBase):         # the starting EX Base: hp only
    kind: Literal[CardKind.EX_BASE]
    hp: int

class ResourceCard(CardBase):       # nothing but text
    kind: Literal[CardKind.RESOURCE]

class ExResourceCard(CardBase):
    kind: Literal[CardKind.EX_RESOURCE]

class UnitTokenCard(CardBase):
    kind: Literal[CardKind.UNIT_TOKEN]
    ap: int | None; hp: int
    traits: tuple[Trait, ...]

Card = Annotated[UnitCard | PilotCard | CommandCard | BaseCard | ExBaseCard | ResourceCard | ExResourceCard | UnitTokenCard,
                 Field(discriminator="kind")]
# Helpers on CardBase: is_deck_card (kind in unit/pilot/command/base), is_pilot (PilotCard, or CommandCard with `pilot`),
# text (current wording), current_block.

# ---- sets and TCGPlayer mapping -----------------------------------------------------------
class SetKind(StrEnum):
    BOOSTER = "booster"; STARTER = "starter"; EXTRA_BOOSTER = "extra_booster"
    DECK_BUILD_BOX = "deck_build_box"; PROMO = "promo"; BETA = "beta"; OTHER = "other"

class CardSet(BaseModel, frozen=True):
    code: SetCode                   # "GD05", "ST11", "EB01", "SC01"; synthetic for non-coded packages (PROMO, BETA, BASIC, OTHER)
    name: str
    kind: SetKind
    bandai_package_id: PackageId | None
    release_date: date | None       # None for packages with no product page
    product_category_raw: str | None
    product_url: str | None
    # No "released" flag (it goes stale). Consumers compare release_date to today.

class CardPrice(BaseModel, frozen=True):
    """The latest TCGPlayer market price for one card. Also exactly one row of a future price history (a time series of these)."""
    card_number: CardNumber         # the join key to the master card model
    price_cents: int                # tcgcsv marketPrice of the cheapest non-alt-art, non-promo product, converted once with round(x * 100)
    product_id: ProductId           # the product that price comes from (audit: which printing)
    fetched_at: datetime            # when we pulled it (UTC)

class PriceFile(BaseModel, frozen=True):
    source_updated_at: datetime     # tcgcsv last-updated.txt for the dump these prices come from
    prices: tuple[CardPrice, ...]   # sorted by card number; a card with no buyable product has no row

class PricedCard(BaseModel, frozen=True):
    """The master card model joined with its latest price. Built when read (`load_cards_with_prices`), never stored."""
    card: Card
    latest_tcg_price: CardPrice | None
```

### Which text wins ("favor newer")
Bandai reprints cards with changed wording and expects more rules-driven changes in newer sets (the shield mechanic is under reconsideration), much like MTG's Oracle text. So a card can have several wordings and **the newest one is the card's text**.

1. Group printings by exact normalized text into `TextVersion`s.
2. Rank versions by `(block.rank, as_of)`: a later rules block beats an earlier one; within a block, the later set release date wins. **Alt arts do not establish recency** (their wording has been slightly off before), so a version is ranked from its non-alt-art printings when it has any (all its printings otherwise). Undated printings (promos/events) rank below dated ones in the same block.
3. `text_versions[0]` is the current text. `keywords`, `referenced_traits`, and `search --text` use it. Older wordings stay available (`show` lists them with their printings).
4. `substantive` marks versions whose wording differs by more than parenthetical reminder text, so a card that really changed shows up in a "changed cards" report instead of hiding among cosmetic edits.
5. **Tie-breaks (decided):** if the top versions still tie on `(block.rank, as_of)`: (a) differing only in reminder text (non-substantive): **keep the version that has the reminder text**; (b) differing substantively: **prefer the wording on a non-alt-art printing** (alt arts have twice carried slightly different text; favor the regular printing); (c) anything still tied is listed as **ambiguous recency** and falls back to the base printing. Raise it; don't guess.
6. If the keyword set differs between versions, the run report lists the card.

### Parser rules
- Parse by `dt` label, never by position. An unknown label, `TYPE`, rarity, color, zone, or block **fails that card's parse** and is listed in the run report; nothing is guessed.
- `-` means none. NFKC-normalize stats first (`３` -> `3`). `+2` on a Pilot or Command is a bonus.
- Base card attributes (kind, color, level, cost, stats, traits, link) come from the base printing. Any other printing that differs in those is reported. Printings contribute `rarity`, `alt_art`, `block`, `where_to_get`, and text.
- `Trait` -> `traits` by splitting `(…)` groups. `Link` -> split on ` / ` into `any_of`; `[…]` is a `PilotNameLink`, `(…) Trait` is a `TraitLink`.
- **Keywords:** from the current text, collect (a) `<Name N>` tokens, mapped by name and ignoring the number, and (b) `【…】` tags, split on `･`, `・`, and `/` (`【Main】/【Action】` gives two; `【Deploy・Development 2】` gives Deploy and Development; `【During Pair･(Vulture) Pilot】` gives During Pair and drops the pilot qualification, which stays in the raw text). Tokens not in the `Keyword` enum go to `unknown_tags`. `【Pilot】[Name]` is not a keyword: it creates `CommandCard.pilot` from that card's AP/HP.
- `referenced_traits`: a **two-pass** step. Pass 1 parses every card and builds `traits.json` from the `Trait` fields. Pass 2 scans each current text for `(…)` groups and keeps only those in the vocabulary (so reminder text like "(At the start of the game...)" is ignored).
- The keyword vocabulary's source of truth is the Comprehensive Rules §13. When Bandai publishes a new rules version, review §13 and the Block enum, since new keywords or a new block will fail the parse until added.

## Data Sources
| Source | Access method | Endpoint | Auth | Notes / quirks |
|--------|---------------|----------|------|----------------|
| Bandai card list | HTML (server-rendered, no API) | `GET https://www.gundam-gcg.com/en/cards/index.php?package=<id>` (also accepts POST) | none | Returns all printings of a package on one page as `li.cardItem > a[data-src="detail.php?detailSearch=<id>"]`. A blank search returns nothing, so iterate packages. Package ids come from the filter on `/en/cards/` (`data-val` + label). 25 packages at 2026-10-06; 2,011 unique printing ids, 1,149 base cards, 862 `_pN` printings. |
| Bandai card detail | HTML, clean semantic markup | `GET https://www.gundam-gcg.com/en/cards/detail.php?detailSearch=<id>` | none | `div.cardNo`, `div.rarity`, `div.blockIcon`, `h1.cardName`, `dl.dataBox` (`dt.dataTit` / `dd.dataTxt`), effect text in `div.dataTxt.isRegular`, FAQ in `div.qaCol`. All 1,149 base pages parsed without a missing label. Fetch rate ~1 page/second (0.5s delay + latency). |
| Bandai product list | HTML | `GET https://www.gundam-gcg.com/en/products/list.php` (paged, 4 pages seen) | none | Set name, category, and **Release Date** (inconsistent formats: `January 29,2027`, `July 24, 2026`; parse tolerantly). Includes **unreleased** sets (GD06 Oct 30 2026, GD07 Jan 29 2027), so consumers must compare `release_date` to today. No robots.txt (404). |
| tcgcsv.com (TCGPlayer catalog) | Static JSON | `GET https://tcgcsv.com/last-updated.txt`; `https://tcgcsv.com/tcgplayer/86/groups`; `.../86/<groupId>/products`; `.../86/<groupId>/prices` | none | For the card number to `productId` mapping and market prices. Updated once a day about 20:00 UTC. Gundam is `categoryId` 86 (28 groups: every set and starter deck, SC01, Edition Beta, four promo groups). Products carry `extendedData` `Number` and `Rarity`; alt arts are separate products with the same `Number` and a `+`/`++` rarity; each product has one price row (`Normal` or `Holofoil`); no per-condition or per-seller data. Usage rules (User-Agent, 100 ms or more between requests, one pull per 24 h, under 10,000 requests a day) and the probe are in `notes/tcgcsv.md` and `notes/source-terms.md`. |

Why Bandai and not a third party: it is official and authoritative, includes things no third party gave us (full card text, traits, links, FAQ, source title, alt arts, official release dates, unreleased sets), and removes one hop. Third-party sites are used only where Bandai has nothing: tcgcsv (TCGPlayer's catalog) for product ids and market prices; DuelFrontier and EGM (and an online ranking) for play data.

## Approach
1. **Sets** (script): scrape the package filter and the product list; build `sets.json`; classify `kind` from the product category and code prefix.
2. **Printing ids** (script): for each package, fetch the list page and collect every `detailSearch` id.
3. **Card details** (script): fetch each printing id not already stored (0.5s between requests). First full run is about 2,000 pages, roughly 35-40 minutes; later runs only fetch new ids. Save raw HTML under the tool's `data/raw/`.
4. **Parse** (script, no network): pass 1 parses all pages into typed models and builds the vocabularies; pass 2 fills `referenced_traits`. Resolve each card's current text version (needs `sets.json` for release dates, so step 1 runs first). Write `cards.json`, `traits.json`, `source_titles.json`. Print a run report: unknown tags, parse failures, per-printing differences, ambiguous-recency cards, and cards whose keywords changed between text versions.
5. **TCGPlayer prices** (script, `sync-tcgplayer`):
   1. Read `last-updated.txt` (one request). If it equals the stored `source_updated_at` and `--force` is not given, say "up to date" and stop: tcgcsv changes once a day, and its rules ask for one pull per day.
   2. Fetch the groups, then each group's `products` and `prices` (about 58 requests in all, at least 0.5 s apart, descriptive User-Agent). Raw responses are cached under `tools/gundam_cards/data/raw/tcgcsv/<source date>/` (gitignored; old days are pruned by hand). They are the audit trail, since the stored file keeps only the result.
   3. **Identify, then price** (no network; `reparse-tcgplayer` redoes this from the raw files). Parsing uses an internal, unstored product record (product id, group, name, `Number`, rarity, price row). Identification needs the rarity: `Legend Rare`, `Rare`, `Uncommon`, `Common` and the `LR`, `R`, `U`, `C` codes are the base rarities, and a trailing `+` or `++` marks an alt art, so a product is a **buyable single** when it has a `Number`, is not an alt art (no `+`/`++`) and is not in a promo group (`GCG-PR`, `EXBP`, `EXRP`, `RP`). Price: dollars to integer cents once. For each card number in `cards.json` the price is the **cheapest buyable product by market price** (Edition Beta and SC01 reprints compete like any printing; if a product has more than one price row, the cheapest is used). Anything unrecognized (a rarity, a price kind, a `Number` not in `cards.json`) is reported, never guessed.
   4. Write `prices.json` atomically: one row per priced card, `(card number, price cents, product id, fetched at)`, sorted, so a re-run on the same dump gives an identical file.
   Nothing else from tcgcsv is stored. Alt arts are never bought, and owning any printing counts as owning the card, so no alt-art or sealed product needs keeping. History is not kept yet: when it is, the rows above are the time series (append each sync's rows; "latest" becomes the newest row per card).
   **The master card model carries the price on read, not in `cards.json`.** `store.load_cards_with_prices()` joins `cards.json` and `prices.json` on card number into `PricedCard` (`card` plus `latest_tcg_price`, or `None`). The card facts (from Bandai) and the price facts (from tcgcsv, daily) have different owners, sources and refresh rates, so they are stored apart and joined by key, like tables.
6. **Search** (script): local filters over `cards.json`; output as a table or JSON.
7. **Redo:** `reparse` rebuilds from saved raw HTML with no network; `refetch` re-pulls from Bandai (cards get errata and new FAQ entries) and logs what changed.

## Implementation status
Done: `mypy --strict` clean, tests passing (the whole repo: 252), full sync run on 2026-10-06 (2,011 printing pages -> 1,152 cards). `changes` lists substantive wording differences between printings.
- `shared/basetypes.py` (validated identifier types, frozen base model, sorted sets) and `shared/fetch.py` (cached, rate-limited, retrying fetcher with a `TextFetcher` protocol for tests).
- `models.py`, `parse_detail.py`, `build.py`: typed cards, keywords, links, text versions, issue reporting.
- `sets.py` (package filter + product list -> `sets.json`, 42 sets), `printings.py` (list pages -> printing ids -> fetch only missing pages; `refetch`), `search.py` (typed local filters), `store.py`, `cli.py`.
- CLI: `sync` (sets, lists, missing printing pages, then rebuild), `sync --only sets|printings`, `refetch --card|--package|--all`, `sets`, `reparse`, `show`, `search`.
- Outputs in `shared/data/gundam_cards/`: `cards.json`, `sets.json`, `traits.json`, `source_titles.json`.

Done 2026-10-08: `tcgcsv.py` (fetch, parse, choose), `sync-tcgplayer`, `reparse-tcgplayer`, `price [--explain]`, `prices.json`, and the `PricedCard` join (`store.load_cards_with_prices`); 14 tests. They replace the earlier plan to read TCGPlayer's search API (see `notes/tcgcsv.md`).

First real sync (tcgcsv dump of 2026-10-07 20:06 UTC): 58 requests; 2,140 products (134 without a card number, 558 alt arts, 364 in promo groups); **1,032 of 1,152 catalog cards priced, including all 956 deck cards** (815 are $0.50 or less, 101 up to $2.00, 31 up to $10.00, 9 above); the 120 unpriced cards are all resources (67), EX resources (26) and EX bases (27), which exist only as promo or alt-art products or not at all. Six promo EX bases in tcgcsv (EXBP-013 to 017 and one more) are not in our catalog (reported). Spot checks: Strike Freedom Gundam $7.60 (its alt arts at $73.59 and $2,622.13 are skipped); Char's Zaku II GD01-026 $1.52 from the GD01 printing, not the $4.73 Edition Beta one. A second sync makes 1 request; `reparse-tcgplayer` is byte-identical.

Findings during implementation:
- A Link alternative can lack the "Trait" suffix: `(Teiwaz) / (Tekkadan) Trait` (GD03-067). **Decided: it's a trait**; `/` is "or".
- There are 25 card packages and 47 products on the product list (11 on the last page, one is the uncoded Edition Beta product).
- Set codes in product titles come as `[GD05]`, `Stardust Trails[GD06]` (no space), `[EVX-01]` (normalized to `EVX01`), and `[PC02A]`.
- Release dates come as `July 24,2026`, `May 29, 2026~ Available at ...`, and `-` (unannounced).
- Full-sync findings are under "What the survey of the catalog showed" (alt-art tiers, `LK*` rarities, per-printing source titles, alt-art-only card numbers, unreliable Beta stats).
- A bug found by the full data: a removed reminder line left a blank line, so reminder-only differences looked substantive. Fixed, with a regression test. Result: the reminder-text rule resolved 5 of 6 wording ties on its own.
- Python's stdlib names matter: modules named `http.py`/`types.py` shadowed the standard library, so the shared modules are `fetch.py` and `basetypes.py`.

Known data issues after the full sync (pinned by `tests/test_corpus.py`; 14 total):
| Kind | Cards | What it is |
|------|-------|-----------|
| `keywords_changed_between_versions` | `GD01-005`, `GD01-088`, `ST02-010` | Older printings use the pre-rework Link/Pair wording (`During Pair`, `When Paired ... If this is a Link Unit`); the newest block says `During Link` / `When Linked`. The newest-block wording wins as intended; reported for visibility. |
| `no_base_printing` | `EXB-001`, `EXR-001`, `R-001` | Only alt arts exist. |
| `printing_attribute_mismatch` | `GD01-051_p1`, `R-001_p5-7`, `T-001_p1`, `T-002_p1`, `T-003_p1`, `T-006_p1` | Alt art/Beta printings whose Link or stats differ; the reference printing wins. |

## Decisions (confirmed with user)
- **Text meaning:** a wording that really *means* something different (e.g. a translation slip: `GD01-051_p1`'s Link reads `Trait [Enhanced Human]` where the base says `(Cyber-Newtype) Trait`) is **raised to the user**, not auto-resolved. `changes` lists every substantive wording difference to read; `printing_attribute_mismatch` reports attribute (Link/stats) differences. The base/reference printing wins meanwhile.
- **LK is Link art**, an alt art; treat like any `+` alt art.
- **Alt arts don't establish recency**; ties prefer non-alt-art wordings (see "Which text wins").
- Terminology is the game's own: **trait**, **keyword**, **Link Unit** (no "faction").
- In a Link, a parenthesized alternative is a trait with or without the word "Trait" after it; `/` is "or" (`(Teiwaz) / (Tekkadan) Trait` = the Teiwaz trait or the Tekkadan trait).
- **One flat `keywords` list**, no values, covering both rules groups, including keywords a card grants or references. Intended use: search on a keyword, then read the cards to judge which really have it. Native-vs-granted is out of scope.
- **Newest wording wins** (block, then set release date). Reminder-text-only ties keep the version with reminder text. Other ambiguous cases are reported, not guessed, and a rule is added once we agree on one.

## Acceptance Checks
- For each package, the number of stored printings equals the number of ids on its list page.
- Every card parses into exactly one `Card` variant; the run report lists unknown tags and parse failures (target: zero failures on the 1,149 survey pages, which are kept as parser test fixtures).
- Counts match the survey: 600 units, 157 commands (68 with a pilot section), 127 pilots, 72 bases, 107 resources, 29 EX bases, 28 EX resources, 29 tokens.
- Five cards of different kinds (Unit, Pilot, plain Command, Command/Pilot hybrid, Base) plus one alt-art printing spot-checked against the site.
- Every `Keyword` in the enum appears on at least one card (or is reported as unused); every `<...>`/`【...】` token in the corpus maps to a `Keyword` or lands in `unknown_tags`.
- `LinkCondition.satisfied_by` agrees with the rules example: a pilot named "Garrod Ran & Tiffa Adill" satisfies a Unit with link `[Garrod Ran]`.
- A card with several wordings shows its newest first; `GD01-090` (alt art with different wording) is a test case.
- `sets.json` dates match the product page; unreleased sets (GD06, GD07) carry future `release_date`s.
- `sync` twice makes zero detail requests the second time; `reparse` reproduces `cards.json` from raw with no network.
- **TCGPlayer sync:** a second `sync-tcgplayer` on the same tcgcsv day makes one request (`last-updated.txt`) and changes nothing; `--force` re-pulls. A sync makes about 58 requests, none faster than 0.5 s apart, none to a TCGPlayer host. `reparse-tcgplayer` reproduces `prices.json` from the saved raw files with no network; the file round-trips through the typed models and a rebuild is byte-identical.
- **Identification:** the GD05 counts from the probe hold (203 products, 6 sealed, 197 with a `Number`, 44 numbers with more than one product, `+`/`++` rarities recognized as alt arts and skipped). A product whose `Number` is not in `cards.json` is reported, not dropped silently.
- **Coverage report:** the run prints how many catalog cards have a price and lists those that do not (for example alt-art-only numbers like `R-001`, and unreleased sets); flagging an unpriced card that real decks play is the job of the consumer (`gundam_collection`), since the catalog tool must not read the meta data.
- **Price rule:** `price GD05-002` returns the cheapest buyable product by market price; `--explain` lists every product considered and why each was or was not buyable; a card with only alt arts or promos has no price and says so.
- **Join:** `load_cards_with_prices()` returns every card in `cards.json` exactly once, with `latest_tcg_price` set for the priced ones; `cards.json` is unchanged by a price sync (byte-identical before and after).
- Prices are integer cents; no float is stored; every price row carries the date it was pulled.
- `mypy --strict` passes; reading `cards.json` back through the models round-trips byte-for-byte.
- Every card number seen in a `gundam_meta` event or online ranking snapshot exists in `cards.json` (cross-check; mismatches reported).
- `search` works with no network.

## Out of Scope
- Seller prices, per-seller inventory, per-condition prices and shipping: TCGPlayer's terms forbid scraping them and tcgcsv does not carry them. Only the market price per product is in scope. Price history is not kept yet (see Open Questions); the price rows are already shaped as one row of a history.
- Japanese or other regional sites.
- Card images (store URLs only).
- Collection ownership (separate tool).
- Per-ability parsing (which keyword belongs to which ability line, native vs. granted keywords, and pilot-qualification tags like `【During Pair･(Vulture) Pilot】`). Raw text is always kept, so it can be added later.

## Open Questions
- **Wording meaning changes:** `changes` shows 11 older wordings on 10 cards (all reorderings and rules rewordings so far, e.g. `if` -> `while`, `During Pair` -> `During Link`). Only the `GD01-051_p1` Link (`Trait [Enhanced Human]`) looks like a translation slip. Reviewed once; re-read it after future syncs.
- **Pilot qualifications** like `【When Paired･(Zeon) Pilot】`: the keyword (When Paired) is recorded, the qualification stays in raw text. Structure it later?
- **Ambiguous recency cases** that aren't reminder-text-only: collected by the run report; once there are real examples we decide a rule and lock it in. (First real example from the fixtures: `GD01-090` vs its promo alt art, same block, wording differs substantively, no way to tell which is newer; the base printing wins meanwhile.)
- **Type flags in DuelFrontier decks:** I expect Command/Pilot hybrids to appear in decks as ordinary commands; I haven't verified how DuelFrontier flags them. The meta tool classifies by catalog `kind`, so it won't matter, but worth a spot check.
- **Unreleased sets:** does Bandai list cards for a set before release (presale)? Not seen yet (GD06/GD07 have no card package).
- **Foil:** Bandai printings don't distinguish foil; tcgcsv's `Holofoil` is only the kind of price a product has (each product has one), so it is recorded and not filtered.
- **Link art:** tcgcsv marks it like any alt art (`+`), so the `LK` printings of the catalog and the `+` products cannot be told apart. Both are alt arts and never bought, so nothing depends on it.
- **Price history** (later, not now): append each sync's rows to a time series per card, for trends (is this card cheap right now?). The row shape does not change.
- **Re-sync cadence:** on demand, plus when a new set's release date arrives or a new package appears in the filter.


## Banned and restricted cards (added 2026-10-08)

Format rules come from Bandai's announcement pages (the current one, September 25, 2026: `https://www.gundam-gcg.com/en/news/01_279.html`), read from the raw page (never a summary: a summarizing model once misread the vanilla-group rule). `sync-restrictions [--url URL]` fetches the page once (cached under `data/raw/restrictions/`, Bandai terms as in `notes/source-terms.md`: personal use) and writes `shared/data/gundam_cards/restrictions.json`; give it the new URL when Bandai publishes a new list.
- **Banned**: no copies (GD01-020 Anksha). **Restricted**: at most N copies (ST02-016 Corsica Base, 2). **Banned pairs**: card A and card B may not be in the same deck (ST01-010 Amuro Ray + ST05-010 Mikazuki Augus; GD01-008 Guntank + GD05-015 M1 Astray Shrike).
- **The vanilla group** is a *description*: "a Unit card that is Lv.2 with cost 1, 2 AP, 2 HP and without effects". Every combination of two different cards matching it is a banned pair, and no more than four copies of one of them may be played: a deck can use one such card, up to four copies. The page lists the cards that match today (22); the tool matches the description against the catalog (so future vanilla cards are covered) and `sync-restrictions` reports any difference from the page's list.
- `legality.py` (pure): `copy_limit(card)` and `violations(counts, catalog)` for a deck list. Used by `suggest` (never builds an illegal deck), by the deck tables (needs are clamped to the limit and banned cards dropped) and to flag found decks that are no longer legal (a deck with Amuro Ray and Mikazuki Augus together was legal until 2026-09-25).
