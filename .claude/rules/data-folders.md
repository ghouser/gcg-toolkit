# Data folders are resolved when a function runs

A folder that holds data (the local dataset, a raw page cache, a tracked output folder, an export path) is found by calling a
function when the code runs, never fixed at import.

- No module-level constant holds a data folder (`RAW_DIR = REPO_ROOT / ...`), and no default argument value does
  (`def load(out_dir: Path = RAW_DIR)`). Default to `None` and resolve in the body: `(out_dir or tracked_folder()) / "sets.json"`.
- Known exception: the packages and collection tools' stores (`tools/gundam_packages/store.py`, `tools/gundam_collection/store.py`)
  (deck nicknames, the buy export and the `check` default path only; the collection itself is read through `collection_file.py`) still fix their output folders at import (`OUT_DIR` constants and default arguments). Moving them was left out of the
  toolkit-hardening spec; new code does not copy them.
- The resolving functions read their environment variable on every call: `data_dir()` (`GCG_DATA_DIR`), `tool_data_root()`
  (`GCG_TOOL_DATA_DIR`), `catalog_export_path()` (`GCG_CATALOG_FILE`), `collection_file_path()` (`GCG_COLLECTION_FILE`). A tool builds its folders on them (`raw_folder()`,
  `tracked_folder()`, `data_out_dir()`).
- Why: a setting changed after import (by the owner's shell, or by the root `conftest.py` for every test) must move every read and
  write, so a test or a run pointed at a temp folder cannot touch the real files.
