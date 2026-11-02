---
name: git
description: Use for local git work in the workspace — status, diff, log, branch, commit, push, or clone a repo.
triggers: git, commit, branch, push, clone, diff, log, status, checkout, stage, merge
---

# Git

Use this for version control in the workspace. **Every git operation asks the
user for permission first**, read-only included. Before calling any git tool,
say plainly what you are about to run and why, so the user can approve it. If
the user declines, stop and ask how they want to proceed.

## Before any write

1. Run `git_status` and `git_diff` first. Know what is staged and unstaged.
2. Never stage or commit files the user did not ask about. No secrets (`.env`,
   keys). If `.env` shows up, stop and tell the user.
3. Write a clear commit message: a short imperative subject line (under ~72
   chars), then a body explaining *why*, not just *what*.
4. Never force-push, never rewrite history (`rebase -i`, `reset --hard`) unless
   the user explicitly asks. The confirm prompt is not a licence to be reckless.

## Tools (all ask for permission)

- `git_status()` — current branch, staged/unstaged/untracked.
- `git_diff(staged=False)` — show changes; set `staged=True` for the index.
- `git_log(n=10)` — recent commits with messages.
- `git_checkout(branch, create=False)` — switch, or create with `create=True`.
- `git_commit(message)` — stage tracked changes and commit.
- `git_push(remote="origin", branch=None)` — push current branch.
- `git_clone(url, dest=None)` — clone into the workspace (refuses an existing
  destination).

## Reporting

State the branch, what was committed (file list), and the new commit hash. If a
command fails, show the git error plainly and stop; do not guess at the cause.
