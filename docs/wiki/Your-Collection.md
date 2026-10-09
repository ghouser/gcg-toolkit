# Your collection

## The file

Your cards live in a plain text file, `shared/data/gundam_collection/my_tcg_collection`: one card per line, a card number and a quantity, in either order. Text after `#` is a comment and blank lines are skipped.

    GD02-041 1          card number, then quantity
    4 GD05-002          quantity, then card number
    ST01-001+ 3         a trailing +, ++ or LK marks an alternate art
    ST05-004 x2         x2 and 2x are fine
    ST05-006 ?          a placeholder for a quantity you still need to count
    # fixed product     a comment

Each line must be exactly a card number and a quantity (no card names). Alt arts (`+`, `++`, `LK`) are tracked but never recommended for purchase. To start a file for the sets you own, `template` prints a line with a `?` for every card in them, for you to fill in or delete:

{{run collection template ST05 | lines=7 | width=110}}

## Check it

`check` finds typos, unknown card numbers and cards typed twice before anything else reads the file:

{{run collection check | lines=20 | width=150}}

The warnings above are not errors: a card listed twice adds up, and `check` tells you the total so you can see if it was a mistake.

## Import it

`import` turns your file into `collection.json`. You rarely need to run it yourself: every view re-imports the file when it is newer and has no errors.

## See what it is worth

`value` splits your collection by price band using TCGPlayer market prices. It also separates the bulk (cards worth under $0.50) from the cards worth selling:

{{run collection value | lines=22 | width=130}}
