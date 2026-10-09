# Tool Pattern

How every tool in this repo is structured. Spec-driven: **the design comes first and `design.md` is the source of truth.** Read this before creating or modifying any tool.

## Layout

```
tools/<tool_name>/          snake_case, so it is importable
  design.md                 The spec. Required. Start from docs/design-template.md.
  cli.py                    Entry point (argparse). Thin: parse args, call modules, print summary.
  <module>.py               Fetch / parse / logic modules. Fetch, parse, and compute stay separate.
  data/
    raw/                    Unmodified fetched responses (cache). Gitignored.
    out/                    Generated outputs (CSV/JSON) other tools or I consume.
  tests/                    Tests for parsing and logic, using small saved fixtures.
    fixtures/
shared/                     Code and data used by 2+ tools
  fetch.py                  Cached, rate-limited fetcher with User-Agent (all network access goes through it)
  basetypes.py              Validated identifier types and base model config (CardNumber, SetCode, Trait, Cents, ...)
  data/                     Shared datasets (e.g. card catalog, collection). Owned by one tool, declared as a dependency by others.
docs/
  tool-pattern.md           This file
  design-template.md        Template for design.md
.claude/skills/<tool_name>/ Optional skill wrapping the tool (see below)
```

Create only what a tool needs; don't pre-create empty folders.

## Rules

1. **Spec first.** No code until `design.md` exists and the user has agreed to it. If implementation diverges from the design, update `design.md` in the same change.
2. **Run from the repo root as a module:** `python3 -m tools.<tool_name>.cli --help`. Shared code imports as `from shared.http import ...`. Tools never import another tool's fetching, parsing or analysis code (code needed by two tools moves to `shared/`). They do read another tool's **data contract**: its `models.py` (the typed models) and `store.py` (the readers for its shared files), which is how `gundam_meta` reads the card catalog and `gundam_packages` reads the meta events.
3. **Data contracts live in `design.md`.** Any file one tool writes for another (or for me) has its format (columns/fields, key, units, timestamp) documented there. The producing tool owns it.
4. **Outputs carry a fetch timestamp** and a stable key (e.g. TCGPlayer `productId`). Re-runs overwrite or update; they don't duplicate.
5. **Durable over AI-first** (see CLAUDE.md): API, then embedded data, then HTML parsing. Judgment calls stay with the LLM; extraction does not.
6. **Every tool has a `Status` in `design.md`** (`Draft`, `Agreed`, `Implemented`) and an entry in the workspace backlog (`IMPROVEMENTS.md`, one folder above the repository) that links to its folder.
7. **Skills wrap tools, not replace them.** A skill in `.claude/skills/<tool_name>/SKILL.md` says when to use the tool and how to run it. The logic stays in the tool.

## Data Model Conventions

Every tool follows these for any file it writes, so models stay consistent across tools.

- **Type safety is a hard requirement. No stringly-typed data.** Models are frozen **pydantic v2** models (strict mode) in the tool's `models.py`, checked by **`mypy --strict`**. Each tool documents its models in `design.md` under "Data Models". Dev dependencies (`pydantic`, `mypy`, `pytest`) go in `requirements.txt`; runtime fetch/parse code stays stdlib otherwise.
  - **Parse, don't validate:** external data (HTML, JSON) is converted into domain types once, at the boundary. Past that point code only handles typed values, never raw strings or dicts.
  - **Identifiers are validated nominal types** in `shared/basetypes.py` (`CardNumber`, `SetCode`, `PrintingId`, `ProductId`, `SellerKey`, `Cents`, ...) so a card number can't be passed where a product id is expected.
  - **Closed vocabularies are enums** (`StrEnum`; `Flag` where values combine). Open vocabularies (traits, source titles) are `NewType`s backed by a generated vocabulary file, not free strings.
  - **Unions are tagged** (e.g. a link requirement is a `PilotNameLink | TraitLink`, discriminated by `kind`), not "a string that might mean two things".
  - **Use the source domain's own terms** (the game's Comprehensive Rules say "trait", "keyword", "Link Unit"), so code, docs, and CLI match what the rules and sites call things.
  - **No `Any`, no bare `dict`/`str` fields** in models. Unknown values from a source become an explicit `Unknown`/`OTHER` member that carries the raw text and emits a warning.
  - Files are read back through the same models, so a hand-edited or stale file fails loudly.
- **Envelope.** Every shared file is `{"schema_version": 1, "generated_at": "<UTC ISO-8601>", "data": ...}`. Bump `schema_version` on any breaking change; readers refuse a version they don't know.
- **Identity.** A card is identified by its **card number** (`ST01-001`) everywhere. Source-specific ids (TCGPlayer `productId`, Bandai printing id, DuelFrontier slug) are fields, never the cross-tool key.
- **Money is integer cents** (`price_cents: 24`), never floats. Convert source floats once at the boundary with rounding.
- **Time:** UTC ISO-8601 with `Z` (`2026-10-06T19:35:09Z`); calendar dates as `YYYY-MM-DD`.
- **Naming and enums:** `snake_case` keys; enums are lowercase string values (`"unit"`, `"core_meta"`).
- **Don't lose source data.** When normalizing a value into an enum, keep the original in a `*_raw` field. A value outside the known enum is stored as `other` (with raw kept) and **reported as a warning**, never silently dropped or coerced.
- **Missing vs. empty.** Absent data is `null`, not `""`, `0`, or `"-"`. Lists are `[]` when empty.
- **Normalize text at the boundary:** strip zero-width characters (e.g. U+200B), collapse whitespace, remove `\r`.
- **No derived state that goes stale.** Don't store values that change with the clock (e.g. "is this set released?"); store the inputs (release date) and compute at read time.
- **Deterministic files.** Sorted keys, stable list ordering, written atomically (temp file then rename), so re-runs produce clean diffs.

## Data layers (how the datasets fit together)
Datasets are kept apart by who owns them, where they come from and how often they change, and **joined by card number** (the identity every tool uses), like tables in a database:

| Layer | Holds | Examples | Changes |
|---|---|---|---|
| **Card facts** | what a card is: the one master card model (a `Card` union by kind), printings, text | `cards.json`, `sets.json` | when a set releases |
| **Association facts** | how cards relate and are played: packages, bridges, synergy, rates, per source | `packages.json`, `rates.json` (and `_online`), the collection | with each meta sync or edit |
| **Price facts** | what a card costs: one row per card per pull | `prices.json` (latest; later a time series of the same rows) | daily |

A convenient joined view (a card with its latest price, a card with its package) is a **read model**: built on read by a function in the owning tool's `store.py`, never stored, so a daily price pull never rewrites card facts and a card file never goes stale. History is a time series of rows keyed by `(card number, pulled at)`; "latest" is the newest row per card. If querying across layers gets awkward, the next step is a SQLite database with these layers as tables; the JSON files and their keys already have that shape.

## Workflow for a new tool

1. Add it to the workspace backlog (`IMPROVEMENTS.md`, one folder above the repository) or pick an item from there.
2. Create `tools/<tool_name>/design.md` from `docs/design-template.md`. Discuss with the user; set Status to `Agreed`.
3. Probe data sources, record findings in the design (source table, endpoints, quirks).
4. Implement per the design; write tests against saved fixtures.
5. Verify against the acceptance checks in the design; set Status to `Implemented`; move the item to Done in the workspace backlog.
