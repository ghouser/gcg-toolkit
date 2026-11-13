# Working rules for AI in this repo

The fundamentals of software development still apply when an AI does the typing.

- **Smallest thing that meets the spec.** No extra features, abstractions or tidying beyond the acceptance criteria.
- **Tests prove behavior.** Each acceptance criterion has a test that would fail if the behavior were wrong. Do not weaken a test to make it pass.
- **Read before writing.** Match the surrounding code's style, naming and structure.
- **Deterministic over AI.** If a script can do it (fetch, parse, transform, validate), write the script; reserve judgment for what scripts cannot do.
- **Say what you do not know.** Report gaps, failures and skipped steps plainly. Do not paper over them.
- **Change is normal.** If the spec or design turns out wrong, say so and amend it; do not work around it silently.
- **Leave it clean.** Everything committed, checks passing, no stray files.
