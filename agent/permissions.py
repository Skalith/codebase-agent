import copy
import functools

from agent.approvals import confirm_action

# Tools that change state or reach outside the machine. Every one of these asks
# the user first. Read-only tools (list/read/search/web/github reads, git reads)
# are intentionally NOT here, so they run without a prompt.
GATED_TOOLS = {
    # core
    "write_file",
    "edit_file",
    "run_command",
    # git (all git operations ask, reads included)
    "git_status",
    "git_diff",
    "git_log",
    "git_checkout",
    "git_commit",
    "git_push",
    "git_clone",
    # filesystem
    "create_directory",
    "move_file",
    "delete_file",
    # github
    "github_create_issue",
}


def _describe(kwargs: dict) -> str:
    if not kwargs:
        return ""
    parts = []
    for key, value in kwargs.items():
        text = str(value)
        if len(text) > 60:
            text = text[:60] + "..."
        parts.append(f"{key}={text}")
    return ", ".join(parts)


def guard_tool(tool_obj):
    """Return a copy of the tool that asks for permission before running."""
    guarded = copy.copy(tool_obj)
    original = guarded.func

    @functools.wraps(original)
    def wrapper(*args, **kwargs):
        if not confirm_action(f"run '{tool_obj.name}'", _describe(kwargs)):
            return f"Cancelled: '{tool_obj.name}' was not approved."
        return original(*args, **kwargs)

    guarded.func = wrapper
    return guarded


def guard_tools(tools):
    """Guard the state-changing tools; pass read-only tools through untouched."""
    return [guard_tool(t) if t.name in GATED_TOOLS else t for t in tools]
