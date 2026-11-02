import os
import shutil
import subprocess
import sys

from langchain_core.tools import tool

DEV_TIMEOUT = 300
MAX_DEV_OUTPUT_CHARS = 6000

PY_EXTENSIONS = (".py",)
WEB_EXTENSIONS = (".js", ".jsx", ".ts", ".tsx")


def _run(command: str) -> str:
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=DEV_TIMEOUT,
            cwd=os.getcwd(),
        )
    except subprocess.TimeoutExpired:
        return f"Error: command timed out after {DEV_TIMEOUT}s"
    except Exception as e:
        return f"Error running command: {e}"
    output = (result.stdout + result.stderr).strip()
    if len(output) > MAX_DEV_OUTPUT_CHARS:
        output = output[:MAX_DEV_OUTPUT_CHARS] + "\n... (output truncated)"
    status = "PASSED" if result.returncode == 0 else "FAILED"
    return f"{status} (exit {result.returncode})\n{output or '(no output)'}"


def _default_test_command() -> str:
    """Prefer the pytest console script; fall back to the running interpreter."""
    if shutil.which("pytest"):
        return "pytest -q"
    return f"{sys.executable} -m pytest -q"


def _build_test_command(target: str = "", command: str = "") -> str:
    base = command.strip() if command else _default_test_command()
    if target.strip():
        base = f"{base} {target.strip()}"
    return base


def _build_lint_command(target: str, tool_name: str = "") -> str:
    target = target.strip()
    tool_name = (tool_name or "").strip().lower()
    if not tool_name:
        tool_name = "eslint" if target.endswith(WEB_EXTENSIONS) else "ruff"
    if tool_name == "ruff":
        return f"ruff check {target}"
    if tool_name == "eslint":
        return f"npx eslint {target}"
    return f"{tool_name} {target}"


@tool
def run_tests(target: str = "", command: str = "") -> str:
    """Run the project's tests and return a formatted pass/fail result.

    Defaults to pytest. Pass `command` for another runner (e.g. 'npx jest').
    `target` narrows the run (a file, folder, or test id).
    """
    return _run(_build_test_command(target, command))


@tool
def lint_code(target: str, tool_name: str = "") -> str:
    """Lint a file or folder. Auto-picks ruff (Python) or eslint (JS/TS)."""
    return _run(_build_lint_command(target, tool_name))


dev_tools = [run_tests, lint_code]
