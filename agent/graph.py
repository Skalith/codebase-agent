import time
import re
import json
from typing import Annotated, TypedDict
from langchain_core.messages import BaseMessage
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode

from agent.tools import code_tools
from agent.skills import skill_tools, catalog_prompt
from agent.tools_web import web_tools
from agent.tools_git import git_tools
from agent.tools_github import github_tools
from agent.tools_fs import fs_tools
from agent.tools_dev import dev_tools
from agent.permissions import guard_tools
from agent.llm_factory import llm_factory
from agent.memory import memory_checkpointer

# Every tool the agent may call. Read-only tools run free; state-changing tools
# (writes, all git operations, deletes, issue creation) ask the user first.
AGENT_TOOLS = guard_tools(
    code_tools
    + skill_tools
    + web_tools
    + git_tools
    + github_tools
    + fs_tools
    + dev_tools
)

MAX_RETRIES = 2
BASE_DELAY = 2

# How long to skip a provider after it reports its quota is exhausted, so we
# fail over immediately instead of retrying a dead key on every request.
QUOTA_COOLDOWN_SECONDS = 300
_quota_blocked_until = {}


def _is_quota_error(exc: Exception) -> bool:
    """True when a provider says the key is out of quota (do not retry it)."""
    msg = str(exc).lower()
    return any(
        token in msg
        for token in ("429", "quota", "rate limit", "rate_limit", "resource_exhausted", "exceeded")
    )


def _is_transient(exc: Exception) -> bool:
    """True for server hiccups worth one retry (not quota)."""
    msg = str(exc).lower()
    return "503" in msg or "unavailable" in msg or "overloaded" in msg


def _retry_delay(exc: Exception, attempt: int) -> float:
    msg = str(exc)
    m = re.search(r"try again in ([\d.]+)s", msg)
    if m:
        return float(m.group(1)) + 0.5
    return BASE_DELAY * (2 ** attempt)

class CodeAgentState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]


