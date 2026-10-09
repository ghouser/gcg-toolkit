# <Tool Name>

**Status:** Draft | Agreed | Implemented
**Folder:** `tools/<tool_name>/`
**Backlog item:** workspace backlog > <item>

## Purpose
One or two sentences: the problem and who/what it serves.

## Usage
The CLI as the user will run it, with an example and what they get back.

```
python3 -m tools.<tool_name>.cli <args>
```

## Inputs
Arguments, files, and shared datasets this tool reads.

## Outputs
Each file written, with its **data contract** (format, columns/fields, key, units, timestamp).

| File | Format | Key | Fields | Consumers |
|------|--------|-----|--------|-----------|

## Data Sources
| Source | Access method (API / embedded / HTML) | Endpoint | Auth | Notes / quirks |
|--------|----------------------------------------|----------|------|----------------|

## Approach
How it works, in steps. Note which steps are deterministic (script) and which, if any, need LLM judgment.

## Acceptance Checks
Concrete, checkable statements that mean it works (e.g. "row count matches the seller page total", "spot-check 5 cards against the site").

## Out of Scope
What this tool deliberately does not do.

## Open Questions
Unresolved decisions; remove as they are answered.
