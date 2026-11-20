# Python style standard

How Python is written in this repository. These are rules a reviewer checks; `ruff` (lint only) and `mypy --strict` check what they can, and the review checklist (`.claude/rules/review-checklist.md`) covers the rest. The reasons behind them are in `docs/principles.md`.

## Structure: functional core, imperative shell
- **Decisions live in pure code.** Parsing, matching, scoring, choosing and formatting are functions of their arguments: same input, same output, no side effects.
- **Effects live at the edge.** File reads and writes, network access, the clock, environment variables and printing happen in a thin outer layer (`cli.py`, `store.py`, `fetch.py`), which gathers inputs, calls the core, and writes the result.
- The core takes what it needs as arguments: data, not paths; a timestamp, not a call to `datetime.now()`; a fetcher, not a URL it opens itself. That is what makes it testable with small values.

## Data: build new, never mutate
- **Processing builds new data objects.** A function never changes a dataset, a model or an argument it was given; it returns a new value (`model_copy(update=...)`, a new tuple, a comprehension).
- Local scratch values inside a function (a list being built, a counter) may change before they are returned; nothing outside the function may see them change.
- **Data is modelled with frozen models**: pydantic v2 models with frozen config for anything read from or written to a file, frozen dataclasses or `NamedTuple`s for internal values. Collections inside them are tuples and frozensets, not lists and sets.

## State: none at module level
- **No mutable module-level state**: no module-level lists, dicts or sets that are changed, no caches in globals, no `global`. Module level holds constants (immutable values, compiled patterns, frozen mappings), functions and classes.
- What would be state is passed in or returned instead.

## Types
- Everything passes `mypy --strict`. No `Any` in models, no bare `dict` or `str` where a domain type exists (`shared/basetypes.py`), enums for closed vocabularies. `docs/tool-pattern.md` has the data-model conventions.

## Lint
- `ruff check .` passes on the whole repository with the rule set in `pyproject.toml` (bugs, dead code and outdated idioms; no layout rules). It runs as a check in `.claude/checks.json`.
- A finding is fixed in code. There are no `# noqa` comments, no per-file ignores and no exclusion lists. A character a finding flags but the data needs (a fullwidth colon, a curly apostrophe, a zero-width space) is written as an escape (`"\uff1a"`), not suppressed.

## Smaller rules
- Never name a module after a standard-library module.
- Every script has a module docstring (what it does, its source, an example invocation) and an `argparse` CLI with `--help`.
- Paths are built from `Path(__file__)` or the dataset root, never absolute.
- Money is integer cents; time is UTC.
