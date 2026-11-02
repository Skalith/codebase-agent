import os
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain_core.language_models.chat_models import BaseChatModel

try:
    from langchain_ollama import ChatOllama
except ImportError:
    ChatOllama = None

try:
    # Native Gemini client: it handles "thought signatures" on tool calls
    # internally. The OpenAI-compat endpoint drops them, which makes thinking
    # models reject any multi-round tool loop with a 400.
    from langchain_google_genai import ChatGoogleGenerativeAI
except ImportError:
    ChatGoogleGenerativeAI = None

load_dotenv()

# All three providers below speak the OpenAI API protocol,
# so a single ChatOpenAI client with a custom base_url covers them.
PROVIDER_DEFAULTS = {
    "OPENAI_API_KEY": {"base_url": None, "model": "gpt-4o-mini"},
    "GROQ_API_KEY": {
        "base_url": "https://api.groq.com/openai/v1",
        "model": "openai/gpt-oss-120b",
    },
    "GEMINI_API_KEY": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "model": "gemini-3.7-flash",
        # Thinking models emit thought_signature parts that the OpenAI-compat
        # tool-calling loop does not replay correctly -> 400 errors. Disabling
        # reasoning via reasoning_effort avoids it.
        "extra_body": {"reasoning_effort": "none"},
    },
    "OMNIROUTE_API_KEY": {
        "base_url": "http://localhost:20128/v1",
        "model": "auto/best-coding",
    },
}


def _is_placeholder(value: str) -> bool:
    return not value or value.lower().startswith("your-")


# Friendly CLI names -> credential env-var prefixes.
PROVIDER_ALIASES = {
    "openai": "OPENAI_API_KEY",
    "groq": "GROQ_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "omniroute": "OMNIROUTE_API_KEY",
}


class LLMFactory:
    def __init__(self):
        # Discover every provider credential defined in the environment.
        self.api_keys = []  # list of {"provider", "key"} entries
        for prefix, defaults in PROVIDER_DEFAULTS.items():
            for name, value in os.environ.items():
                if name.startswith(prefix) and not _is_placeholder(value):
                    self.api_keys.append({"provider": prefix, "key": value})
        self.current_key_index = 0
        self._local_llm = None

    def get_next_entry(self):
        if not self.api_keys:
            return None
        entry = self.api_keys[self.current_key_index]
        self.current_key_index = (self.current_key_index + 1) % len(self.api_keys)
        return entry

    def get_llm_for_entry(self, entry: dict) -> BaseChatModel:
        """Build a client for one specific discovered credential."""
        defaults = PROVIDER_DEFAULTS[entry["provider"]]
        if entry["provider"] == "GEMINI_API_KEY" and ChatGoogleGenerativeAI is not None:
            return ChatGoogleGenerativeAI(
                model=defaults["model"],
                temperature=0,
                google_api_key=entry["key"],
            )
        return ChatOpenAI(
            model=defaults["model"],
            temperature=0,
            api_key=entry["key"],
            base_url=defaults["base_url"],
            **({"extra_body": defaults["extra_body"]} if "extra_body" in defaults else {}),
        )

    def get_local_llm(self):
        """Create the Ollama client connection.

        NOTE: no Ollama model is installed on this device, so this is
        connection setup ONLY. It is never invoked automatically; the
        remote-failure path in graph.py raises instead. Using it requires
        explicitly setting ENABLE_OLLAMA=1 in the environment.
        """
        if self._local_llm is None:
            if ChatOllama is None:
                raise RuntimeError(
                    "langchain-ollama is not installed. Run: pip install langchain-ollama"
                )
            self._local_llm = ChatOllama(model="qwen2.5-coder", temperature=0)
        return self._local_llm

    def ollama_enabled(self) -> bool:
        """True only when the user explicitly opts in via ENABLE_OLLAMA=1."""
        return os.environ.get("ENABLE_OLLAMA") == "1"

    def available_models(self) -> list[str]:
        """Provider aliases usable with /model, based on discovered credentials."""
        reverse = {v: k for k, v in PROVIDER_ALIASES.items()}
        names = [reverse[e["provider"]] for e in self.api_keys]
        if ChatOllama is not None:
            names.append("ollama")
        return names

    def get_llm_by_name(self, name: str) -> BaseChatModel:
        """Build a client for a caller-chosen provider alias or 'ollama'."""
        name = name.strip().lower()
        if name == "ollama":
            return self.get_local_llm()
        prefix = PROVIDER_ALIASES.get(name)
        if prefix is None:
            raise ValueError(
                f"Unknown model '{name}'. Choose from: {', '.join(self.available_models())}"
            )
        entry = next((e for e in self.api_keys if e["provider"] == prefix), None)
        if entry is None:
            raise ValueError(
                f"No {prefix} configured. Available: {', '.join(self.available_models())}"
            )
        return self.get_llm_for_entry(entry)

    def get_llm(self, model_name: str = "gpt-4o-mini", use_local: bool = False) -> BaseChatModel:
        if (use_local and self.ollama_enabled()) or not self.api_keys:
            return self.get_local_llm()

        entry = self.get_next_entry()
        defaults = PROVIDER_DEFAULTS[entry["provider"]]
        # Only OpenAI accepts an arbitrary caller-chosen model; other
        # providers use their own tested default.
        model = model_name if entry["provider"] == "OPENAI_API_KEY" else defaults["model"]
        return ChatOpenAI(
            model=model,
            temperature=0,
            api_key=entry["key"],
            base_url=defaults["base_url"],
        )


llm_factory = LLMFactory()
