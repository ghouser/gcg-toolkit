# Every store reader has an empty-dataset case

Every public store reader has a row in the reader tables of `shared/test_empty_dataset.py` (`EMPTY_ANSWERS` or `RAISES_NO_DATA`).
A store reader is every public `load_*` and `*_as_of` function in a tool's `store.py`, and any other public function there that reads
stored data (such as `read_raw_dump`, `raw_dump_stamps`, `stored_event_ids`).

- The row states the reader's documented empty answer (None, an empty tuple, mapping or set) or the `NoData` source it raises,
  worked out by hand from its docstring, never copied from running it. A reader never raises anything else on an empty dataset.
- A reader of the dataset or a raw cache is called with no folder, so it resolves the root conftest's empty folders as a run would;
  a reader of tracked files is given an empty folder or a missing path.
- Adding, renaming or changing a reader's empty answer changes its row in the same commit.
- The reviewer checks this (`review-checklist.md`). There is no test that scans the stores for readers: the repo forbids tests that
  scan code (`docs/testing.md`). Commands are different: `test_every_subcommand_is_checked_or_is_not_a_dataset_read` fails the run
  when a subcommand has no case.
