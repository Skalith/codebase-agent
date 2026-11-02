import os
import uuid

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage

from agent import llm_factory as lf
from agent.graph import agent_app, create_code_agent
from agent.llm_factory import LLMFactory
from agent.memory import memory_checkpointer


# ---------- tools ----------

def test_list_files_skips_dot_and_venv_dirs(tmp_path, monkeypatch):
    (tmp_path / "src").mkdir()
    (tmp_path / ".git").mkdir()
    (tmp_path / "venv").mkdir()
    (tmp_path / "src" / "app.py").write_text("print(1)")
    (tmp_path / "README.md").write_text("hi")
    (tmp_path / ".env.secret").write_text("k")
    (tmp_path / ".git" / "HEAD").write_text("ref")
    monkeypatch.chdir(tmp_path)

    from agent.tools import list_files

    files = list_files.invoke({})
    assert sorted(files) == ["README.md", os.path.join("src", "app.py")]


def test_read_file_blocks_path_traversal(tmp_path, monkeypatch):
    secret = tmp_path.parent / "outside.txt"
    secret.write_text("secret")
    monkeypatch.chdir(tmp_path)

    from agent.tools import read_file

    assert "outside the workspace" in read_file.invoke({"file_path": "../outside.txt"})


def test_search_code_returns_line_matches(tmp_path, monkeypatch):
    d = tmp_path / "pkg"
    d.mkdir()
    (d / "mod.py").write_text("def target_fn():\n    return 1\n")
    monkeypatch.chdir(tmp_path)

    from agent.tools import search_code

    hits = search_code.invoke({"query": "target_fn"})
    assert len(hits) == 1
    assert hits[0].startswith(os.path.join("pkg", "mod.py") + ":1:")


# ---------- llm_factory ----------

@pytest.fixture()
def clean_env(monkeypatch):
    for name in list(os.environ):
        if name.startswith(("OPENAI_API_KEY", "GROQ_API_KEY", "GEMINI_API_KEY", "OMNIROUTE_API_KEY")):
            monkeypatch.delenv(name)
    monkeypatch.delenv("ENABLE_OLLAMA", raising=False)


