import os
import subprocess

from langchain_core.tools import tool

GIT_TIMEOUT = 120
MAX_GIT_OUTPUT_CHARS = 5000


def _run_git(*args: str):
    """Run a git command in the workspace. Returns (returncode, output)."""
    try:
        result = subprocess.run(
            ["git", *args],
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT,
            cwd=os.getcwd(),
        )
    except FileNotFoundError:
        return 127, "Error: git is not installed."
    except subprocess.TimeoutExpired:
        return 124, f"Error: git {' '.join(args)} timed out after {GIT_TIMEOUT}s"
    output = (result.stdout + result.stderr).strip()
    if len(output) > MAX_GIT_OUTPUT_CHARS:
        output = output[:MAX_GIT_OUTPUT_CHARS] + "\n... (output truncated)"
    return result.returncode, output or "(no output)"


def _format(returncode: int, output: str) -> str:
    return f"exit code: {returncode}\n{output}"


@tool
def git_status() -> str:
    """Show the workspace git status: current branch and changed files."""
    return _format(*_run_git("status", "--short", "--branch"))


@tool
def git_diff(staged: bool = False) -> str:
    """Show unstaged changes (or staged changes when staged=True)."""
    args = ["diff", "--staged"] if staged else ["diff"]
    return _format(*_run_git(*args))


@tool
def git_log(n: int = 10) -> str:
    """Show the last N commits with their messages."""
    return _format(*_run_git("log", "--oneline", f"-n{int(n)}"))


@tool
def git_checkout(branch: str, create: bool = False) -> str:
    """Switch to a branch, or create it first when create=True."""
    if create:
        return _format(*_run_git("checkout", "-b", branch))
    return _format(*_run_git("checkout", branch))


@tool
def git_commit(message: str) -> str:
    """Stage all changes and commit them with the given message."""
    code, _ = _run_git("add", "-A")
    if code != 0:
        return _format(code, "git add -A failed.")
    return _format(*_run_git("commit", "-m", message))


@tool
def git_push(remote: str = "origin", branch: str = "") -> str:
    """Push the current branch to a remote."""
    args = ["push", remote] + ([branch] if branch else [])
    return _format(*_run_git(*args))


@tool
def git_clone(url: str, dest: str = "") -> str:
    """Clone a repository into the workspace."""
    if dest and os.path.exists(dest):
        return f"Error: destination '{dest}' already exists. Pick another path."
    args = ["clone", url] + ([dest] if dest else [])
    return _format(*_run_git(*args))


git_tools = [
    git_status,
    git_diff,
    git_log,
    git_checkout,
    git_commit,
    git_push,
    git_clone,
]
