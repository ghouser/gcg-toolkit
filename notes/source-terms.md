# Source terms and robots.txt (checked 2026-10-07)

What each data source allows, read from its own robots.txt and terms. Re-check when a site changes (terms pages carry their own "last updated" dates). Nothing here is legal advice; it is the plain reading of the published text, for a personal, non-commercial hobby project.

| Source | robots.txt (for `*`) | Terms | Status |
|---|---|---|---|
| **EGM Events** `deckbuilder.egmanevents.com` | Allows `/api`; blocks only `/admin/`, `/account` | None published (privacy policy only; nothing on scraping) | OK. One request (~600 KB) per sync to the API the site itself uses. |
| **DuelFrontier** `api.duelfrontier.com` | None (404) | Terms (last updated 2025-08-27) prohibit: "Use automated tools to access the Service without permission". Also: "You may not copy, modify, or distribute our proprietary content". | **Needs permission.** About 1,000 requests for a full sync; ~930 responses cached locally. |
| **MetaSheep** `metasheep.gg` | Public pages allowed; `Disallow: /api/` and account pages | Personal, non-commercial license; may not "modify or copy the materials" or "mirror" them; may not "collect or harvest any information from the Service without authorization". Pro content may not be exported or shared. | **Needs authorization.** Nothing collected (home page and terms read once). |
| **Bandai** `www.gundam-gcg.com` | None (404) | Site footer: "All images, text, data posted on this website cannot be copied, printed, etc. without permission." Bandai Terms of Use: use "beyond personal use or other use permitted by applicable laws" (reproduction, distribution, publication) is prohibited without Bandai's prior consent. No clause about automation. | **OK for personal use.** About 2,000 pages cached, 0.5 s apart, fetched once. Keep the catalog private: do not publish card text or images. |
| **TCGPlayer** `www.tcgplayer.com`, `mp-search-api.tcgplayer.com` | `Crawl-Delay: 10`; blocks `/sellers/*/product/*` and `/search/*/product?seller=*`; no robots.txt on the API host | Terms of Service: "You agree not to crawl, scrape or spider any of our websites without express permission from us. If you want access to our APIs, please visit our Developer Portal." The Developer Portal says: "We are no longer granting new API access at this time." | **Do not scrape.** We have never sent TCGPlayer a request (no data, `sync-tcgplayer` is not built). The store-recommender design that calls the marketplace search API for seller inventory conflicts with the terms and the robots rules. |

## Added 2026-10-07

| Source | robots.txt (for `*`) | Terms / usage rules | Status |
|---|---|---|---|
| **tcgcsv.com** (a community export of TCGPlayer's catalog API) | `Allow: /` | Built for scripted use. Docs ask: a custom User-Agent ("generic or missing User-Agents may be blocked"), at least 100 ms between requests (exceeding it means a 10-minute IP throttle), pull at most once per 24 h (check `last-updated.txt` first; updates daily around 20:00 UTC), under 10,000 requests per day (over that "may be banned"). | **OK** if we follow those rules (our fetcher already does: descriptive User-Agent, 0.5 s delay, cache). Data: categories -> groups (sets) -> products -> market prices. Gundam Card Game is `categoryId` 86. **No SKU data**: no per-condition prices and no per-seller listings. Residual note: the data is TCGPlayer's API output redistributed by a third party; TCGPlayer's own terms are about their websites. |
| **Gundambay** `gundambay.com` | `Allow: /`; blocks `/admin/`, `/auth/` and the edit pages | Terms of Service (last updated 2025-01-08), the whole license: "Permission is granted to temporarily download one copy of the materials on Gundambay for personal, non-commercial transitory viewing only." Contact: `legal@gundambay.com`. | **Viewing only.** Extracting data with a script, or analyzing a downloaded dump, is processing, not viewing. Deleting the dump afterwards addresses retention, not purpose. Ask first. Also a different kind of data: user-built decks and simulated matchups, not tournament results. |

## Consequences for the tools
- `gundam_meta`: EGM is clean. DuelFrontier needs permission before further syncing; stored data stays usable. Without DuelFrontier, GD05 packages come out nearly the same (13 vs 14 packages) but the GD05.5 sample halves and older eras shrink.
- `gundam_cards`: Bandai is fine for personal use; do not redistribute.
- `gundam_cards sync-tcgplayer` uses tcgcsv, a public mirror of TCGPlayer's catalog and prices. Do not build calls to TCGPlayer's marketplace endpoints.
