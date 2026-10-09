# Buying

`buy` plans what to buy to play more of an **archetype**, cheapest path first. It never buys anything: it prints a plan and can write a list you paste into TCGPlayer's Mass Entry.

## The plan

{{run collection buy suletta | lines=30 | width=170}}

How it chooses: the deck cheapest to make **Playable** goes first; its copies then count as bought, and the next deck is chosen by its extra cost. So shared cards are bought once. Rules it keeps: near mint, the cheapest regular printing, never an alt art, never past 4 copies of a card number.

## Premium cards

Cards of **$10 or more** are premium. They are *considered but skipped*: the plan shows them, marks them `SKIPPED`, and leaves them out of the totals until you approve them with `--include-premium`. A deck blocked only by a premium card stays in the plan, so you can see what is holding it back.

## Alternatives

For every pick of $5 or more (change it with `--alt-from DOLLARS`) the plan lists same-job alternatives, marked *better*, *equal* or *trade-off*, and tells you which ones you already own. Alternatives are offered as redundancy (a reprint alongside the card), never silently swapped in.

## Going further

    buy suletta --polish                 # also plan the move from Playable to Complete
    buy suletta --polish --export        # write TCGPlayer Mass Entry lines
    buy --package "char aznable (b)"     # every deck containing a package
    buy --deck GD02-054+ST11-001         # one deck, by id, nickname or name
    buy marida --include-premium         # plan the $10+ cards too

The exported lines look like `4 Char's Gelgoog [GD01]`: quantity, name and set. The tool writes the list; you paste it in yourself.
