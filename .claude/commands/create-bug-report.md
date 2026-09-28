---
description: Create a structured bug report for claw-forge fix --report
argument-hint: [brief bug description]
allowed-tools: [Read, Write, Bash]
---

# /create-bug-report

Guide the user through creating a structured bug_report.md, then run the fix.

## Flow

### Phase 1 — Title & symptoms
Ask: "What's broken? Describe the symptom in one sentence."
Ask: "Any other symptoms? (error messages, affected users, frequency)"

### Phase 2 — Reproduction
Ask: "What are the exact steps to reproduce this bug?"
Ask: "Does it happen every time, or intermittently?"

### Phase 3 — Expected vs actual
Ask: "What should happen instead?"

### Phase 4 — Scope & constraints
Check existing files: `ls src/ lib/ app/ 2>/dev/null | head -20` to suggest affected areas.
Ask: "Which files or modules do you suspect? (or 'unknown')"
Ask: "What must NOT change while fixing this? (e.g. API contract, auth flow)"

### Phase 5 — Generate bug_report.md
Write the file to the project root, using **only these `##` headings** — anything
under a heading the parser does not recognise is dropped, and `claw-forge fix`
will say so:

```markdown
# Bug: <short title>

## Symptoms
## Reproduction steps
## Expected behaviour
## Actual behaviour
## Affected scope
## Constraints
## Regression test required
## Environment
```

Put the root-cause analysis under `## Symptoms` or `## Reproduction steps` —
prose, wrapped list items and fenced code blocks are all captured there. Do not
add sections like `## Impact` or `## Suggested fix`: they read well but never
reach the agent.

Show a summary of what was captured.

### Phase 6 — Run fix
Ask: "Ready to fix? (yes/no)"
If yes: run `claw-forge fix --report bug_report.md`
Show expected output.
