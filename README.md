# gcg-toolkit

Tools for the **Gundam Card Game**: a card catalog with prices, tournament and online meta data, deck *packages* (the cards that are played together), your collection, and a planner that tells you what to buy and what to build.

Everything is deterministic and explained: the tools write lists, and you paste them into TCGPlayer yourself. Nothing is bought or scraped on your behalf.

## Set up

Needs Python 3.14+.

    ./bootstrap.sh            # creates .venv, installs requirements, runs the tests

The card data, prices, meta data and package analysis are stored in `shared/data/`, so a fresh clone works straight away. Refresh the card catalog and prices with `gundam_cards sync` (see `docs/commands.md`).

## Use

Everything runs from the repository root as `.venv/bin/python -m tools.<tool>.cli ...`. The cheat sheet is `docs/commands.md`; the shared vocabulary (deck, package, bridge, squad, Link pair, ...) is `docs/glossary.md`.

1. Put your cards in `shared/data/gundam_collection/my_tcg_collection` (`gundam_collection template` writes a starting file, `check` finds typos).
2. `gundam_collection decks` lists the meta decks and how close you are to each; `deck <name>` explains one.
3. `gundam_collection buy <archetype>` plans the cheapest path to a playable deck.
4. `gundam_collection suggest barbatos aggro PB` builds a new 50-card deck from a package, a plan and colors.

## Layout

| Folder | What |
|---|---|
| `tools/gundam_cards` | the Bandai catalog, traits, restrictions, TCGPlayer prices |
| `tools/gundam_meta` | tournament events, the online ranking, example decks, eras |
| `tools/gundam_packages` | packages, bridges, squads, rates |
| `tools/gundam_collection` | your collection, bands, archetypes, buy and suggest |
| `shared/` | code and data used by more than one tool |
| `docs/`, `notes/`, `IMPROVEMENTS.md` | patterns, vocabulary, source notes, backlog |

Each tool has a `design.md` that is its spec. Checks: `.venv/bin/python -m pytest` and `.venv/bin/python -m mypy tools shared`.
