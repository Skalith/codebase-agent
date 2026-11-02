import os
import subprocess

from langchain_core.tools import tool
from duckduckgo_search import DDGS

IGNORED_DIRS = {".git", ".hg", ".svn", "__pycache__", "venv", ".venv", "node_modules"}
SEARCH_EXTENSIONS = (".py", ".js", ".ts", ".tsx", ".json", ".md")
MAX_SEARCH_RESULTS = 50
MAX_LIST_FILES = 500
MAX_FILE_SIZE_BYTES = 1_000_000
MAX_COMMAND_TIMEOUT_SECONDS = 120
MAX_COMMAND_OUTPUT_CHARS = 5_000


def _resolve_in_workspace(file_path: str):
    """Return the absolute path for file_path if it stays inside cwd, else None."""
    workspace = os.path.realpath(os.getcwd())
    full_path = os.path.realpath(os.path.join(workspace, file_path))
    if not full_path.startswith(workspace + os.sep):
        return None
    return full_path


def _iter_workspace_files():
    """Yield (workspace, absolute_path) for every visible file in the workspace.

    Directory filters are applied during the walk so ignored trees are never entered.
    The workspace is resolved at call time, not at import time.
    """
    workspace = os.getcwd()
    for root, dirs, files in os.walk(workspace):
        dirs[:] = [d for d in dirs if d not in IGNORED_DIRS and not d.startswith(".")]
        for file in files:
            if not file.startswith("."):
                yield workspace, os.path.join(root, file)


@tool
def list_files() -> list[str]:
    """List all file paths in the current project workspace directory."""
    results = []
    for workspace, path in _iter_workspace_files():
        results.append(os.path.relpath(path, workspace))
    results.sort()
    if len(results) > MAX_LIST_FILES:
        extra = len(results) - MAX_LIST_FILES
        results = results[:MAX_LIST_FILES] + [f"... ({extra} more files not shown)"]
    return results or ["(no files found — workspace is empty)"]


@tool
def read_file(file_path: str) -> str:
    """Read the content of a specific file within the workspace."""
    full_path = _resolve_in_workspace(file_path)
    if full_path is None:
        return "Error: path is outside the workspace."
    try:
        with open(full_path, "r", encoding="utf-8") as f:
            content = f.read()
        return content if content.strip() else "(file is empty)"
    except Exception as e:
        return f"Error reading file: {str(e)}"


@tool
def search_code(query: str) -> list[str]:
    """Search for a keyword or function name across all code files in the workspace.

    Returns matches as 'path:line: text' entries.
    """
    matches = []
    query_lower = query.lower()
    for workspace, path in _iter_workspace_files():
        if not os.path.basename(path).endswith(SEARCH_EXTENSIONS):
            continue
        try:
            if os.path.getsize(path) > MAX_FILE_SIZE_BYTES:
                continue
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                for line_no, line in enumerate(f, start=1):
                    if query_lower in line.lower():
                        snippet = line.strip()[:120]
                        matches.append(
                            f"{os.path.relpath(path, workspace)}:{line_no}: {snippet}"
                        )
                        if len(matches) >= MAX_SEARCH_RESULTS:
                            return matches
        except Exception:
            continue
    return matches or ["(no matches found)"]


@tool
def write_file(file_path: str, content: str) -> str:
    """Create a new file or overwrite an existing one in the workspace with
    the given full content. Prefer edit_file for small changes to existing files."""
    full_path = _resolve_in_workspace(file_path)
    if full_path is None:
        return "Error: path is outside the workspace."
    try:
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, "w", encoding="utf-8") as f:
            f.write(content)
        rel = os.path.relpath(full_path, os.path.realpath(os.getcwd()))
        return f"OK: wrote {len(content)} chars to {rel}"
    except Exception as e:
        return f"Error writing file: {str(e)}"


@tool
def edit_file(file_path: str, old_string: str, new_string: str) -> str:
    """Replace an exact occurrence of old_string with new_string in a workspace file.

    old_string must match the file content exactly (including whitespace) and be
    unique in the file; include surrounding lines for context if needed.
    """
    full_path = _resolve_in_workspace(file_path)
    if full_path is None:
        return "Error: path is outside the workspace."
    try:
        with open(full_path, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception as e:
        return f"Error reading file: {str(e)}"

    count = content.count(old_string)
    if count == 0:
        return "Error: old_string not found in file. Re-read the file and copy it exactly."
    if count > 1:
        return (
            f"Error: old_string appears {count} times. Add more surrounding lines "
            "so the match is unique."
        )
    updated = content.replace(old_string, new_string, 1)
    try:
        with open(full_path, "w", encoding="utf-8") as f:
            f.write(updated)
    except Exception as e:
        return f"Error writing file: {str(e)}"
    rel = os.path.relpath(full_path, os.path.realpath(os.getcwd()))
    return f"OK: edited {rel}"


@tool
def run_command(command: str) -> str:
    """Run a shell command inside the workspace and return stdout+stderr.

    Use this to run tests, linters, git status, installs, etc.
    """
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=MAX_COMMAND_TIMEOUT_SECONDS,
            cwd=os.getcwd(),
        )
    except subprocess.TimeoutExpired:
        return f"Error: command timed out after {MAX_COMMAND_TIMEOUT_SECONDS}s"
    except Exception as e:
        return f"Error running command: {str(e)}"

    output = (result.stdout + result.stderr).strip()
    if len(output) > MAX_COMMAND_OUTPUT_CHARS:
        output = output[:MAX_COMMAND_OUTPUT_CHARS] + "\n... (output truncated)"
    return f"exit code: {result.returncode}\n{output}"


MAX_WEB_RESULTS = 8


@tool
def web_search(query: str) -> list[str]:
    """Search the web for documentation, Stack Overflow answers, error solutions, etc.

    Use this when you need external knowledge beyond the local codebase.
    Returns a list of result snippets with titles and URLs.
    """
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=MAX_WEB_RESULTS))
    except Exception as e:
        return [f"Web search error: {str(e)}"]
    if not results:
        return ["(no web results found)"]
    formatted = []
    for r in results:
        title = r.get("title", "")
        url = r.get("href", "")
        body = r.get("body", "")[:200]
        formatted.append(f"{title}\n  {url}\n  {body}")
    return formatted


code_tools = [list_files, read_file, search_code, write_file, edit_file, run_command, web_search]
