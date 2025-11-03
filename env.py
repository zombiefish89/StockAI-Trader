"""Load environment variables from a .env file if python-dotenv is available."""

from __future__ import annotations

try:  # pragma: no cover - optional dependency
    from dotenv import load_dotenv  # type: ignore
except ImportError:  # pragma: no cover
    def load_dotenv(*args, **kwargs):  # type: ignore
        return False

# Load default .env (located at project root)
load_dotenv()
