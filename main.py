import argparse
import os
import shutil
import time
import uuid
from datetime import datetime

try:
    import readline  # noqa: F401  (line editing/history; unavailable on Windows)
except ImportError:
    pass

from langchain_core.messages import HumanMessage
from agent.graph import create_code_agent
from agent.llm_factory import llm_factory
from agent.tracing import trace_callbacks

# ── ANSI Colors ──────────────────────────────────────────────────────────────
DIM      = "\033[2m"
RED      = "\033[31m"
ORANGE   = "\033[33m"
GREEN    = "\033[32m"
LIME     = "\033[92m"
CYAN     = "\033[96m"
MAGENTA  = "\033[95m"
BOLD     = "\033[1m"
RESET    = "\033[0m"


def show_splash():
    """KRATOS splash screen – macOS-style terminal graphic."""
    width = 52

    def edge(char="─"):
        return DIM + char * width + RESET

    def dot(color, label="●"):
        return f"  {color}{BOLD}{label}{RESET}"

    # clear screen for a clean activation feel
    os.system("clear")

    def row(visible, styled=""):
        """Box row: pad by the visible (uncoloured) text length."""
        pad = " " * max(width - len(visible), 0)
        return f"  {DIM}│{RESET}{styled or visible}{pad}{DIM}│{RESET}"

    lines = [
        f"  {DIM}┌{edge('─')}┐{RESET}",
        row("  ●  ●  ●", f"{dot(RED)}{dot(ORANGE)}{dot(GREEN)}"),
        f"  {DIM}├{edge('─')}┤{RESET}",
        row(""),
        row("     ⚔  K R A T O S ⚔", f"     {LIME}{BOLD}⚔  K R A T O S ⚔{RESET}"),
        row("     Autonomous Coding Agent", f"     {CYAN}Autonomous Coding Agent{RESET}"),
        row(""),
        row("     $ ~/workspace", f"     {LIME}$ {CYAN}~/workspace{RESET}"),
        row("     > _", f"     {MAGENTA}{BOLD}> _{RESET}"),
        f"  {DIM}└{edge('─')}┘{RESET}",
    ]

    for line in lines:
        print(line)
    print()


def _right(text: str, color: str = DIM) -> str:
    """Right-align a short line to the terminal width; leaves content alone."""
    width = shutil.get_terminal_size((80, 20)).columns
    pad = " " * max(width - len(text) - 2, 0)
    return f"{pad}{color}{text}{RESET}"


def new_config(thread_id: str) -> dict:
    return {
        "configurable": {"thread_id": thread_id},
        "callbacks": trace_callbacks(),
    }


def resolve_llm(choice: str):
    """Map an external provider choice to (llm_override, label).

    'auto' (or empty) means: no override, use the built-in fallback chain.
    """
    choice = (choice or "auto").strip().lower()
    if choice in ("", "auto"):
        return None, "auto"
    return llm_factory.get_llm_by_name(choice), choice


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        prog="kratos",
        description="KRATOS — autonomous coding agent.",
    )
    parser.add_argument(
        "-m",
        "--model",
        default=os.environ.get("KRATOS_MODEL", "auto"),
        help=(
            "Provider to use: auto, openai, groq, gemini, omniroute, ollama "
            "(can also be set with the KRATOS_MODEL env var)."
        ),
    )
    return parser.parse_args(argv)


def main():
    args = parse_args()
    show_splash()

    try:
        llm_override, current_model = resolve_llm(args.model)
    except Exception as e:
        print(f"❌ {e}")
        llm_override, current_model = None, "auto"

    print(f"🧠 Model: {current_model}")
    print("Type 'exit' or 'quit' to close. Commands: /new, /model\n" + "-" * 60)

    thread_id = "cli_session_main"
    turns_in_thread = 0
    NEW_THREAD_HINT_AFTER = 6
    app = create_code_agent(llm_override=llm_override)

    while True:
        try:
            query = input("\n👤 You: ")
            if query.strip().lower() in ["exit", "quit"]:
                print("Goodbye!")
                break
            if query.strip() == "/new":
                thread_id = f"cli_session_{uuid.uuid4().hex[:8]}"
                turns_in_thread = 0
                print(f"✨ Started new conversation (thread: {thread_id})")
                continue
            if query.strip().startswith("/model"):
                parts = query.strip().split()
                if len(parts) == 1:
                    models = ", ".join(["auto"] + llm_factory.available_models())
                    print(f"🧠 Current model: {current_model} | Available: {models}")
                    continue
                try:
                    choice = parts[1].lower()
                    llm = None if choice == "auto" else llm_factory.get_llm_by_name(choice)
                    app = create_code_agent(llm_override=llm)
                    current_model = choice
                    print(f"✅ Switched to '{current_model}' (conversation history kept)")
                except Exception as e:
                    print(f"❌ {str(e)}")
                continue
            if not query.strip():
                continue

            config = new_config(thread_id)
            initial_state = {"messages": [HumanMessage(content=query)]}

            req_at = datetime.now().strftime("%H:%M:%S")
            started = time.perf_counter()
            print("\n⚔️ KRATOS ⚔️: ", end="", flush=True)

            # Stream tokens as they arrive; only AI-node chunks carry content.
            for chunk, metadata in app.stream(
                initial_state, config=config, stream_mode="messages"
            ):
                if metadata.get("langgraph_node") == "agent":
                    text = chunk.content
                    if isinstance(text, list):
                        text = "".join(
                            part.get("text", "")
                            for part in text
                            if isinstance(part, dict)
                        )
                    if text:
                        print(text, end="", flush=True)

            elapsed = time.perf_counter() - started
            resp_at = datetime.now().strftime("%H:%M:%S")
            print("\n" + _right(f"req {req_at} | resp {resp_at} | {elapsed:.1f}s"))
            turns_in_thread += 1
            if turns_in_thread >= NEW_THREAD_HINT_AFTER:
                print(
                    f"{DIM}  tip: this thread is getting long — use /new to start "
                    f"fresh on a new topic (sends less context){RESET}"
                )
                turns_in_thread = 0
            print("-" * 60)

        except KeyboardInterrupt:
            print("\nExiting...")
            break
        except Exception as e:
            print(f"\n❌ Error: {str(e)}")

if __name__ == "__main__":
    main()
