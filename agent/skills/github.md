---
name: github
description: Use to read files, search code, or work with issues and pull requests on GitHub — public repos, or any repo when a token is configured.
triggers: github, repo, repository, issue, issues, pull request, pr, gh, remote, owner, fork
---

# GitHub

Use this for anything on GitHub that is not the local checkout: reading
another project's code, searching across GitHub, or listing and creating issues
and pull requests.

## Auth and limits

- Public reads work without a token. Writes (creating issues) and heavy search
  need `GITHUB_TOKEN` in the environment. If a call fails with 401/403, say the
  token is missing rather than retrying blindly.
- Respect rate limits. If you get a 403 with a reset time, stop calling the API
  and tell the user when it resets. Do not hammer it.
- Filenames are case-sensitive. The repo, owner, and path must be exact.

## Tools

- `github_read_file(owner, repo, path, ref="main")` — one file's text. For a
  whole repo, prefer `git_clone` (suits reading many files).
- `github_search_code(query)` — search code across GitHub. Use qualifiers like
  `repo:owner/name` and the exact function name to keep results tight.
- `github_list_issues(owner, repo, state="open")` — open issues.
- `github_list_prs(owner, repo, state="open")` — open pull requests.
- `github_create_issue(owner, repo, title, body)` — create an issue. This is a
  write: it asks you to confirm first. Confirm the repo, title, and body with
  the user's intent before calling.

## Rules

1. Read before you write: list issues/PRs before creating one, so you do not
   duplicate an existing thread.
2. Quote issue/PR numbers as `#123` and include the full URL in your answer.
3. Summarize what you found; do not dump raw JSON.
4. When the local repo has a remote you care about, `git_status`/`git_log` is
   usually faster than the API. Use the API for other people's repos and for
   issues/PRs.
