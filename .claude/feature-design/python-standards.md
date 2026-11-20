# python-standards: design

Spec: `claude-workspace/specs/gcg-toolkit/python-standards/spec.md` (PersonalClaude workspace)

## Approach
Four pieces of written standard, one linter, one real-data gate and one doc refresh. No tool's behavior changes.

**Linter first (AC-4).** `ruff` is pinned exactly in `requirements.txt` (the repo has one requirements file, so it is the dev dependency list too) and configured under `[tool.ruff]` in `pyproject.toml`: `target-version = "py314"`, lint only, and an explicit `select` of rule families that catch bugs or dead code rather than layout (pycodestyle `E4`/`E7`/`E9`, Pyflakes `F`, bugbear `B`, pyupgrade `UP`, comprehensions `C4`, simplify `SIM`, `PIE`, pylint errors `PLE`, and Ruff's own `RUF`). No whitespace, line-length or import-order rules: those are formatting, which the spec leaves to `python-format`. There is no `ignore`, no `per-file-ignores`, no `extend-exclude`; ruff's default `respect-gitignore` keeps the virtualenv and the git-ignored folders out. The first step counts the findings and reports them; the cleanup follows only once the owner has seen the count (and a split, if it is large). Every finding is fixed in code; no `# noqa`. A `lint` check (`.venv/bin/python -m ruff check .`) joins `tests` and `types` in `.claude/checks.json`.

**One real-data gate (AC-3).** The root `conftest.py` already reads `GCG_TEST_REAL_DATA` once. It gains a `pytest_collection_modifyitems` hook that adds a skip to every item marked `real_data` unless the variable is `1`. `pyproject.toml` registers `real_data` and drops `corpus`. The three `test_corpus.py` modules and the collection regression test drop their own env checks and `skipif` gates and use `pytestmark = pytest.mark.real_data`; their "skip on an empty dataset" checks stay (that is a different reason to skip). The marker gate is the only place the variable is read for gating. With the variable set, only `real_data` tests see the real `GCG_DATA_DIR`; the autouse empty-dataset fixture still gives every other test its empty temp folder. (Before this, setting the variable handed the real dataset to every test, and 93 tests written for an empty dataset failed.) The root conftest also loads the `pytester` plugin so the gate itself can be tested.

**Docs (AC-1, AC-2, AC-5).** New `docs/principles.md` (principles as musts, values as tie-breakers, each category with its why), `docs/python-style.md` (functional core and imperative shell, new data objects instead of mutation, no mutable module-level state, frozen models; how ruff fits), `docs/testing.md` (the testing rules of AC-2, naming the `real_data` marker and `GCG_TEST_REAL_DATA`), and `.claude/rules/review-checklist.md` (short: correctness, cleanliness, rules, scope, design docs match code). `.claude/CLAUDE.md` points to all four. `docs/tool-pattern.md` is edited sentence by sentence against these and the export contract. Repo docs stay durable: rules and reasons, no acceptance criteria or feature detail.

Why ruff with a curated `select` over `select = ["ALL"]` plus ignores: an ignore list reads like hiding findings, which the spec forbids, and `ALL` pulls in layout and opinion rules (assert style, magic numbers, complexity limits) whose fixes would be refactors beyond the spec.

## Files and interfaces
- `requirements.txt`: `ruff==<exact version>`.
- `pyproject.toml`: `[tool.ruff]` and `[tool.ruff.lint]` (select only); pytest markers: `real_data` replaces `corpus`.
- `.claude/checks.json`: new check `lint`: `[".venv/bin/python", "-m", "ruff", "check", "."]`.
- `conftest.py`: `pytest_collection_modifyitems(config, items)` skips `real_data` items unless `GCG_TEST_REAL_DATA=1`; `_empty_dataset` keeps the empty folder for every unmarked test; `pytest_plugins = ["pytester"]`.
- `shared/test_real_data_marker.py` (new): the gate's tests.
- `tools/gundam_cards/tests/test_corpus.py`, `tools/gundam_meta/tests/test_corpus.py`, `tools/gundam_packages/tests/test_corpus.py`, `tools/gundam_collection/tests/test_regression.py`: use the marker, drop per-module env gates.
- Python files across `tools/` and `shared/` with lint findings: fixed in place, no behavior change.
- New docs: `docs/principles.md`, `docs/python-style.md`, `docs/testing.md`, `.claude/rules/review-checklist.md`. Changed: `.claude/CLAUDE.md`, `docs/tool-pattern.md`, and any `design.md` line naming the `corpus` marker.

## Tests
- AC-1, AC-2, AC-5: documents, checked by review against the spec's lists (each listed rule present, no `if`/`else` rule, no acceptance criteria, no private material). A text check: `grep -rn "IMPROVEMENTS.md" docs/tool-pattern.md` and `grep -rn "null" docs/tool-pattern.md` show no stale statement.
- AC-3: `shared/test_real_data_marker.py` runs the root conftest under `pytester` on a tiny module: the `real_data` test is skipped with the variable unset or not `1`, and with it `1` the marked test sees the dataset while the unmarked one keeps an empty folder. `GCG_TEST_REAL_DATA=1 pytest -q` passes. `grep -rn "GCG_TEST_REAL_DATA" tools shared` finds no per-module gate; `grep -rn "corpus" pyproject.toml` finds nothing. `pytest -q` with the variable unset passes.
- AC-4: the `lint` check passes; `grep -rn "noqa" tools shared conftest.py` is empty; `pyproject.toml` has no `ignore`, `per-file-ignores`, `exclude` or `extend-exclude` under ruff. The tests and types checks still pass after the fixes (they guard against behavior change).

## Risks
- **Fixes that change behavior.** Some findings (ambiguous Unicode in strings, zero-width spaces, loop-variable capture) touch strings or closures that may be intentional. Each such fix is checked against the tests and, where output text changes, against the spec's "no behavior change"; a character that must stay is written as an escape (`"–"`) rather than suppressed.
- **Ruff version drift.** New ruff releases add rules to selected families; the exact pin keeps the check stable, and upgrades are a deliberate change.
- **Ignored files.** Ruff skips git-ignored paths through `respect-gitignore`; if that default changes, private folders could be linted. Checked by `ruff check --show-files`.
- **Size.** If the finding count exceeds about 100 or 15 files, work stops for a split (AC-4).