def test_provider_discovery_and_models(clean_env, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY_X", "gq-key")
    monkeypatch.setenv("GEMINI_API_KEY_9", "gm-key")
    monkeypatch.setenv("OPENAI_API_KEY_3", "oa-key")

    factory = LLMFactory()
    providers = {e["provider"] for e in factory.api_keys}
    assert providers == {"GROQ_API_KEY", "GEMINI_API_KEY", "OPENAI_API_KEY"}

    by_provider = {e["provider"]: factory.get_llm_for_entry(e) for e in factory.api_keys}
    assert by_provider["GROQ_API_KEY"].model_name == "openai/gpt-oss-120b"
    assert by_provider["GROQ_API_KEY"].openai_api_base == "https://api.groq.com/openai/v1"
    gem_name = str(
        getattr(by_provider["GEMINI_API_KEY"], "model", None)
        or getattr(by_provider["GEMINI_API_KEY"], "model_name", None)
    )
    assert "gemini" in gem_name.lower()
    assert by_provider["OPENAI_API_KEY"].model_name == "gpt-4o-mini"


def test_placeholder_keys_ignored(clean_env, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY_1", "your-key-here")
    assert [e["provider"] for e in LLMFactory().api_keys] == []


def test_ollama_disabled_by_default(clean_env):
    assert LLMFactory().ollama_enabled() is False


def test_memory_checkpointer_active():
    assert memory_checkpointer is not None


# ---------- graph integration (fake model, no network) ----------

from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult


class SimpleScripted(BaseChatModel):
    calls: int = 0

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.calls += 1
        if self.calls == 1:
            message = AIMessage(
                content="",
                tool_calls=[{"name": "list_files", "args": {}, "id": "call_1"}],
            )
        else:
            message = AIMessage(content="done: files listed")
        return ChatResult(generations=[ChatGeneration(message=message)])

    @property
    def _llm_type(self):
        return "simple-scripted"


def test_agent_tool_loop_with_fake_llm(tmp_path, monkeypatch, clean_env):
    (tmp_path / "a.py").write_text("x = 1\n")
    monkeypatch.chdir(tmp_path)

    workflow = create_code_agent(llm_override=SimpleScripted())
    config = {"configurable": {"thread_id": f"t_{uuid.uuid4().hex[:8]}"}}
    final = workflow.invoke({"messages": [HumanMessage(content="list files")]}, config=config)

    assert final["messages"][-1].content == "done: files listed"
    kinds = [type(m).__name__ for m in final["messages"]]
    assert "ToolMessage" in kinds  # the tools node actually ran


class ScriptedSkill(BaseChatModel):
    calls: int = 0

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.calls += 1
        if self.calls == 1:
            message = AIMessage(
                content="",
                tool_calls=[
                    {"name": "load_skill", "args": {"name": "web"}, "id": "c1"}
                ],
            )
        else:
            message = AIMessage(content="loaded the web skill")
        return ChatResult(generations=[ChatGeneration(message=message)])

    @property
    def _llm_type(self):
        return "scripted-skill"


def test_agent_loads_skill_through_graph(tmp_path, monkeypatch, clean_env):
    monkeypatch.chdir(tmp_path)
    workflow = create_code_agent(llm_override=ScriptedSkill())
    config = {"configurable": {"thread_id": f"t_{uuid.uuid4().hex[:8]}"}}
    final = workflow.invoke(
        {"messages": [HumanMessage(content="how do I scrape a web page?")]},
        config=config,
    )
    tool_contents = [
        str(m.content) for m in final["messages"] if getattr(m, "type", None) == "tool"
    ]
    assert any("Web research" in c for c in tool_contents)


def test_all_providers_fail_raises_clean_error(tmp_path, monkeypatch, clean_env):
    monkeypatch.setattr(
        lf.llm_factory,
        "api_keys",
        [{"provider": "OPENAI_API_KEY", "key": "bad"}],
    )

    def boom(entry):
        raise RuntimeError("401 unauthorized")

    monkeypatch.setattr(lf.llm_factory, "get_llm_for_entry", boom)

    with pytest.raises(RuntimeError, match="All providers failed"):
        agent_app.invoke(
            {"messages": [HumanMessage(content="hi")]},
            config={"configurable": {"thread_id": f"t_{uuid.uuid4().hex[:8]}"}},
        )


# ---------- skills ----------

def test_skill_frontmatter_and_catalog(tmp_path, monkeypatch):
    from agent import skills as sk

    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    (skills_dir / "demo.md").write_text(
        "---\nname: demo\ndescription: A demo skill.\ntriggers: demo, test\n---\n"
        "# Demo\nBody line.\n"
    )
    monkeypatch.setattr(sk, "SKILLS_DIR", str(skills_dir))

    catalog = sk.load_catalog()
    assert [e["name"] for e in catalog] == ["demo"]
    assert catalog[0]["description"] == "A demo skill."
    assert "Body line." in sk.get_skill("demo")


def test_get_skill_unknown_name_lists_available(tmp_path, monkeypatch):
    from agent import skills as sk

    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    (skills_dir / "demo.md").write_text("---\nname: demo\n---\nbody\n")
    monkeypatch.setattr(sk, "SKILLS_DIR", str(skills_dir))

    assert "no skill named 'nope'" in sk.get_skill("nope")


def test_bundled_skills_have_frontmatter():
    from agent.skills import load_catalog

    catalog = load_catalog()
    assert {e["name"] for e in catalog} == {
        "web", "github", "git", "filesystem", "testing", "coding",
    }
    assert all(e["description"] for e in catalog)


# ---------- web tools ----------

def test_github_blob_url_rewrites_to_raw():
    from agent.tools_web import _github_blob_to_raw

    assert _github_blob_to_raw(
        "https://github.com/octocat/Hello-World/blob/main/README.md"
    ) == "https://raw.githubusercontent.com/octocat/Hello-World/main/README.md"
    assert _github_blob_to_raw(
        "https://github.com/a/b/raw/v1/c.py"
    ) == "https://raw.githubusercontent.com/a/b/v1/c.py"
    assert _github_blob_to_raw("https://example.com/x") == "https://example.com/x"


def test_html_to_text_extracts_title_and_skips_script():
    from agent.tools_web import _html_to_text

    title, text = _html_to_text(
        "<html><head><title>Hi</title><style>b{}</style></head>"
        "<body><script>var x=1;</script><p>Hello world</p></body></html>"
    )
    assert title == "Hi"
    assert "Hello world" in text
    assert "var x" not in text


def test_fetch_url_rejects_non_http():
    from agent.tools_web import fetch_url

    assert "must start with http" in fetch_url.invoke({"url": "ftp://x"})


class _FakeScraplingPage:
    def __init__(self, body, ctype="text/html; charset=utf-8", status=200, raw_body=None):
        self.html_content = body
        self.headers = {"content-type": ctype}
        self.status = status
        self.body = raw_body if raw_body is not None else (
            body.encode() if isinstance(body, str) else body
        )
        self.encoding = "utf-8"


def test_http_get_uses_scrapling_when_available(monkeypatch):
    from agent import tools_web as tw

    class FakeFetcher:
        @staticmethod
        def get(url, timeout=None):
            return _FakeScraplingPage(
                "<html><head><title>Scr</title></head><body>"
                "<article><p>scrapling body text here</p></article></body></html>"
            )

    monkeypatch.setattr(tw, "_ScraplingFetcher", FakeFetcher)
    title, text = tw._http_get("https://x")
    assert title == "Scr"
    assert "scrapling body text" in text


def test_http_get_falls_back_to_requests(monkeypatch):
    from agent import tools_web as tw

    monkeypatch.setattr(tw, "_fetch_via_scrapling", lambda url: None)

    class FakeResp:
        headers = {"content-type": "text/html"}
        text = (
            "<html><head><title>Req</title></head><body>"
            "<p>requests body</p></body></html>"
        )

        def raise_for_status(self):
            pass

    monkeypatch.setattr(tw.requests, "get", lambda *a, **k: FakeResp())
    title, text = tw._http_get("https://x")
    assert title == "Req"
    assert "requests body" in text


def test_http_get_non_html_returns_raw(monkeypatch):
    from agent import tools_web as tw

    class FakeFetcher:
        @staticmethod
        def get(url, timeout=None):
            return _FakeScraplingPage(
                "<html><body>Hello World!\n</body></html>",
                ctype="text/plain",
                raw_body=b"Hello World!\n",
            )

    monkeypatch.setattr(tw, "_ScraplingFetcher", FakeFetcher)
    _title, text = tw._http_get("https://x")
    # must return the true body, not Scrapling's html-wrapped skeleton
    assert text.strip() == "Hello World!"


def test_scrapling_error_status_returns_none(monkeypatch):
    from agent import tools_web as tw

    class FakeFetcher:
        @staticmethod
        def get(url, timeout=None):
            return _FakeScraplingPage("nope", status=404)

    monkeypatch.setattr(tw, "_ScraplingFetcher", FakeFetcher)
    assert tw._fetch_via_scrapling("https://x") is None


# ---------- dev tools ----------

def test_build_test_command_defaults_and_override():
    from agent.tools_dev import _build_test_command

    assert "pytest -q" in _build_test_command()
    assert _build_test_command("tests/test_x.py").endswith("tests/test_x.py")
    assert _build_test_command("", "npx jest") == "npx jest"
    assert _build_test_command("a.test.js", "npx jest") == "npx jest a.test.js"


def test_build_lint_command_autodetect():
    from agent.tools_dev import _build_lint_command

    assert _build_lint_command("a.py") == "ruff check a.py"
    assert _build_lint_command("x.ts") == "npx eslint x.ts"
    assert _build_lint_command("a.py", "ruff") == "ruff check a.py"


def test_run_tests_reports_pass(tmp_path, monkeypatch):
    from agent.tools_dev import run_tests

    monkeypatch.chdir(tmp_path)
    out = run_tests.invoke({"command": "echo ok"})
    assert out.startswith("PASSED")
    assert "ok" in out


# ---------- skills (bundled) ----------

def test_list_and_load_bundled_skill():
    from agent.skills import list_skills, load_skill

    assert "web" in " ".join(list_skills.invoke({}))
    assert "git_commit" in load_skill.invoke({"name": "git"})


# ---------- filesystem tools ----------

def test_glob_files_finds_and_skips_ignored(tmp_path, monkeypatch):
    from agent.tools_fs import glob_files

    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("x")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "b.py").write_text("y")
    monkeypatch.chdir(tmp_path)

    out = glob_files.invoke({"pattern": "**/*.py"})
    assert os.path.join("src", "a.py") in out
    assert all(".git" not in x for x in out)


def test_create_directory(tmp_path, monkeypatch):
    from agent.tools_fs import create_directory

    monkeypatch.chdir(tmp_path)
    assert "OK" in create_directory.invoke({"path": "a/b/c"})
    assert (tmp_path / "a" / "b" / "c").is_dir()


def test_move_and_delete(monkeypatch, tmp_path):
    from agent.tools_fs import move_file, delete_file

    monkeypatch.chdir(tmp_path)
    (tmp_path / "a.txt").write_text("hi")

    assert "OK" in move_file.invoke({"src": "a.txt", "dest": "b.txt"})
    assert (tmp_path / "b.txt").exists()
    assert "OK" in delete_file.invoke({"path": "b.txt"})
    assert not (tmp_path / "b.txt").exists()


def test_move_file_refuses_existing_dest(monkeypatch, tmp_path):
    from agent.tools_fs import move_file

    monkeypatch.chdir(tmp_path)
    (tmp_path / "a.txt").write_text("a")
    (tmp_path / "b.txt").write_text("b")

    assert "already exists" in move_file.invoke({"src": "a.txt", "dest": "b.txt"})


# ---------- github tools ----------

def test_github_http_error_messages():
    from agent.tools_github import _explain_http_error

    assert "GITHUB_TOKEN" in _explain_http_error(401)
    assert "rate limit" in _explain_http_error(403)


def test_github_read_file_returns_raw(monkeypatch):
    from agent import tools_github

    monkeypatch.setattr(tools_github, "_get", lambda *a, **k: (True, "print(1)"))
    assert (
        tools_github.github_read_file.invoke(
            {"owner": "o", "repo": "r", "path": "a.py"}
        )
        == "print(1)"
    )


def test_github_list_issues_filters_prs(monkeypatch):
    from agent import tools_github

    data = [
        {"number": 1, "title": "bug", "html_url": "u1"},
        {"number": 2, "title": "pr", "html_url": "u2", "pull_request": {}},
    ]
    monkeypatch.setattr(tools_github, "_get", lambda *a, **k: (True, data))
    out = tools_github.github_list_issues.invoke({"owner": "o", "repo": "r"})
    assert any("#1 bug" in x for x in out)
    assert all("pr" not in x for x in out)


def test_github_create_issue_needs_token(monkeypatch):
    from agent import tools_github

    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    out = tools_github.github_create_issue.invoke(
        {"owner": "o", "repo": "r", "title": "t"}
    )
    assert "GITHUB_TOKEN" in out


# ---------- git tools ----------

def _init_repo(path):
    import subprocess

    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.t"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=path, check=True)


def test_git_status_reports_branch(tmp_path, monkeypatch):
    from agent.tools_git import git_status

    _init_repo(tmp_path)
    (tmp_path / "a.txt").write_text("hi")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("KRATOS_YES", "1")

    assert "exit code: 0" in git_status.invoke({})


def test_git_commit_and_log(tmp_path, monkeypatch):
    from agent.tools_git import git_commit, git_log

    _init_repo(tmp_path)
    (tmp_path / "a.txt").write_text("hi")
    monkeypatch.chdir(tmp_path)

    assert "exit code: 0" in git_commit.invoke({"message": "first"})
    assert "first" in git_log.invoke({})


# ---------- permissions ----------

def test_gated_and_free_tool_sets():
    from agent.permissions import GATED_TOOLS

    git_names = {
        "git_status", "git_diff", "git_log",
        "git_checkout", "git_commit", "git_push", "git_clone",
    }
    assert git_names <= GATED_TOOLS
    assert {"write_file", "edit_file", "run_command", "delete_file"} <= GATED_TOOLS
    for free in ["list_files", "read_file", "search_code", "web_search",
                 "fetch_url", "load_skill", "github_read_file"]:
        assert free not in GATED_TOOLS


def test_guard_passes_reads_through():
    from agent.permissions import guard_tools
    from agent.tools import list_files

    assert guard_tools([list_files])[0] is list_files


def test_guard_declined_returns_cancelled(monkeypatch):
    from agent import permissions
    from agent.tools_git import git_status

    monkeypatch.setattr(permissions, "confirm_action", lambda *a, **k: False)
    guarded = permissions.guard_tool(git_status)
    assert guarded is not git_status
    assert guarded.invoke({}).startswith("Cancelled")


def test_guard_approved_runs_tool(tmp_path, monkeypatch):
    from agent import permissions
    from agent.tools_git import git_status

    _init_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(permissions, "confirm_action", lambda *a, **k: True)

    assert "exit code: 0" in permissions.guard_tool(git_status).invoke({})


# ---------- approvals ----------

def test_confirm_action_auto_approves_with_env(monkeypatch):
    from agent.approvals import confirm_action

    monkeypatch.setenv("KRATOS_YES", "1")
    assert confirm_action("git push") is True


def test_confirm_action_defaults_to_no(monkeypatch):
    from agent import approvals

    monkeypatch.delenv("KRATOS_YES", raising=False)
    monkeypatch.setattr("builtins.input", lambda *a, **k: "")
    assert approvals.confirm_action("git commit") is False

    monkeypatch.setattr("builtins.input", lambda *a, **k: "y")
    assert approvals.confirm_action("git commit") is True


# ---------- history window / summary ----------

class FinalModel(BaseChatModel):
    text: str = "final answer"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        return ChatResult(
            generations=[ChatGeneration(message=AIMessage(content=self.text))]
        )

    @property
    def _llm_type(self):
        return "final-model"


def test_window_keeps_current_turn_and_summarizes_older(clean_env):
    from agent import graph as g

    msgs = []
    for i in range(20):
        msgs.append(HumanMessage(content=f"question {i}"))
        msgs.append(AIMessage(content=f"answer {i}"))
    msgs.append(HumanMessage(content="current task"))

    summary, recent = g._window_history(msgs)

    assert recent[-1].content == "current task"
    assert len(recent) <= g.RECENT_MESSAGE_LIMIT
    assert "question 0" in summary
    assert "question 19" not in summary
    assert all(m.content != "current task" for m in recent[:-1])


def test_window_never_starts_on_tool_message(clean_env):
    from agent import graph as g
    from langchain_core.messages import ToolMessage

    msgs = [HumanMessage(content="old")]
    msgs.append(AIMessage(content="", tool_calls=[{"name": "x", "args": {}, "id": "1"}]))
    msgs.append(ToolMessage(content="result", tool_call_id="1", name="x"))
    for i in range(g.RECENT_MESSAGE_LIMIT):
        msgs.append(HumanMessage(content=f"filler {i}"))
        msgs.append(AIMessage(content=f"reply {i}"))

    _summary, recent = g._window_history(msgs)
    assert recent[0].type != "tool"


# ---------- quota failover ----------

def test_quota_error_fails_over_and_cools_down(tmp_path, monkeypatch, clean_env):
    import time
    from agent import graph as g

    g._quota_blocked_until.clear()
    monkeypatch.setattr(
        lf.llm_factory,
        "api_keys",
        [
            {"provider": "GEMINI_API_KEY", "key": "x"},
            {"provider": "GROQ_API_KEY", "key": "y"},
        ],
    )

    def fake_get(entry):
        if entry["provider"] == "GEMINI_API_KEY":
            raise RuntimeError("429 RESOURCE_EXHAUSTED: quota exceeded")
        return FinalModel(text="final from groq")

    monkeypatch.setattr(lf.llm_factory, "get_llm_for_entry", fake_get)
    monkeypatch.setattr(lf.llm_factory, "ollama_enabled", lambda: False)

    workflow = create_code_agent()
    result = workflow.invoke(
        {"messages": [HumanMessage(content="hi")]},
        config={"configurable": {"thread_id": f"q_{uuid.uuid4().hex[:8]}"}},
    )
    assert result["messages"][-1].content == "final from groq"
    assert g._quota_blocked_until.get("GEMINI_API_KEY", 0) > time.time()
    g._quota_blocked_until.clear()


def test_quota_exhausted_key_is_skipped_next_call(monkeypatch, clean_env):
    import time
    from agent import graph as g

    g._quota_blocked_until.clear()
    g._quota_blocked_until["GEMINI_API_KEY"] = time.time() + 60
    calls = {"gemini": 0, "groq": 0}
    monkeypatch.setattr(
        lf.llm_factory,
        "api_keys",
        [
            {"provider": "GEMINI_API_KEY", "key": "x"},
            {"provider": "GROQ_API_KEY", "key": "y"},
        ],
    )

    def fake_get(entry):
        if entry["provider"] == "GEMINI_API_KEY":
            calls["gemini"] += 1
            raise RuntimeError("boom")
        calls["groq"] += 1
        return FinalModel(text="ok")

    monkeypatch.setattr(lf.llm_factory, "get_llm_for_entry", fake_get)
    monkeypatch.setattr(lf.llm_factory, "ollama_enabled", lambda: False)

    workflow = create_code_agent()
    workflow.invoke(
        {"messages": [HumanMessage(content="hi")]},
        config={"configurable": {"thread_id": f"q_{uuid.uuid4().hex[:8]}"}},
    )
    assert calls["gemini"] == 0
    assert calls["groq"] == 1
    g._quota_blocked_until.clear()


# ---------- trafilatura main-content extraction ----------

def test_html_to_text_prefers_main_content(clean_env):
    from agent.tools_web import _html_to_text

    html = (
        "<html><head><title>Doc</title></head><body>"
        "<nav>Home About Contact</nav>"
        "<article><h1>Real title</h1>"
        "<p>This is the real body paragraph with enough words to keep.</p></article>"
        "<footer>Copyright notice</footer>"
        "</body></html>"
    )
    title, text = _html_to_text(html, url="https://example.com/doc")
    assert "real body paragraph" in text
    assert "Copyright notice" not in text
