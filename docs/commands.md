# Commands: asking the tools directly

Run everything from the repo root as `.venv/bin/python -m tools.<tool>.cli <command>`. Every command has `--help`.
Most views take `--source tournament|online|both`
(the collection views default to both) and `--limit N`.

## What do I own, and how much of each package / deck? (the band views)

    .venv/bin/python -m tools.gundam_collection.cli check                      # validate my_tcg_collection (typos, duplicates, unknown cards)
    .venv/bin/python -m tools.gundam_collection.cli import                     # my_tcg_collection -> collection.json (the views also re-import it themselves when the file is newer and has no errors)
    .venv/bin/python -m tools.gundam_collection.cli coverage --source online --limit 40    # every package: band, share, cost to the next band, stage
    .venv/bin/python -m tools.gundam_collection.cli decks                      # decks by band (perfect .. reachable); add --all for the lower bands
    .venv/bin/python -m tools.gundam_collection.cli decks --all --min-rate 0   # every deck, even ones played in under 5% of decks
    .venv/bin/python -m tools.gundam_collection.cli archetypes                  # the meta as archetypes, with how close I am to each
    .venv/bin/python -m tools.gundam_collection.cli decks --sort archetype      # biggest archetype first within each band
    .venv/bin/python -m tools.gundam_collection.cli decks --ids                 # also show each deck's id
    .venv/bin/python -m tools.gundam_collection.cli nickname "Suletta Aerial + Academy" redletta   # name a deck (by id); --list, --remove
    .venv/bin/python -m tools.gundam_collection.cli deck redletta               # a nickname, an id (gd04024 st13006) or words of the name
    .venv/bin/python -m tools.gundam_collection.cli deck "Master Asia"         # one deck (words of its name): header, core, staples, picks to buy
    .venv/bin/python -m tools.gundam_collection.cli deck "Master Asia" --cards         # every card: need / own / short / price
    .venv/bin/python -m tools.gundam_collection.cli deck "Marida Kshatriya" --alt-from 3   # alternatives under every pick of $3 or more (default $5)
    .venv/bin/python -m tools.gundam_collection.cli deck "Marida Kshatriya" --alternatives   # same-job cards for what is missing (never counted)
    .venv/bin/python -m tools.gundam_collection.cli deck "Master Asia" --options       # include the optional layer
    .venv/bin/python -m tools.gundam_collection.cli styles --explain          # what the decks do: colors, ratings, plan (aggro / midrange / control)
    .venv/bin/python -m tools.gundam_collection.cli decks --sort played --min-rate 0.10   # by meta coverage, leaving out fringe decks
    .venv/bin/python -m tools.gundam_collection.cli buy suletta                  # what to buy to play more of an archetype (cheapest path to Playable first)
    .venv/bin/python -m tools.gundam_collection.cli buy suletta --polish --export   # also to Complete; writes TCGPlayer Mass Entry lines (4 Char's Gelgoog [GD01])
    .venv/bin/python -m tools.gundam_collection.cli buy --package "char aznable (b)" --polish   # every deck containing a package (name as decks show it, or its anchor ST11-001)
    .venv/bin/python -m tools.gundam_collection.cli buy --deck GD02054ST11001   # one deck, by id / nickname / name
    .venv/bin/python -m tools.gundam_collection.cli buy suletta --alt-from 2     # alternatives (and ones you own) for every card of $2 or more (default $5)
    .venv/bin/python -m tools.gundam_collection.cli buy marida --include-premium  # plan the $10+ cards too (otherwise they are held back)
    .venv/bin/python -m tools.gundam_collection.cli suggest barbatos aggro PB        # a hypothetical 50 (+ a pool): shape from found decks, cards by the ratings
    #   output: ratings (now with links), link pairs, the cards by section, "other pilots worth a look" (ranked by the Units they Link, pilot stats added), the pool
    .venv/bin/python -m tools.gundam_collection.cli suggest barbatos aggro           # no colors: one deck per second color, grouped by color
    .venv/bin/python -m tools.gundam_collection.cli suggest suletta control GR --prefer owned --novelty 0.4
    .venv/bin/python -m tools.gundam_collection.cli card GD01-044              # one card: price, copies owned, its package(s), what is associated with it
    .venv/bin/python -m tools.gundam_collection.cli value                      # my collection by price band

## What do the decks look like? (the data behind it)

    .venv/bin/python -m tools.gundam_packages.cli packages --source online   # packages: core / optional members, play rates
    .venv/bin/python -m tools.gundam_packages.cli archetypes --source online # package combinations (= decks), with typical picks
    .venv/bin/python -m tools.gundam_packages.cli package "Suletta Aerial" --source online   # every card played with a package, with rates
    .venv/bin/python -m tools.gundam_packages.cli card GD01-044 --source online              # one card's package, partners, bridges, squads
    .venv/bin/python -m tools.gundam_packages.cli pairs GD01-044 --source online   # pairing: the pilots that make a Unit Link (or a pilot's Units), by deck play
    .venv/bin/python -m tools.gundam_packages.cli squads --source online     # cards that do the same job
    .venv/bin/python -m tools.gundam_packages.cli compare                    # tournament vs online: each package's rate in both

## Refreshing data

    .venv/bin/python -m tools.gundam_cards.cli sync-restrictions   # banned / restricted cards from Bandai's announcement (one request; pass --url for a newer list)
    .venv/bin/python -m tools.gundam_cards.cli restrictions        # show the list in force

    .venv/bin/python -m tools.gundam_cards.cli sync-tcgplayer          # prices (tcgcsv); --force to refetch
    .venv/bin/python -m tools.gundam_packages.cli build ; .venv/bin/python -m tools.gundam_packages.cli build --source online   # re-derive packages after new data

## Finding a package

    .venv/bin/python -m tools.gundam_packages.cli packages --source online --limit 80 | grep -i -A3 char   # list packages (name, id, color, core cards)
    .venv/bin/python -m tools.gundam_packages.cli package pkg:ST11-001 --source online           # one package: its cards and what it is played with
    .venv/bin/python -m tools.gundam_collection.cli coverage --source online --limit 60            # every package: how much of it you own, by band
