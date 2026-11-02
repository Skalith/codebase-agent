import os

from langchain_core.tools import tool

from agent.paths import PROJECT_ROOT

SKILLS_DIR = os.path.join(PROJECT_ROOT, "agent", "skills")


def _parse_frontmatter(text: str):
    """Split a leading ``---`` fenced block of ``key: value`` lines from the body.

    Returns (metadata_dict, body). Files without frontmatter return ({}, text).
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text
    meta = {}
    end = None
    for i, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            end = i
            break
        if ":" in line:
            key, _, value = line.partition(":")
            meta[key.strip()] = value.strip()
    if end is None:
        return {}, text
    return meta, "\n".join(lines[end + 1:]).lstrip("\n")


def _iter_skill_paths():
    if not os.path.isdir(SKILLS_DIR):
        return
    for entry in sorted(os.listdir(SKILLS_DIR)):
        if entry.endswith(".md"):
            yield os.path.join(SKILLS_DIR, entry)


def load_catalog() -> list[dict]:
    """Return one entry per skill file: name, description, triggers, path."""
    catalog = []
    for path in _iter_skill_paths():
        try:
            with open(path, "r", encoding="utf-8") as f:
                meta, _ = _parse_frontmatter(f.read())
        except OSError:
            continue
        stem = os.path.splitext(os.path.basename(path))[0]
        catalog.append(
            {
                "name": meta.get("name") or stem,
                "description": meta.get("description", ""),
                "triggers": meta.get("triggers", ""),
                "path": path,
            }
        )
    return catalog


def get_skill(name: str) -> str:
    """Return the full body of the named skill, or a helpful error string."""
    slug = name.strip().lower().replace(" ", "-")
    catalog = load_catalog()
    for entry in catalog:
        stem = os.path.splitext(os.path.basename(entry["path"]))[0]
        if entry["name"].lower() == slug or stem == slug:
            with open(entry["path"], "r", encoding="utf-8") as f:
                _, body = _parse_frontmatter(f.read())
            return body
    available = ", ".join(e["name"] for e in catalog) or "(none installed)"
    return f"Error: no skill named '{name}'. Available skills: {available}"


def catalog_prompt() -> str:
    """One line per skill, for the system prompt's skill index."""
    return "\n".join(f"- {e['name']}: {e['description']}" for e in load_catalog())


@tool
def list_skills() -> list[str]:
    """List the skills available to you (name and when each one applies)."""
    entries = load_catalog()
    if not entries:
        return ["(no skills installed)"]
    return [f"{e['name']}: {e['description']}" for e in entries]


@tool
def load_skill(name: str) -> str:
    """Load a skill's full instructions before doing a task it covers.

    Call list_skills first when you are unsure which skill applies, then load
    and follow the matching skill.
    """
    return get_skill(name)


skill_tools = [list_skills, load_skill]
