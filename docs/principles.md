# Principles and values

What this toolkit holds itself to. **Principles are musts**: a change that breaks one is wrong, however useful. **Values break ties**: when two reasonable choices both keep the principles, the value decides. Mechanical specifics (how code is laid out, how tests are written) live in `docs/python-style.md`, `docs/testing.md` and `docs/tool-pattern.md`; this page says what they serve.

## Principles

### Correct data
- What a tool reports is true to its sources: nothing invented, nothing silently dropped, nothing coerced to look tidy. A value the code does not understand is kept and reported, not guessed.
- Source data is never lost: the catalog only grows, and dated snapshots are added, never rewritten.
- A write is all or nothing: a failed or interrupted run leaves the earlier files as they were.

*Why:* every decision the toolkit supports (what to buy, what to build) rests on this data. A wrong number that looks right costs more than a crash.

### Deterministic and explained
- The same inputs give the same results. Files are written in a stable order, so a rerun changes only what the data (or its timestamp) changed.
- Every recommendation can say why: which data, which rule, which constant (constants and their reasons are in `docs/tuning.md`).

*Why:* results are only trustworthy if they can be reproduced and checked, and a choice that cannot be explained cannot be argued with.

### Durable over by-hand
- Work that will recur is a script with a `--help`, not a one-off done in a conversation. Fetch, parse and compute stay separate, so one can be fixed without redoing the others.
- Prefer an API or published data over parsing pages, and parsing over reading by hand.

*Why:* a script can be rerun, tested and reviewed; manual work can only be redone.

### Typed at the boundary
- Outside data becomes typed, validated models once, where it enters. Past that point code handles domain types, never raw strings or dicts.

*Why:* a malformed value fails loudly at the door instead of travelling into an analysis and quietly bending it.

### Portable and contained
- The repository runs on any machine: no absolute or machine-specific paths. Raw inputs live in the local dataset outside git; what is committed is code, tracked reference data and regenerable output.
- Tests never touch the real dataset unless asked to.

*Why:* the toolkit has to survive a fresh clone, and a test run must never change real data.

### A good citizen of its sources
- Fetching identifies itself, is rate limited, caches what it fetched, and keeps to each source's terms.

*Why:* the toolkit depends on sources that owe it nothing.

### Smallest change that does the job
- A change does what its design says and no more: no speculative features, abstractions or drive-by cleanups.

*Why:* every extra line is something to review, test and keep true.

## Values (tie-breakers)
- **Correctness over convenience.** When in doubt, refuse and report rather than guess.
- **Derived over stored.** Compute from inputs at read time rather than store a value that can go stale.
- **Explicit over clever.** Plain names, plain control flow, one obvious way to read it.
- **Pure over effectful.** Put a decision where it can be tested without files, network or clock.
- **Standard library over a dependency.** A dependency must clearly earn its place.
- **Fail loudly over carry on.** A clear error beats a quietly wrong result.
- **The source's own words.** Name things as the game rules and sources do (`docs/glossary.md`).
