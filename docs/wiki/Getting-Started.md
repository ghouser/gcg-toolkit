# Getting started

## Install

You need Python 3.14 or newer and git.

    git clone git@github.com:ghouser/gcg-toolkit.git
    cd gcg-toolkit
    ./bootstrap.sh

`bootstrap.sh` creates a virtual environment in `.venv`, installs the three dependencies and runs the test suite. Card data, prices, meta data and the package analysis are stored in the repository, so a fresh clone works straight away; see [Keeping data fresh](Keeping-Data-Fresh) to update them.

## How commands are written

Everything runs from the repository root as:

    .venv/bin/python -m tools.<tool>.cli <command> [options]

There are four tools:

| Tool | What it is for |
|---|---|
| `gundam_collection` | **you will use this one most**: your cards, decks, bands, buying, suggesting |
| `gundam_packages` | the packages, pairs and squads behind the decks |
| `gundam_cards` | the card catalog, prices and banned list |
| `gundam_meta` | tournament events and the online ranking |

Every command has `--help`:

{{run collection --help | lines=8 | width=150}}

Most views take `--source tournament|online|both` (the collection views default to both) and `--limit N`.

## Ask about a card

The quickest way to see what the toolkit knows is to ask about one card:

{{run collection card GD01-044 | lines=40 | width=170}}
