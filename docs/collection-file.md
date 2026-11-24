# The collection file (contract for other apps)

The UI maintains what the owner has in one JSON file. The toolkit's collection commands only read it and never write it. This document is the contract, and the one place the old hand-typed list's format is written down so the UI's one-time import can read it. `docs/collection-file.example.json` is a valid file (the toolkit's tests parse it).

## Where it is

`$GCG_COLLECTION_FILE`, or `~/.gcg/collection.json` when the variable is unset (resolved each time a command runs). Until the file exists, the commands read the old text list read-only (see below). When the file exists it is used alone: the text list is not read and the two are never merged.

## The file

    {
      "schema_version": 1,
      "updated_at": "2026-11-22T18:30:00Z",
      "counts": {
        "ST01-001": 2,
        "ST01-001_p5": 1,
        "GD02-041": 4
      }
    }

| Field | Type | Meaning |
|---|---|---|
| `schema_version` | integer | `1` (see Version policy) |
| `updated_at` | time | ISO 8601, in UTC; when the file was last written |
| `counts` | object | printing id -> count of copies owned |

- **Identifiers** are printing ids; their shape is defined in `docs/catalog-export.md` (the "Identifiers" table): `ST01-001` is the base printing, `ST01-001_p5` an alternate printing. Case-sensitive, no spaces.
- **Counts are integers of 1 or more.** A card not owned is left out of `counts`; the file never contains `null` and never a count of 0.
- The UI writes only these three top-level keys, and its own reader refuses a file with any other top-level key. The toolkit's reader is more lenient: it ignores fields it does not know. An empty `counts` is valid.
- The UI records a count for each printing it shows: every printing of a card, base or alternate (including each variant of a card listed only as variants, such as `EXB-001`), has its own count. It writes only printing ids from the catalog.
- A printing id the toolkit's catalog does not know is not an error: the commands name it once on stderr, leave it out, and carry on.
- Owning any printing of a card counts as owning the card; copies of different printings of one card add up.

A file that is present but invalid (not JSON, a missing or unreadable `updated_at` or `counts`, a count below 1, a null, non-integer or boolean count, a malformed printing id) is refused: the command says what is wrong, reads nothing from the file, exits non-zero, and does not fall back to the text list.

## Version policy

- `schema_version` changes only for a **breaking** change: a field removed or renamed, made required where it was optional, or its type or meaning changed.
- Not breaking: adding an optional field (the toolkit's reader ignores it; the UI's reader refuses top-level keys it does not know, so a new key needs the UI updated first).
- A reader accepts the versions it was written for and refuses any other with a message naming the version found and the versions supported; it never guesses. The toolkit supports version 1.

## The legacy text list

`shared/data/gundam_collection/my_tcg_collection` is the old hand-typed list. The commands read it only as the fallback until the collection file exists; `gundam_collection check` validates it. One card per line:

- A card number and a quantity, in either order: `GD02-041 1` or `4 GD05-002`. Separators are spaces, tabs, commas or semicolons.
- `x` before or after the quantity is allowed: `ST05-004 x2`, `ST05-004 2x`.
- `#` starts a comment; blank lines are skipped.
- `?` in place of the quantity is a placeholder for an unknown quantity; it counts as nothing.
- A trailing `+`, `++` or `LK` on the card number marks an alt-art level or Link art: `ST01-001+ 3`.
- A quantity of 0 or above 99, and lines that cannot be read, count as nothing.

**The markers do not map to a printing id.** A card can have several alternate printings, and `+`, `++` and `LK` say only the alt-art level or that it is Link art, not which printing. So the fallback counts every line, marker or not, as that card's base printing (and says how many marker lines it counted), and the UI's one-time import must ask the owner or choose, never convert a marker silently.