def _tool_content_text(content) -> str:
    """Flatten any ToolMessage content shape into plain text."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, (list, tuple)):
        parts = []
        for part in content:
            if isinstance(part, dict):
                parts.append(str(part.get("text", "")))
            else:
                parts.append(str(part))
        return "".join(parts)
    return str(content)


def _sanitize_messages(messages):
    """Replace empty tool results before sending history to any provider.

    Some providers (e.g. Groq) reject role=tool messages whose content is a
    blank string OR an empty array, and such messages can end up in persisted
    history. Rewriting them at send time also heals threads that were already
    poisoned.
    """
    cleaned = []
    for m in messages:
        if isinstance(m, BaseMessage) and m.type == "tool":
            if not _tool_content_text(m.content).strip():
                m = type(m)(
                    content="(empty tool result)",
                    tool_call_id=m.tool_call_id,
                    name=getattr(m, "name", None),
                )
        cleaned.append(m)
    return cleaned


RECENT_MESSAGE_LIMIT = 10
MAX_MESSAGE_CHARS = 8000
MAX_SUMMARY_CHARS = 1500


def _summarize_old(messages) -> str:
    """Condense dropped turns into a short deterministic summary.

    No extra model call: prior user asks and final assistant replies are
    listed, so background survives without shipping the whole thread.
    """
    lines = []
    for m in messages:
        mtype = getattr(m, "type", None)
        text = _tool_content_text(m.content).strip().replace("\n", " ")
        if not text:
            continue
        if mtype == "human":
            lines.append(f"- User asked: {text[:200]}")
        elif mtype == "ai" and not getattr(m, "tool_calls", None):
            lines.append(f"- You answered: {text[:200]}")
    if not lines:
        return ""
    summary = "\n".join(lines)
    if len(summary) > MAX_SUMMARY_CHARS:
        summary = "... " + summary[-MAX_SUMMARY_CHARS:]
    return summary


def _window_history(messages):
    """Return (summary, recent_messages) to send to the provider.

    Keeps the current turn's full tool exchange (a tool result must follow its
    call) plus the most recent messages; everything older becomes a summary.
    """
    messages = list(messages)

    last_human = None
    for i in range(len(messages) - 1, -1, -1):
        if getattr(messages[i], "type", None) == "human":
            last_human = i
            break

    recent_start = max(len(messages) - RECENT_MESSAGE_LIMIT, 0)
    if last_human is not None:
        recent_start = min(last_human, recent_start)

    # Never start the window on a bare tool result (some providers reject it).
    while recent_start > 0 and getattr(messages[recent_start], "type", None) == "tool":
        recent_start -= 1

    summary = _summarize_old(messages[:recent_start])

    trimmed = []
    for m in messages[recent_start:]:
        content = m.content
        if isinstance(content, (list, dict)):
            content = json.dumps(content)
        if isinstance(content, str) and len(content) > MAX_MESSAGE_CHARS:
            content = (
                content[:MAX_MESSAGE_CHARS]
                + f"\n... ({len(content) - MAX_MESSAGE_CHARS} chars truncated)"
            )
            m = m.model_copy(update={"content": content})
        trimmed.append(m)
    return summary, trimmed


def create_code_agent(llm_override=None):

    def agent_node(state: CodeAgentState):
        system_prompt = (
            "You are KRATOS, an expert coding agent working inside the user's "
            "project directory (your workspace).\n"
            "First decide what kind of request this is:\n"
            "- CODEBASE task: anything about the files, code, tests, config, or "
            "git history in THIS workspace. Explore before you act: use "
            "search_code/list_files/read_file to understand the relevant code, "
            "make precise minimal edits, then verify (re-read and/or run tests).\n"
            "- GENERAL coding question: language concepts, algorithms, library "
            "usage, or 'how do I...' that does not depend on this workspace's "
            "files. Answer directly and concisely from your own knowledge. Do NOT "
            "search or read files unless the question actually depends on this "
            "codebase; use web_search only when you need current/external facts.\n"
            "For codebase changes follow EXPLORE -> ANALYSE -> ACT -> VERIFY: "
            "understand the relevant code, reason about what the change affects "
            "(callers, imports, tests), apply precise minimal edits (never rewrite "
            "a whole file when a small edit suffices), then confirm nothing broke. "
            "Then summarize what you changed and why. For general questions, just "
            "answer.\n"
            "Skills: you have a library of skills that teach you how to handle "
            "a class of task correctly (web research, GitHub, git, filesystem, "
            "testing, coding). Before starting a task that matches one, call "
            "load_skill(name) and follow it. Call list_skills when unsure.\n"
            "Available skills:\n" + catalog_prompt()
        )

        summary, recent = _window_history(_sanitize_messages(state["messages"]))
        if summary:
            system_prompt += (
                "\n\nSummary of earlier conversation (older turns were trimmed to "
                "save space; treat as background):\n" + summary
            )
        messages = [{"role": "system", "content": system_prompt}] + recent

        if llm_override is not None:
            response = llm_override.bind_tools(AGENT_TOOLS).invoke(messages)
            return {"messages": [response]}

        # Provider priority: gemini → groq → omniroute (free local) → ollama.
        response = None
        errors = []
        last_exc = None
        FALLBACK_ORDER = ["GEMINI_API_KEY", "GROQ_API_KEY", "OMNIROUTE_API_KEY"]
        entries_by_provider = {e["provider"]: e for e in llm_factory.api_keys}
        ordered = [entries_by_provider[p] for p in FALLBACK_ORDER if p in entries_by_provider]
        # Append any other providers not in the priority list.
        seen = set(FALLBACK_ORDER)
        ordered += [e for e in llm_factory.api_keys if e["provider"] not in seen]

        for attempt in range(MAX_RETRIES + 1):
            transient = False
            for entry in ordered:
                provider = entry["provider"]
                # Skip providers whose quota is exhausted: fail over immediately
                # to the next one instead of retrying a dead key.
                if _quota_blocked_until.get(provider, 0) > time.time():
                    errors.append(f"{provider}: skipped (quota, cooling down)")
                    continue
                try:
                    client = llm_factory.get_llm_for_entry(entry).bind_tools(AGENT_TOOLS)
                    response = client.invoke(messages)
                    break
                except Exception as exc:
                    errors.append(f"{provider}: {exc}")
                    if _is_quota_error(exc):
                        _quota_blocked_until[provider] = time.time() + QUOTA_COOLDOWN_SECONDS
                    elif _is_transient(exc):
                        transient = True
                        last_exc = exc
            if response is not None or not transient or attempt >= MAX_RETRIES:
                break
            errors.append(f"(retry {attempt + 1}/{MAX_RETRIES}...)")
            time.sleep(_retry_delay(last_exc, attempt))

        # Last resort: local Ollama if explicitly enabled.
        if response is None and llm_factory.ollama_enabled():
            try:
                response = (
                    llm_factory.get_local_llm()
                    .bind_tools(AGENT_TOOLS)
                    .invoke(messages)
                )
            except Exception as local_error:
                errors.append(f"local-ollama: {local_error}")

        if response is None:
            raise RuntimeError(
                "All providers failed.\n  - " + "\n  - ".join(errors)
            )

        return {"messages": [response]}

    tool_node = ToolNode(tools=AGENT_TOOLS)

    def should_continue(state: CodeAgentState):
        last_message = state["messages"][-1]
        if last_message.tool_calls:
            return "tools"
        return END

    workflow = StateGraph(CodeAgentState)
    workflow.add_node("agent", agent_node)
    workflow.add_node("tools", tool_node)

    workflow.add_edge(START, "agent")
    workflow.add_conditional_edges("agent", should_continue, {"tools": "tools", END: END})
    workflow.add_edge("tools", "agent")

    return workflow.compile(checkpointer=memory_checkpointer)

agent_app = create_code_agent()