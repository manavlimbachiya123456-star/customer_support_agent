"""Settings. Everything comes from environment variables (see .env.example)."""
import os

from dotenv import load_dotenv

load_dotenv()

GEMINI_MODEL = "gemini-2.5-flash"
EMBED_MODEL = "gemini-embedding-001"
EMBED_DIM = 768


def get(name: str, default: str = "") -> str:
    return os.getenv(name, default)


def flag(name: str, default: str = "false") -> bool:
    return get(name, default).lower() == "true"


def mock_llm() -> bool:
    """MOCK_LLM=true -> no Gemini calls. A rule-based agent and hash embeddings are used."""
    return flag("MOCK_LLM", "true")
