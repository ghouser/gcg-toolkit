# One atomic write

The atomic write (a temp file in the target's folder, then a rename over the target) lives only in `shared/dataset.py` as `write_atomic`.

- A module that writes a file imports `write_atomic` from `shared.dataset`; it does not re-export it through a store or define its own.
- A second definition of it (a new `write_atomic`, an `_atomic_write`, or an inline `mkstemp` plus `os.replace`) is a review finding.
- Why: one copy means one place that refuses a write into the real `~/.gcg` while tests run, and one place that cleans up a failed write.
- The reviewer checks this (`review-checklist.md`). There is no test or lint check that scans the code for it: the repo forbids tests that
  scan code.
