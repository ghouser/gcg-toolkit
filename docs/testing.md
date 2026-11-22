# Testing standard

Rules for tests in this repository, written so a reviewer can check each one. Tests use pytest and run with `.venv/bin/python -m pytest -q` (the `tests` check in `.claude/checks.json`).

## Where tests live
- A tool's tests live beside its modules, in `tools/<tool>/tests/`. Tests for `shared/` code live in `shared/` as `shared/test_<module>.py`. New tests follow the same layout; there is no separate tests tree.
- Fixtures are small and saved in the tool's `tests/fixtures/` folder: a few cards, one page, one event, never a whole crawl or dataset. Test data built in code (helpers like `tools/gundam_packages/tests/helpers.py`) is fine and preferred when it is shorter.

## What a test proves
- **Test behavior, not construction.** A test calls the code the way its users do and checks what comes out. It does not scan source files or docs to check how they are written; rules about how code is built are for the reviewer (`.claude/rules/review-checklist.md`). One stated exception: a test may read `docs/catalog-export.md` to check the identifier patterns the contract documents against its fixture, `docs/identifier-examples.json` (`shared/test_identifier_examples.py`).
- **CLI end to end for commands; units for logic.** A command's behavior and output contract (what it prints, what files it writes, its exit code) is tested by running the command (its `main` with arguments). Logic and parsing (scoring, matching, parsing a page) are tested as units, by calling the function with small values.
- **Expected values come from the spec or from hand derivation**, never copied from running the code. A test whose expectations were taken from the code's own output is a *characterization test*: its name says so (`test_characterization_...`) and a comment says what it pins and why.
- **"Effectively what the spec asked."** Where the spec cannot fully determine a value (a score, a ranking among near-equals), a test may check a range, an ordering or a property instead of an exact value, and says so in a comment.
- **Every command and every reader has a "no data" test.** On an empty dataset it gives a clear "no data" result (a message naming what is missing, a non-zero exit where that is the contract), never a crash and never an empty success. `shared/test_empty_dataset.py` holds these for the commands.

## Real data
- Tests never read or write the real dataset by default. The root `conftest.py` points `GCG_DATA_DIR` at an empty temporary folder for every test.
- Tests never touch the cards and meta tools' real raw caches or tracked files: the root `conftest.py` points `GCG_TOOL_DATA_DIR` at a temporary folder for every test (real-data tests see it as it is), holding copies of the tracked `sets.json` and `restrictions.json`.
- A test that needs the real dataset is marked **`real_data`** (`pytestmark = pytest.mark.real_data`). Marked tests are skipped unless **`GCG_TEST_REAL_DATA=1`**; with it set, only they see the real dataset, and they still skip when the data they need is absent.
- `conftest.py` is the only place that reads `GCG_TEST_REAL_DATA`. A test module never checks it itself; it uses the marker.
- Real-data tests check facts that should survive a data refresh (ranges, orderings, that every card is known), or pin facts of a dated sync and say so in their docstring.
