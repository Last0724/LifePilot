"""DeepSeek chat completion client.

Built on the official OpenAI SDK (``openai>=1.0.0``) pointed at the DeepSeek
endpoint, which exposes an OpenAI-compatible API. This module owns
credential resolution, error translation and JSON extraction, so
``core.ai_consultant`` can stay concerned with prompts and validation only.

The SDK client is created lazily: importing this module must not require an
API key, because the test suite runs without one.
"""

from __future__ import annotations

import json
import os
from typing import Any

__all__ = [
    "AIError",
    "AIConfigError",
    "AINetworkError",
    "AIResponseError",
    "DeepSeekClient",
    "extract_json_object",
    "read_api_key",
    "DEFAULT_BASE_URL",
    "DEFAULT_MODEL",
    "ENV_KEY_NAME",
]

DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-chat"
DEFAULT_TIMEOUT_SECONDS = 30
ENV_KEY_NAME = "DEEPSEEK_API_KEY"


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class AIError(Exception):
    """Base class for every failure raised by the AI module."""


class AIConfigError(AIError):
    """The API key is missing or rejected, or the SDK is not installed."""


class AINetworkError(AIError):
    """The provider could not be reached, timed out, or rate-limited us."""


class AIResponseError(AIError):
    """The provider replied, but the payload cannot be used."""


# ---------------------------------------------------------------------------
# Credentials
# ---------------------------------------------------------------------------


def read_api_key(explicit_key: str | None = None) -> str:
    """Resolve the DeepSeek API key.

    Priority order:
        1. the ``explicit_key`` argument (tests, or callers holding a key),
        2. the ``DEEPSEEK_API_KEY`` environment variable,
        3. Streamlit secrets (``.streamlit/secrets.toml``).

    Raises ``AIConfigError`` when none is set, so the caller gets an
    actionable message instead of an authentication failure from the server.
    """
    if explicit_key and explicit_key.strip():
        return explicit_key.strip()

    env_key = os.environ.get(ENV_KEY_NAME, "").strip()
    if env_key:
        return env_key

    secret = _read_streamlit_secret()
    if secret:
        return secret

    raise AIConfigError(
        f"{ENV_KEY_NAME} is not configured. Provide it as an argument, an "
        "environment variable, or an entry in .streamlit/secrets.toml."
    )


def _read_streamlit_secret() -> str:
    """Return the key from Streamlit secrets, or an empty string.

    Streamlit is an optional import: the module must work in a plain Python
    test run where Streamlit is not installed.
    """
    try:
        import streamlit as st  # noqa: PLC0415 - optional dependency
    except Exception:
        return ""

    try:
        value = st.secrets[ENV_KEY_NAME]
    except Exception:
        return ""

    return str(value).strip()


# ---------------------------------------------------------------------------
# JSON extraction
# ---------------------------------------------------------------------------


def extract_json_object(text: str) -> dict[str, Any]:
    """Parse a JSON object out of a model reply.

    Models routinely wrap their answer in markdown fences or add a sentence
    before and after the payload. This narrows the reply to the outermost
    ``{...}`` span before parsing, then rejects anything that is not a JSON
    object so callers never receive a list or a bare string.
    """
    if not isinstance(text, str) or not text.strip():
        raise AIResponseError("Model reply was empty.")

    cleaned = _strip_code_fence(text.strip())

    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise AIResponseError("Model reply contained no JSON object.")

    candidate = cleaned[start : end + 1]
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise AIResponseError(f"Model reply was not valid JSON: {exc}") from exc

    if not isinstance(parsed, dict):
        raise AIResponseError("Model reply was valid JSON but not an object.")

    return parsed


def _strip_code_fence(text: str) -> str:
    """Remove a leading/trailing ``` fence, including its language tag."""
    if not text.startswith("```"):
        return text

    lines = text.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip().startswith("```"):
        lines = lines[:-1]

    return "\n".join(lines).strip()


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class DeepSeekClient:
    """Chat-completion client for the DeepSeek API.

    The underlying SDK client is created on first use so that importing this
    module never requires credentials. An ``sdk`` instance may be injected for
    tests, which keeps the suite offline.
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        timeout: int | None = None,
        sdk: Any | None = None,
    ) -> None:
        self._api_key = api_key
        self.base_url = (base_url or DEFAULT_BASE_URL).rstrip("/")
        self.model = model or DEFAULT_MODEL
        self.timeout = timeout or DEFAULT_TIMEOUT_SECONDS
        self._sdk = sdk

    # -- public API ---------------------------------------------------------

    def chat(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.3,
        json_mode: bool = True,
    ) -> str:
        """Send a chat completion request and return the assistant text.

        Raises a subclass of ``AIError`` for every failure mode: missing key,
        unreachable host, timeout, HTTP error, or unusable body.
        """
        if not messages:
            raise AIResponseError("messages must not be empty.")

        client = self._get_client()

        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        try:
            response = client.chat.completions.create(**kwargs)
        except Exception as exc:  # translated below
            raise self._translate_error(exc) from exc

        return self._extract_content(response)

    def chat_json(
        self,
        messages: list[dict[str, str]],
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Send a request and parse the reply as a JSON object."""
        return extract_json_object(self.chat(messages, **kwargs))

    # -- internals ----------------------------------------------------------

    def _get_client(self) -> Any:
        """Return the SDK client, creating it on first use."""
        if self._sdk is not None:
            return self._sdk

        api_key = read_api_key(self._api_key)

        try:
            from openai import OpenAI  # noqa: PLC0415 - optional until used
        except ImportError as exc:
            raise AIConfigError(
                "The openai package is not installed. The Technical Lead "
                "needs to add 'openai>=1.0.0' to requirements.txt."
            ) from exc

        self._sdk = OpenAI(
            api_key=api_key,
            base_url=self.base_url,
            timeout=self.timeout,
        )
        return self._sdk

    @staticmethod
    def _translate_error(exc: Exception) -> AIError:
        """Map an SDK or transport failure onto the project's exceptions."""
        try:
            import openai  # noqa: PLC0415 - only needed when an error occurs
        except ImportError:
            return AIResponseError(f"AI client error: {exc}")

        if isinstance(exc, (openai.AuthenticationError, openai.PermissionDeniedError)):
            return AIConfigError(
                "DeepSeek rejected the API key. Check that it is valid and "
                "has not expired."
            )

        if isinstance(exc, (openai.APITimeoutError, openai.APIConnectionError)):
            return AINetworkError(f"Could not reach the DeepSeek API: {exc}")

        if isinstance(exc, (openai.RateLimitError, openai.InternalServerError)):
            return AINetworkError(f"DeepSeek is unavailable right now: {exc}")

        if isinstance(exc, openai.APIError):
            return AIResponseError(f"DeepSeek returned an error: {exc}")

        return AIResponseError(f"Unexpected AI client error: {exc}")

    @staticmethod
    def _extract_content(response: Any) -> str:
        """Read ``choices[0].message.content`` from an SDK response.

        ``getattr`` is used throughout so that a mock response behaves like a
        real one during tests.
        """
        choices = getattr(response, "choices", None)
        if not choices:
            raise AIResponseError("DeepSeek returned no choices.")

        message = getattr(choices[0], "message", None)
        if message is None:
            raise AIResponseError("DeepSeek returned a choice without a message.")

        content = getattr(message, "content", None)
        if not isinstance(content, str) or not content.strip():
            raise AIResponseError("DeepSeek returned an empty message.")

        return content
