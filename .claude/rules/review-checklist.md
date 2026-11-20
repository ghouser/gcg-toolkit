# Review checklist

Check every change against this list. A "no" is a finding.

## Correctness
- Does it do what its design or spec says, including edge cases and the empty dataset?
- Do the tests prove the behavior, with expected values from the spec or worked out by hand (`docs/testing.md`)?
- Do `tests`, `types` and `lint` in `.claude/checks.json` pass?

## Cleanliness
- Is it readable: plain names, no dead code, no commented-out code, no leftover debugging?
- Is the working tree clean, with small commits whose messages say why?

## Rules
- Does it keep `docs/principles.md`, `docs/python-style.md` (functional core and imperative shell, no mutation of data or arguments, no mutable module-level state, frozen models) and `docs/testing.md`?
- Does it keep the rules in this folder and `docs/tool-pattern.md`?
- No `# noqa`, no lint ignores or exclusions, no tests that scan code or docs.

## Scope
- Is everything in it asked for by the change's spec or design? No extra features, refactors or tidying beyond it.

## Design docs match the code
- Do `.claude/feature-design/<feature>.md`, the tool's `design.md`, `docs/commands.md`, `docs/tuning.md` and `docs/glossary.md` say what the code now does?
