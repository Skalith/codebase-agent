import os
import logging

from dotenv import load_dotenv

load_dotenv()

# Suppress Langfuse SDK noise (timeout/export errors).
logging.getLogger("langfuse").setLevel(logging.CRITICAL)
logging.getLogger("httpx").setLevel(logging.CRITICAL)

try:
    from langfuse.langchain import CallbackHandler
except ImportError:
    CallbackHandler = None

_has_keys = bool(
    os.environ.get("LANGFUSE_SECRET_KEY") and os.environ.get("LANGFUSE_PUBLIC_KEY")
)

# Disable Langfuse unless explicitly opted in via ENABLE_LANGFUSE=1.
# The SDK silently spams timeout errors otherwise.
_enabled = os.environ.get("ENABLE_LANGFUSE") == "1"
langfuse_handler = CallbackHandler() if (_has_keys and CallbackHandler and _enabled) else None


def trace_callbacks():
    """Return the callback list to merge into an invocation config."""
    return [langfuse_handler] if langfuse_handler else []
