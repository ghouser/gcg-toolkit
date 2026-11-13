# repo-claude-setup: design

Spec: `claude-workspace/specs/gcg-toolkit/repo-claude-setup/spec.md` (Approved 2026-10-26)

## Approach
Give the toolkit a standard `.claude/` folder so the workspace workflow can set up a
worktree and run the repo's own checks mechanically, and so an agent started in a worktree
finds the repo's instructions, rules and design folder in the standard places. This is
configuration and docs only; no tool code, `bootstrap.sh`, `pyproject.toml` or
`requirements.txt` changes.

Four pieces, each the simplest thing that meets its criterion:
- `.claude/checks.json` declares the setup command (`./bootstrap.sh --no-test`) and the two
  checks the repo already documents (`pytest -q`, `mypy tools shared`) in the schema
  `scripts/repocheck.py` reads (a `setup` list, a `checks` list, each entry `{name, argv}`,
  commands run as argv lists with the worktree as cwd). The workspace starter template uses
  `mypy .`; this repo's own instructions and `bootstrap.sh` type-check `tools shared`, so the
  config matches the repo, not the generic template.
- `.claude/CLAUDE.md` becomes the single home for the repo's AI instructions. The entire
  repo-root `CLAUDE.md` moves here verbatim, section for section, plus a short
  "How work happens here" section pointing at the workspace workflow, `.claude/checks.json`,
  `.claude/rules/` and `.claude/feature-design/`. The one stale backlog line (pointing at the
  workspace `IMPROVEMENTS.md` "one folder up") is dropped per AC-4. The repo-root `CLAUDE.md`
  is then deleted so there is exactly one copy.
- `.claude/rules/ai-fundamentals.md` is adopted from the workspace starter unchanged.
- `.claude/feature-design/` is a tracked folder: its `README.md` (adopted from the starter)
  plus this design file make it tracked.

Why move the whole file rather than leave a root stub: the spec's resolved open question says
`.claude/` should be the one home for the project's AI material, since more is expected.

## Files and interfaces
- `.claude/checks.json` (new): `setup` = `./bootstrap.sh --no-test`; `checks` =
  `.venv/bin/python -m pytest -q` and `.venv/bin/python -m mypy tools shared`; `timeout` 1800.
- `.claude/CLAUDE.md` (new): all existing repo-root instructions, section meanings unchanged,
  plus the "How work happens here" section; the stale backlog bullet removed.
- repo-root `CLAUDE.md` (deleted): so each instruction has one source.
- `.claude/rules/ai-fundamentals.md` (new): adopted from the starter.
- `.claude/feature-design/README.md` (new): adopted from the starter.
- `.claude/feature-design/repo-claude-setup.md` (new): this file.
- `docs/tool-pattern.md`: unchanged. Its only `CLAUDE.md` reference, `(see CLAUDE.md)`, is a
  prose mention, not a path, so AC-5's rule ("updated only if it names a path; otherwise leave
  it") leaves it. Its `IMPROVEMENTS.md` references are out of scope (AC-5 permits no change
  outside `.claude/` beyond the root `CLAUDE.md` removal; the out-of-scope list forbids
  rewriting instructions beyond the single stale line, and "the repo's instructions" is the
  `CLAUDE.md`).

## Tests
- AC-1: `.claude/checks.json` parses and matches the documented commands; running
  `python3 -m scripts.repocheck setup gcg-toolkit repo-claude-setup` then
  `python3 -m scripts.repocheck run gcg-toolkit repo-claude-setup --project gcg-toolkit` from
  the workspace exits 0 and writes `test-results.json` with `passed: true`. Also runnable
  directly in the worktree: `./bootstrap.sh --no-test`, `.venv/bin/python -m pytest -q`,
  `.venv/bin/python -m mypy tools shared`.
- AC-2: `.claude/CLAUDE.md` exists with every original section; no repo-root `CLAUDE.md`
  remains (`git ls-files CLAUDE.md` empty); a "How work happens here" section is present.
- AC-3: `.claude/rules/ai-fundamentals.md` and `.claude/feature-design/README.md` exist and
  are tracked.
- AC-4: `grep -rn "one folder up from this repository"` over the instructions finds nothing;
  `.claude/CLAUDE.md` does not point at the workspace backlog for ideas.
- AC-5: `git diff --stat origin/main...HEAD` shows no change under `tools/` or `shared/`, and
  nothing outside `.claude/` except the root `CLAUDE.md` deletion.

## Risks
- Python 3.14: `bootstrap.sh` requires it and fails loudly otherwise. If `python3` is older,
  the check needs `PYTHON` set to a 3.14 interpreter. If none is available the config is still
  correct but the end-to-end check cannot be demonstrated; that case is reported, not guessed.
- Scope creep into `docs/tool-pattern.md`: its stale `IMPROVEMENTS.md` references are tempting
  to fix but are out of scope; leaving them is the spec's intent. Noted so a reader knows it is
  deliberate.
