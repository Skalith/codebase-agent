---
name: filesystem
description: Use for finding files by pattern, creating directories, moving or renaming, or deleting files in the workspace.
triggers: glob, find files, pattern, directory, folder, move, rename, delete, remove, mkdir, path
---

# Filesystem

Use this to locate files by pattern and to reorganize the workspace. Every path
is confined to the workspace; anything outside it is refused. Finding files
(`glob_files`, `list_files`) runs freely; creating, moving, and deleting ask the
user for permission first.

## Rules

1. Find before you act. Use `glob_files` (or `list_files`) to confirm a path
   exists before moving or deleting it.
2. Before calling `create_directory`, `move_file`, or `delete_file`, say the
   exact path and why. The user approves or declines each one. Never delete
   source or config files to "clean up" unless asked.
3. Prefer `move_file` over delete+rewrite for renames; it preserves content.
4. Do not touch ignored trees (`.git`, `venv`, `node_modules`, `__pycache__`).

## Tools

- `glob_files(pattern)` — find by pattern, e.g. `**/*.py`, `src/**/*.ts`.
  Patterns are relative to the workspace root. No permission needed.
- `create_directory(path)` — make a folder (and any missing parents).
- `move_file(src, dest)` — rename or move within the workspace; refuses a
  `dest` that already exists.
- `delete_file(path)` — remove a file.

## After acting

Report the concrete change: `moved a/b.py -> c/b.py`, `created src/core/`,
`deleted tmp/scratch.py`. If something was not found, say so; do not invent a
nearby path.
