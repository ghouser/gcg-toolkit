# Data folders are resolved when a function runs

A folder that holds data (the local dataset, a raw page cache, a tracked output folder, an export path) is found by calling a
function when the code runs, never fixed at import.

- No module-level constant holds a data folder (`RAW_DIR = REPO_ROOT / ...`), and no default argument value does
  (`def load(out_dir: Path = RAW_DIR)`). Default to `None` and resolve in the body: `(out_dir or tracked_folder()) / "sets.json"`.
- Known exception: the collection tool's store (`tools/gundam_collection/store.py`)
  (deck nicknames and the buy export only; the collection and the text list are found by `collection_file.py`'s `collection_file_path()` and
  `text_list_path()`, which `check` also uses) still fixes its output folder at import (an `OUT_DIR` constant and default arguments). Moving it was left out of the
  toolkit-hardening spec; new code does not copy it.
- The resolving functions read their environment variable on every call: `data_dir()` (`GCG_DATA_DIR`), `tool_data_root()`
  (`GCG_TOOL_DATA_DIR`), `catalog_export_path()` (`GCG_CATALOG_FILE`), `collection_file_path()` (`GCG_COLLECTION_FILE`). A tool builds its folders on them (`raw_folder()`,
  `tracked_folder()`, `data_out_dir()`).
- Why: a setting changed after import (by the owner's shell, or by the root `conftest.py` for every test) must move every read and
  write, so a test or a run pointed at a temp folder cannot touch the real files.
