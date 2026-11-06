"""Configuration: the one model, the Portkey connection, and project paths.

The model is defined in exactly one place (MODEL_ID). OPENAI_MODEL may be set,
but only to that same value; anything else stops the backend with an error
instead of quietly running a different model. There is no fallback model.
"""

from __future__ import annotations

import os
from functools import cache
from pathlib import Path

from dotenv import load_dotenv
from pydantic_ai.models.openai import OpenAIChatModel, OpenAIChatModelSettings
from pydantic_ai.providers.openai import OpenAIProvider

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = PROJECT_ROOT / "backend"
PROMPTS_DIR = BACKEND_DIR / "prompts"
OUTPUT_DIR = BACKEND_DIR / "output"
MCP_CONFIG = PROJECT_ROOT / "mcp.json"
MCP_SERVER_NAME = "campus-customs"

load_dotenv(PROJECT_ROOT / ".env")
os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")

MODEL_ID = "gpt-6-luna"
PORTKEY_BASE_URL = "https://api.portkey.ai/v1"


class ConfigError(RuntimeError):
    """The environment is missing something the agents need."""


def model_id() -> str:
    configured = os.getenv("OPENAI_MODEL", MODEL_ID).strip()
    if configured != MODEL_ID:
        raise ConfigError(
            f"OPENAI_MODEL is {configured!r}, but this project runs every agent on {MODEL_ID!r} only. "
            "Remove OPENAI_MODEL or set it to that value."
        )
    return configured


@cache
def build_model() -> OpenAIChatModel:
    """The single model object every agent shares: gpt-6-luna through Portkey."""
    api_key = os.getenv("PORTKEY_API_KEY")
    if not api_key:
        raise ConfigError("PORTKEY_API_KEY is not set. Copy .env.example to .env in hw5 and fill it in.")
    provider = OpenAIProvider(base_url=os.getenv("PORTKEY_BASE_URL", PORTKEY_BASE_URL), api_key=api_key)
    return OpenAIChatModel(model_id(), provider=provider)


def model_settings(max_output_tokens: int) -> OpenAIChatModelSettings:
    # Luna models reject function tools on /v1/chat/completions unless reasoning
    # effort is 'none' (found in HW 4); every agent here relies on tools.
    return OpenAIChatModelSettings(
        openai_reasoning_effort=os.getenv("LLM_REASONING_EFFORT", "none"),
        max_tokens=max_output_tokens,
    )


def audit_trail_path() -> Path:
    """backend/output/audit_trail.json, or AUDIT_TRAIL_PATH for isolated tests."""
    override = os.getenv("AUDIT_TRAIL_PATH")
    return Path(override) if override else OUTPUT_DIR / "audit_trail.json"
