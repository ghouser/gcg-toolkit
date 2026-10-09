# Meta data: the packages behind the decks

The `gundam_packages` tool shows the analysis the decks are built from. Use `--source tournament` or `--source online`.

## packages

A **package** is a single-color group of cards that are always played together (a pilot and the Units that Link to it, a Unit and its supports). Core members are in 90% or more of the decks that run the package.

{{run packages packages --source online --limit 4 | lines=24 | width=170}}

## package: everything played with one

{{run packages package pkg:ST11-001 --source online | lines=26 | width=170}}

## pairs: pilots and Units

`pairs` shows which pilots make a Unit Link, or which Units a pilot serves, ranked by how real decks pair them:

{{run packages pairs GD01-044 --source online | lines=18 | width=170}}

## Other views

    packages squads --source online     # cards that do the same job (squads)
    packages card GD01-044              # one card: its package, partners, bridges and squads
    packages archetypes --source online # package combinations (= decks), with typical picks
    packages compare                    # tournament vs online: each package's rate in both
