---
name: coding
description: Use for any change to the codebase — reading, editing, or adding files. The core explore, analyse, act, verify loop.
triggers: edit, change, fix, bug, refactor, implement, add, feature, function, class, code, file, error
---

# Coding

The default working method for every request that touches code.

## Loop: EXPLORE, ANALYSE, ACT, VERIFY

1. **Explore.** Use `search_code`, `list_files`, and `read_file` to find the
   relevant code. Never edit a file you have not read. Confirm the exact current
   text before changing it.
2. **Analyse.** Work out what the change touches: callers, imports, tests,
   config. State your plan in one or two lines before editing.
3. **Act.** Make the smallest change that solves the problem.
   - Use `edit_file` for targeted changes; copy `old_string` from the file
     exactly, including whitespace, and include enough context to be unique.
   - Use `write_file` only for new files or a genuine full rewrite.
   - Never rewrite a whole file to change a few lines.
4. **Verify.** Re-read the edited section and, when tests exist, run them
   (see the `testing` skill). Then give a short summary: what changed, why, and
   what you verified.

## Rules

- Match the surrounding code's style, naming, and libraries. Do not introduce a
  new dependency the project does not already use.
- Do not add comments unless they explain non-obvious *why*, not *what*.
- Keep the change boundary tight: do not fix unrelated things in the same pass.
- Never commit secrets. Never print or log `.env` values.
- If the request is ambiguous, make a reasonable choice, state the assumption,
  and proceed — do not stall.
