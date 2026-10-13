"""Shared Portkey/OpenAI configuration for future agents."""

import os
from pathlib import Path

from openai import AsyncOpenAI
from dotenv import load_dotenv
from openai import OpenAI
from pydantic_ai.models.openai import OpenAIResponsesModel
from pydantic_ai.providers.openai import OpenAIProvider

MODEL = "gpt-6-luna"
PORTKEY_BASE_URL = "https://api.portkey.ai/v1"


def load_root_env() -> None:
    """Load the project .env, then the repository-root .env if present."""
    project_root = Path(__file__).resolve().parents[1]
    repository_root = Path(__file__).resolve().parents[3]
    for env_path in (project_root / ".env", repository_root / ".env"):
        if env_path.exists():
            load_dotenv(env_path, override=False)


def get_api_key() -> str:
    load_root_env()
    api_key = os.environ.get("PORTKEY_API_KEY")
    if not api_key:
        raise RuntimeError("PORTKEY_API_KEY is required for agent model calls")
    return api_key


def get_client() -> OpenAI:
    """Create a Portkey-backed synchronous OpenAI client."""
    api_key = get_api_key()
    return OpenAI(
        api_key=api_key,
        base_url=PORTKEY_BASE_URL,
        default_headers={"x-portkey-api-key": api_key},
    )


def run_agent(prompt: str, max_output_tokens: int = 300) -> str:
    """Run a future agent with the homework's single approved model."""
    response = get_client().responses.create(
        model=MODEL,
        input=prompt,
        max_output_tokens=max_output_tokens,
    )
    return response.output_text


def get_agent_model() -> OpenAIResponsesModel:
    """Create the single approved PydanticAI model through Portkey Responses."""
    api_key = get_api_key()
    async_client = AsyncOpenAI(
        api_key=api_key,
        base_url=PORTKEY_BASE_URL,
        default_headers={"x-portkey-api-key": api_key},
    )
    provider = OpenAIProvider(openai_client=async_client)
    return OpenAIResponsesModel(MODEL, provider=provider)
