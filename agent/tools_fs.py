import glob as _glob
import os
import shutil

from langchain_core.tools import tool

from agent.tools import IGNORED_DIRS, _resolve_in_workspace

MAX_GLOB_RESULTS = 200


def _is_ignored(path: str, workspace: str) -> bool:
    rel = os.path.relpath(path, workspace)
    parts = rel.split(os.sep)
    return any(p in IGNORED_DIRS or p.startswith(".") for p in parts)


@tool
def glob_files(pattern: str) -> list[str]:
    """Find files by glob pattern relative to the workspace, e.g. **/*.py."""
    workspace = os.path.realpath(os.getcwd())
    matches = []
    for path in _glob.glob(os.path.join(workspace, pattern), recursive=True):
        if os.path.isfile(path) and not _is_ignored(path, workspace):
            matches.append(os.path.relpath(path, workspace))
    matches.sort()
    if not matches:
        return [f"(no files match '{pattern}')"]
    if len(matches) > MAX_GLOB_RESULTS:
        extra = len(matches) - MAX_GLOB_RESULTS
        matches = matches[:MAX_GLOB_RESULTS] + [f"... ({extra} more not shown)"]
    return matches


@tool
def create_directory(path: str) -> str:
    """Create a directory (and any missing parents) inside the workspace."""
    full_path = _resolve_in_workspace(path)
    if full_path is None:
        return "Error: path is outside the workspace."
    try:
        os.makedirs(full_path, exist_ok=True)
    except Exception as e:
        return f"Error creating directory: {e}"
    rel = os.path.relpath(full_path, os.path.realpath(os.getcwd()))
    return f"OK: created {rel}"


@tool
def move_file(src: str, dest: str) -> str:
    """Move or rename a file within the workspace (refuses an existing dest)."""
    src_full = _resolve_in_workspace(src)
    dest_full = _resolve_in_workspace(dest)
    if src_full is None or dest_full is None:
        return "Error: path is outside the workspace."
    if not os.path.exists(src_full):
        return f"Error: '{src}' does not exist."
    if os.path.exists(dest_full):
        return f"Error: '{dest}' already exists. Pick another path."
    try:
        shutil.move(src_full, dest_full)
    except Exception as e:
        return f"Error moving file: {e}"
    return f"OK: moved {src} -> {dest}"


@tool
def delete_file(path: str) -> str:
    """Delete a file in the workspace."""
    full_path = _resolve_in_workspace(path)
    if full_path is None:
        return "Error: path is outside the workspace."
    if not os.path.exists(full_path):
        return f"Error: '{path}' does not exist."
    if os.path.isdir(full_path):
        return "Error: refusing to delete a directory; only files are supported."
    try:
        os.remove(full_path)
    except Exception as e:
        return f"Error deleting file: {e}"
    return f"OK: deleted {path}"


fs_tools = [glob_files, create_directory, move_file, delete_file]
