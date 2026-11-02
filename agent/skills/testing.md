---
name: testing
description: Use when running tests or linters, or when changing code that has tests — verify behavior instead of assuming it works.
triggers: test, tests, pytest, jest, lint, ruff, eslint, failing, failure, assert, verify, check
---

# Testing and linting

Use this whenever you claim code works, or when tests or linters are present.
Verification is not optional: run the check, read the result, then decide.

## Rules

1. Run the narrowest check that covers your change first (one test file, one
   function), then broaden. Fast feedback beats a slow full run.
2. Read failures fully: message, file, line. Fix the cause, not the symptom.
   Never weaken or delete a test to make it pass unless the user says the test
   itself is wrong.
3. Re-run after every fix. A fix is not done until the check passes.
4. Report the exact command and its real result. Do not say "should pass".
5. Lint only what you touched (a file or folder), and only fix issues relevant
   to your change.

## Tools

- `run_tests(target=None, command=None)` — runs the project's test runner
  (pytest by default; pass `command` for jest or another runner). `target` can
  be a file, folder, or test id. Returns formatted pass/fail plus failure detail.
- `lint_code(target, tool=None)` — runs `ruff` (Python) or `eslint` (JS/TS) on a
  file or folder. Auto-detects the tool when omitted.

## Loop

1. `run_tests(target)` and read the output.
2. On failure, `read_file` the failing source, find the root cause, fix it with
   `edit_file`.
3. `run_tests(target)` again. Repeat until green, then run the broader suite.
4. Summarize: command, before/after result, files changed.
