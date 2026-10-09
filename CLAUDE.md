# gcg-toolkit

Tools for researching, collecting and planning around the **Gundam Card Game**: the card catalog and prices, meta data, deck packages, a collection, and a planner for what to buy and build.

## Core Principle: Durable Over "AI-First"

Prefer building reusable tools over doing work by hand in the conversation.

- Don't read through HTML or copy data manually if a script can fetch and parse it.
- Source priority, in order:
  1. Official or community **API** or downloadable data (JSON/CSV/dumps)
  2. **Structured data embedded in pages** (JSON-LD, `__NEXT_DATA__`, XHR endpoints seen in the network tab)
  3. **Scraping HTML** with a parser (not by eyeballing it)
  4. Reading pages manually: last resort, and only for one-offs
- If a task will plausibly recur, write a script (or skill) the first time.
- Use the LLM for what scripts can't do well: judgment, summarizing, resolving ambiguous matches, deciding what to build. Not for bulk extraction or transformation.
- When a script exists for the task, run it. Don't redo its work by hand.

## Tools and Spec-Driven Workflow

Work is organized as **tools**, each in `tools/<tool_name>/` with a `design.md` spec. **Before creating or changing a tool, read `docs/tool-pattern.md`** (layout, rules, workflow) and use `docs/design-template.md` for new designs. Design first, get agreement, then implement.

- `docs/glossary.md`: the shared vocabulary (deck, package, bridge, squad, free floating, trait, Link pair, rates and their symbols Z/Y/YY). Use these names in code, docs and CLI output; add a term there when you introduce one.
- `docs/commands.md`: the command cheat sheet. `docs/tuning.md`: every tuning constant and why it has its value.
- `IMPROVEMENTS.md`: backlog of tools and ideas. Check it for context; update it when starting or finishing something.
- `tools/<tool_name>/design.md`: the spec and source of truth for that tool, including data contracts.
- `shared/`: code and data used by 2+ tools (e.g. `shared/fetch.py`, the cached fetcher).

## Collection and Purchasing Goals
The full version, with how each is enforced, is the top of `tools/gundam_collection/design.md`. Any work on decks, collections or purchases must serve these.

**Deck building:** (1) critical cards a package needs are never missed; (2) critical cards that bridge packages are never missed; (3) flexible cards are identified and ranked by real deck inclusion; (4) alternative cards are considered, but functional reprints are **redundant, not substitutes**: each keeps its own role and need (core stays core even if a reprint exists, since decks run both to reach more copies of the job); a reprint stands in only for a card real decks don't play in that role.

**Spending, in this order:** (1) within my means: invest where I already have support (home packages) before new packages or decks; (2) value: fund cards that enable a package or deck, and buy the cheapest acceptable alternative rather than the best card; (3) durable: among those, prefer cards that work in many packages and decks. Hard rules: near mint only, no `+`/`++`/`LK` alt-art purchases, at most 4 copies per card number, everything deterministic and explained, and nothing scraped or bought on my behalf (the tool writes a list; I paste it into TCGPlayer).

## Script Conventions

- **Language:** Python 3.14 in the project virtualenv: run everything from the repository root as `.venv/bin/python -m ...` (`./bootstrap.sh` creates it). Standard library first for runtime code (`urllib`, `json`, `csv`, `argparse`, `sqlite3`); add a dependency only when it clearly earns it and record it in `requirements.txt`. Models are typed (pydantic v2 + `mypy --strict`, see `docs/tool-pattern.md`); tests use pytest. Check with `.venv/bin/python -m mypy tools shared` and `.venv/bin/python -m pytest`.
- **Portable:** no absolute or machine-specific paths in code or data (roots come from `Path(__file__)`; stored paths are repo-relative). The repository must clone and run on any machine.
- **Never name a module after a stdlib module** (`http.py`, `types.py`, `json.py`, ...): it shadows the standard library when its folder is on `sys.path`.
- Every script is a CLI with `argparse` and a `--help` that explains it. Takes inputs via args, writes outputs to `data/`, prints a short summary.
- **Be a good web citizen:** set a descriptive User-Agent, rate-limit requests, honor robots.txt/ToS, and cache raw responses in `data/<domain>/raw/` (git-ignored) so re-runs don't re-hit the site.
- **Idempotent:** re-running should update outputs, not duplicate them.
- Keep fetch, parse, and output steps separable so a parser can be fixed without refetching.
- Prefer plain, diff-friendly formats (CSV/JSON); use SQLite only when querying across datasets justifies it.
- Include a short docstring at the top of each script: what it does, source, example invocation.

## Working Style

- Before scraping, look for an API or data export first. Check network requests and the site's documented endpoints. Say what you found.
- When a source is new, add a short note in `notes/<source>.md` (base URL, auth, rate limits, schema quirks, how IDs map) so future sessions don't rediscover it.
- Verify output: spot-check row counts and a few records against the source before calling it done.
- Report data gaps and mismatches plainly (missing cards, unparsed fields); don't paper over them.
- Prices and rankings go stale. Record the fetch date/time with any snapshot.
- Ask before adding paid services, API keys, or anything that stores credentials.
- Propose a skill when a multi-step workflow repeats; skills should wrap scripts, not replace them.

## Domain Notes

- **Card numbers** are `SET-NNN` (`GD05-002`, `ST11-001`, `EB01-076`); other shapes exist (`R-016` resources, `T-022` tokens, `EXB-/EXR-/EXBP-/EXRP-/RP-` extras). The number is the identity everywhere. Alternate arts share the base card's number and are marked by rarity: `+`, `++`, and `LK` (Link art). In the collection file, `GD02-041+ 2` is two alt-art copies of GD02-041.
- **Set codes:** boosters `GD01`-`GD07`, starters `ST01`-`ST14`, extra booster `EB01`, deck build box `SC01`; TCGPlayer also has `GD01_b` (Edition Beta) and promo groups. `shared/data/gundam_cards/sets.json` has release dates; eras for meta analysis are in `tools/gundam_meta/eras.json` (GD05, GD05.5, GD06, ...).
- **Card data:** Bandai's official English site (`gundam_cards sync`). **Prices:** tcgcsv, a public mirror of TCGPlayer's catalog (category 86), market price in integer cents, one pull a day at most (`gundam_cards sync-tcgplayer`; see `notes/tcgcsv.md`). The purchase price of a card is its cheapest non-alt-art product.
- **Meta data:** tournament events from DuelFrontier and EGM Events (`gundam_meta sync`), plus a stored online card ranking and weighted **example decks** (online decks). Terms of each source: `notes/source-terms.md`.
- **Banned and restricted cards:** Bandai's announcement page (`gundam_cards sync-restrictions`; rules enforced by `tools/gundam_cards/legality.py`).
- **Packages** are single-color groups of cards played together; **archetypes** are decks grouped by their most-played package and plan (aggro / midrange / control). The vocabulary is `docs/glossary.md`.
