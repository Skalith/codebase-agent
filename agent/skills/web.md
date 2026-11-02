---
name: web
description: Use for web search, fetching a URL, or scraping a GitHub file — anything needing knowledge or content from outside the local codebase.
triggers: web, search, google, url, fetch, scrape, docs, documentation, stackoverflow, error message, latest, current
---

# Web research and scraping

Use this when the answer is not in the workspace: external docs, package
APIs, error messages, version notes, or content at a URL.

## Rules

1. Search before fetching. Start with `web_search` to find candidate sources,
   then `fetch_url` only the URLs worth reading in full.
2. Prefer primary sources: official docs and repositories over blog reposts.
   Say which source you used.
3. Cross-check anything load-bearing. If two sources disagree, report both and
   say which you trust and why.
4. Never invent a URL. Only fetch URLs returned by a search or given by the user.
5. Quote enough to be verifiable, and always include the source URL in your
   answer. Do not paste more of a page than needed.
6. The codebase wins on facts about the codebase. Use the web for the outside
   world, not to guess what local code does.

## How to do it

- **Search:** `web_search(query)` returns titled snippets with URLs. Make the
  query specific: include the library name, the exact error text, or the version.
- **Fetch a page:** `fetch_url(url)` returns readable text plus the title. If the
  body is empty or looks like a stub, the page is probably JavaScript-rendered —
  say so rather than guessing its contents.
- **GitHub file:** `scrape_github_file(url)` turns a `github.com/.../blob/...`
  URL into raw text. Use this to read a file from any public repo.
- When a page fails (timeout, 403, empty), try one different source; if it still
  fails, report the failure plainly instead of filling the gap with assumptions.

## Answer shape

Give the answer first, then the sources:

```
<direct answer>

Sources:
- <title> — <url>
```
