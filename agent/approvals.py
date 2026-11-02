import os

AUTO_APPROVE_ENV = "KRATOS_YES"


def confirm_action(action: str, detail: str = "") -> bool:
    """Ask the user to approve a write or destructive action before it runs.

    Returns True only on an explicit yes. Set KRATOS_YES=1 to skip the prompt
    (used by tests and non-interactive scripts).
    """
    if os.environ.get(AUTO_APPROVE_ENV) == "1":
        return True
    prompt = f"⚠  Approve {action}"
    if detail:
        prompt += f" [{detail}]"
    prompt += " (y/N): "
    try:
        answer = input(prompt).strip().lower()
    except (EOFError, KeyboardInterrupt):
        return False
    return answer in ("y", "yes")
