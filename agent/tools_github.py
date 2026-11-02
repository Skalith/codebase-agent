import os

import requests
from langchain_core.tools import tool

GITHUB_API = "https://api.github.com"
GITHUB_TIMEOUT = 20
MAX_GITHUB_TEXT = 6000


def _headers(raw: bool = False) -> dict:
    headers = {
        "Accept": "application/vnd.github.raw" if raw else "application/vnd.github+json",
        "User-Agent": "KRATOS-agent/1.0",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _explain_http_error(status: int) -> str:
    if status == 401:
        return "401 unauthorized — set GITHUB_TOKEN in the environment."
    if status == 403:
        return "403 forbidden — rate limit hit or token lacks scope."
    if status == 404:
        return "404 not found — check the owner, repo, path, and ref."
    return f"{status} error from GitHub."


def _get(path: str, params: dict = None, raw: bool = False):
    """GET a GitHub API path. Returns (ok, text_or_data)."""
    try:
        response = requests.get(
            f"{GITHUB_API}{path}",
            params=params or {},
            headers=_headers(raw=raw),
            timeout=GITHUB_TIMEOUT,
        )
    except requests.RequestException as e:
        return False, f"Network error: {e}"
    if response.status_code >= 400:
        return False, _explain_http_error(response.status_code)
    if raw:
        text = response.text
        if len(text) > MAX_GITHUB_TEXT:
            text = text[:MAX_GITHUB_TEXT] + "\n... (file truncated)"
        return True, text
    return True, response.json()


@tool
def github_read_file(owner: str, repo: str, path: str, ref: str = "main") -> str:
    """Read one file from a public GitHub repository at a given ref."""
    ok, data = _get(
        f"/repos/{owner}/{repo}/contents/{path}", {"ref": ref}, raw=True
    )
    return data if ok else f"Error: {data}"


@tool
def github_search_code(query: str) -> list[str]:
    """Search code across GitHub. Use qualifiers like repo:owner/name for precision."""
    ok, data = _get("/search/code", {"q": query})
    if not ok:
        return [f"Error: {data}"]
    items = data.get("items", [])
    if not items:
        return ["(no results)"]
    return [
        f"{i['repository']['full_name']}:{i['path']}\n  {i['html_url']}"
        for i in items[:10]
    ]


@tool
def github_list_issues(owner: str, repo: str, state: str = "open") -> list[str]:
    """List issues on a repository (excludes pull requests)."""
    ok, data = _get(f"/repos/{owner}/{repo}/issues", {"state": state})
    if not ok:
        return [f"Error: {data}"]
    issues = [i for i in data if "pull_request" not in i]
    if not issues:
        return [f"(no {state} issues)"]
    return [f"#{i['number']} {i['title']}\n  {i['html_url']}" for i in issues[:20]]


@tool
def github_list_prs(owner: str, repo: str, state: str = "open") -> list[str]:
    """List pull requests on a repository."""
    ok, data = _get(f"/repos/{owner}/{repo}/pulls", {"state": state})
    if not ok:
        return [f"Error: {data}"]
    if not data:
        return [f"(no {state} pull requests)"]
    return [f"#{p['number']} {p['title']}\n  {p['html_url']}" for p in data[:20]]


@tool
def github_create_issue(owner: str, repo: str, title: str, body: str = "") -> str:
    """Create an issue on a repository. Requires GITHUB_TOKEN."""
    if not os.environ.get("GITHUB_TOKEN"):
        return "Error: creating an issue needs GITHUB_TOKEN in the environment."
    try:
        response = requests.post(
            f"{GITHUB_API}/repos/{owner}/{repo}/issues",
            headers=_headers(),
            json={"title": title, "body": body},
            timeout=GITHUB_TIMEOUT,
        )
    except requests.RequestException as e:
        return f"Network error: {e}"
    if response.status_code >= 400:
        return f"Error: {_explain_http_error(response.status_code)}"
    data = response.json()
    return f"Created issue #{data['number']}: {data['html_url']}"


github_tools = [
    github_read_file,
    github_search_code,
    github_list_issues,
    github_create_issue,
    github_list_prs,
]
