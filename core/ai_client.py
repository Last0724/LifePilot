"""DeepSeek chat completion client.

This module owns every detail of talking to the DeepSeek API: resolving
credentials, performing the HTTP request, translating transport failures
into a small set of project exceptions, and turning a model reply into a
Python dictionary.

Only the standard library is used. That keeps the module importable and
testable on a machine where no third-party package has been installed yet,
which matters because ``requirements.txt`` is owned by the Technical Lead.

Business rules (what to ask, how to validate a profile) live in
``core.ai_consultant``. This file stays transport-focused.
"""

from __future__ import annotations

import json
import os
import socket
import urllib.error
import urllib.request
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
    """The API key is missing, or the provider rejected it."""


class AINetworkError(AIError):
    """The provider could not be reached, or the request timed out."""


class AIResponseError(AIError):
    """The provider replied, but the payload cannot be used."""


# ---------------------------------------------------------------------------
# Credentials
# ---------------------------------------------------------------------------


def read_api_key(explicit_key: str | None = None) -> str:
    """Resolve the DeepSeek API key.

    Priority order:
        1. the ``explicit_key`` argument (used by tests and by callers that
           already hold a key),
        2. the ``DEEPSEEK_API_KEY`` environment variable,
        3. Streamlit secrets (``.streamlit/secrets.toml``).

    Raises ``AIConfigError`` when none of them is set, so the caller gets an
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

    Streamlit is an optional import here: the module must work in a plain
    Python test run where Streamlit is not installed.
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
    """Minimal chat-completion client for the DeepSeek API.

    The client is stateless between calls apart from its configuration, so a
    single instance can be reused across a Streamlit session.
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        timeout: int | None = None,
    ) -> None:
        self._api_key = api_key
        self.base_url = (base_url or DEFAULT_BASE_URL).rstrip("/")
        self.model = model or DEFAULT_MODEL
        self.timeout = timeout or DEFAULT_TIMEOUT_SECONDS

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

        api_key = read_api_key(self._api_key)

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "stream": False,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        request = urllib.request.Request(
            url=f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            method="POST",
        )

        raw_body = self._post(request)
        return self._extract_content(raw_body)

    def chat_json(
        self,
        messages: list[dict[str, str]],
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Send a request and parse the reply as a JSON object."""
        return extract_json_object(self.chat(messages, **kwargs))

    # -- internals ----------------------------------------------------------

    def _post(self, request: urllib.request.Request) -> str:
        """Execute the request and return the decoded body."""
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            raise self._translate_http_error(exc) from exc
        except (urllib.error.URLError, socket.timeout, TimeoutError) as exc:
            raise AINetworkError(f"Could not reach the DeepSeek API: {exc}") from exc

    @staticmethod
    def _translate_http_error(exc: urllib.error.HTTPError) -> AIError:
        """Map an HTTP status onto the project's exception hierarchy."""
        detail = ""
        try:
            detail = exc.read().decode("utf-8", errors="replace")[:200]
        except Exception:
            detail = ""

        if exc.code in (401, 403):
            return AIConfigError(
                f"DeepSeek rejected the API key (HTTP {exc.code}). "
                "Check that the key is valid and not expired."
            )
        if exc.code == 429:
            return AINetworkError(
                "DeepSeek rate limit reached (HTTP 429). Retry after a pause."
            )
        if 500 <= exc.code < 600:
            return AINetworkError(f"DeepSeek service error (HTTP {exc.code}).")

        return AIResponseError(
            f"Unexpected DeepSeek response (HTTP {exc.code}): {detail}"
        )

    @staticmethod
    def _extract_content(raw_body: str) -> str:
        """Validate the envelope and return ``choices[0].message.content``."""
        if not raw_body or not raw_body.strip():
            raise AIResponseError("DeepSeek returned an empty body.")

        try:
            data = json.loads(raw_body)
        except json.JSONDecodeError as exc:
            raise AIResponseError("DeepSeek returned a non-JSON body.") from exc

        if not isinstance(data, dict):
            raise AIResponseError("DeepSeek returned an unexpected payload shape.")

        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            raise AIResponseError("DeepSeek returned no choices.")

        first = choices[0]
        if not isinstance(first, dict):
            raise AIResponseError("DeepSeek returned a malformed choice.")

        message = first.get("message")
        if not isinstance(message, dict):
            raise AIResponseError("DeepSeek returned a choice without a message.")

        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise AIResponseError("DeepSeek returned an empty message.")

        return content
