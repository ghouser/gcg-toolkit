# tcgcsv.com: TCGPlayer catalog and prices

Probed 2026-10-08. Terms and usage rules are in `notes/source-terms.md` (custom User-Agent, at least 100 ms between requests, one pull per 24 h after checking `last-updated.txt`, under 10,000 requests a day). No auth.

**Structure.** `https://tcgcsv.com/tcgplayer/<categoryId>/groups` (sets), `.../<categoryId>/<groupId>/products` and `.../<categoryId>/<groupId>/prices`, all JSON `{totalItems, success, errors, results}`. Updated daily at about 20:00 UTC (`https://tcgcsv.com/last-updated.txt`).

**Gundam Card Game is `categoryId` 86.** 28 groups: every set and starter deck (GD01 to GD07, ST01 to ST14, EB01, SC01 `Deck Build Box Freedom Ascension`, `GD01_b` Edition Beta), plus promo groups (`GCG-PR`, `EXBP`, `EXRP`, `RP`). Future sets are listed ahead of release (GD06 on 2026-10-30, GD07 on 2027-01-29). Group keys: `groupId`, `name`, `abbreviation`, `publishedOn`.

**Products** (GD05 group: 203). Keys: `productId`, `name`, `cleanName`, `groupId`, `url`, `imageUrl`, `extendedData` (a list of `{name, value}`). For a card: `Number` (the card number, e.g. `GD05-001`), `Rarity`, `CardType`, `Color`, `Level`, `Cost`, `Attack Points`, `Hit Points`, `Trait`, `Zone`, `Link Condition`, `Description`. Sealed products (booster pack, box, case) have no `Number`. **Alternate arts are separate products with the same `Number`**, and their rarity carries our `+` marks: `Legend Rare` and `LR+` for GD05-001 (`V2 Gundam` and `V2 Gundam (LR+)`); rarities seen: Common, Uncommon, Rare, Legend Rare, `C+`, `U+`, `R+`, `LR+`, `LR++`. In GD05, 44 card numbers have more than one product.

**Prices** (one row per product, 201 rows for 203 products). Keys: `productId`, `lowPrice`, `midPrice`, `highPrice`, `marketPrice`, `directLowPrice`, `subTypeName` (`Normal` or `Holofoil`; each product has one). Dollars as floats (convert to integer cents once). `marketPrice` was never null. **No per-condition and no per-seller data** (tcgcsv does not share SKUs). Reprints are separate products in the reprinting group (SC01 products carry the original `Number`), so one card number can have products in several groups.

**First full pull (2026-10-08, dump of 2026-10-07 20:06 UTC):** 2,140 products over 28 groups; 134 without a `Number`; 558 alt arts (rarity ends in `+` or `++`); 364 in the four promo groups; the promo groups write the rarity as `Promo`. Some Edition Beta (`GD01_b`) products have no price row or a null market price. A full pull is 58 requests (1 + 1 + 28 x 2).

**What it means.** Join to our catalog on `Number` plus the alt-art level read from the rarity suffix; a card's purchase price is the cheapest non-alt-art product for its number (market price), not a seller's listing. About 57 requests make a full sync (1 for groups, 2 per group).
