"""Tests for ``core.ai_client``.

Every test runs offline. A fake SDK object is injected instead of a real
``openai.OpenAI`` client, so no API key and no network access are required.
"""

from __future__ import annotations

import json
import os
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

from core import ai_client

try:
    import openai
except ImportError:  # pragma: no cover - exercised only without the SDK
    openai = None


def _response(content: str) -> SimpleNamespace:
    """Build an object shaped like a chat completion response."""
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
    )


def _sdk(content: str | None = None, error: Exception | None = None) -> SimpleNamespace:
    """Build a fake SDK whose create() returns content or raises error."""

    def create(**kwargs):
        if error is not None:
            raise error
        return _response(content or "")

    create_fn = mock.MagicMock(side_effect=create)
    return SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create_fn))
    )


def _make_error(error_class, message: str = "boom") -> BaseException:
    """Create a real SDK exception without its network-related arguments.

    openai 3.x builds these from HTTP responses, which would drag an extra
    HTTP dependency into the test suite. Bypassing ``__init__`` still produces
    an instance that ``isinstance`` recognises and that can be raised.
    """
    error = error_class.__new__(error_class)
    Exception.__init__(error, message)
    return error


class ExtractJsonObjectTests(unittest.TestCase):
    def test_plain_object(self):
        self.assertEqual(ai_client.extract_json_object('{"a": 1}'), {"a": 1})

    def test_markdown_fence_is_stripped(self):
        result = ai_client.extract_json_object('```json\n{"a": 2}\n```')
        self.assertEqual(result, {"a": 2})

    def test_surrounding_prose_is_ignored(self):
        text = 'Sure, here it is: {"a": 3}. Hope that helps.'
        self.assertEqual(ai_client.extract_json_object(text), {"a": 3})

    def test_nested_structure_is_preserved(self):
        result = ai_client.extract_json_object('{"outer": {"inner": [1, 2]}}')
        self.assertEqual(result["outer"]["inner"], [1, 2])

    def test_empty_string_is_rejected(self):
        with self.assertRaises(ai_client.AIResponseError):
            ai_client.extract_json_object("   ")

    def test_text_without_object_is_rejected(self):
        with self.assertRaises(ai_client.AIResponseError):
            ai_client.extract_json_object("no json here")

    def test_truncated_object_is_rejected(self):
        with self.assertRaises(ai_client.AIResponseError):
            ai_client.extract_json_object('{"a": 1')

    def test_array_is_rejected(self):
        with self.assertRaises(ai_client.AIResponseError):
            ai_client.extract_json_object("[1, 2, 3]")

    def test_non_string_is_rejected(self):
        with self.assertRaises(ai_client.AIResponseError):
            ai_client.extract_json_object(None)  # type: ignore[arg-type]


class ReadApiKeyTests(unittest.TestCase):
    def test_explicit_key_wins(self):
        with mock.patch.dict(os.environ, {"DEEPSEEK_API_KEY": "env-key"}):
            self.assertEqual(ai_client.read_api_key("explicit"), "explicit")

    def test_environment_variable_is_used(self):
        with mock.patch.dict(os.environ, {"DEEPSEEK_API_KEY": "env-key"}):
            self.assertEqual(ai_client.read_api_key(), "env-key")

    def test_missing_key_raises_config_error(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ai_client.AIConfigError):
                ai_client.read_api_key()


class ChatTests(unittest.TestCase):
    def test_successful_call_returns_text(self):
        client = ai_client.DeepSeekClient(api_key="test-key", sdk=_sdk('{"ok": true}'))
        text = client.chat([{"role": "user", "content": "hi"}])
        self.assertEqual(text, '{"ok": true}')

    def test_chat_json_returns_dict(self):
        client = ai_client.DeepSeekClient(
            api_key="test-key",
            sdk=_sdk("```json\n{\"ok\": true}\n```"),
        )
        self.assertEqual(
            client.chat_json([{"role": "user", "content": "hi"}]),
            {"ok": True},
        )

    def test_json_mode_sends_response_format(self):
        fake = _sdk('{"ok": true}')
        client = ai_client.DeepSeekClient(api_key="test-key", sdk=fake)

        client.chat([{"role": "user", "content": "hi"}])

        sent = fake.chat.completions.create.call_args.kwargs
        self.assertEqual(sent["response_format"], {"type": "json_object"})

    def test_json_mode_can_be_disabled(self):
        fake = _sdk("plain text")
        client = ai_client.DeepSeekClient(api_key="test-key", sdk=fake)

        client.chat([{"role": "user", "content": "hi"}], json_mode=False)

        sent = fake.chat.completions.create.call_args.kwargs
        self.assertNotIn("response_format", sent)

    def test_empty_messages_are_rejected(self):
        client = ai_client.DeepSeekClient(api_key="test-key", sdk=_sdk("{}"))
        with self.assertRaises(ai_client.AIResponseError):
            client.chat([])

    def test_missing_sdk_raises_config_error(self):
        client = ai_client.DeepSeekClient(api_key="test-key")
        with mock.patch.dict(sys.modules, {"openai": None}):
            with self.assertRaises(ai_client.AIConfigError):
                client.chat([{"role": "user", "content": "hi"}])

    def test_response_without_choices_is_rejected(self):
        fake = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(
                    create=mock.MagicMock(return_value=SimpleNamespace(choices=[]))
                )
            )
        )
        client = ai_client.DeepSeekClient(api_key="test-key", sdk=fake)
        with self.assertRaises(ai_client.AIResponseError):
            client.chat([{"role": "user", "content": "hi"}])

    def test_empty_content_is_rejected(self):
        client = ai_client.DeepSeekClient(api_key="test-key", sdk=_sdk("   "))
        with self.assertRaises(ai_client.AIResponseError):
            client.chat([{"role": "user", "content": "hi"}])


@unittest.skipIf(openai is None, "openai SDK is not installed")
class ErrorTranslationTests(unittest.TestCase):
    """Verify that SDK exceptions map onto the project's own hierarchy."""

    def _assert_maps_to(self, error: BaseException, expected: type) -> None:
        client = ai_client.DeepSeekClient(api_key="test-key", sdk=_sdk(error=error))
        with self.assertRaises(expected):
            client.chat([{"role": "user", "content": "hi"}])

    def test_authentication_error_maps_to_config_error(self):
        self._assert_maps_to(
            _make_error(openai.AuthenticationError), ai_client.AIConfigError
        )

    def test_permission_denied_maps_to_config_error(self):
        self._assert_maps_to(
            _make_error(openai.PermissionDeniedError), ai_client.AIConfigError
        )

    def test_timeout_maps_to_network_error(self):
        self._assert_maps_to(
            _make_error(openai.APITimeoutError), ai_client.AINetworkError
        )

    def test_connection_error_maps_to_network_error(self):
        self._assert_maps_to(
            _make_error(openai.APIConnectionError), ai_client.AINetworkError
        )

    def test_rate_limit_maps_to_network_error(self):
        self._assert_maps_to(
            _make_error(openai.RateLimitError), ai_client.AINetworkError
        )

    def test_server_error_maps_to_network_error(self):
        self._assert_maps_to(
            _make_error(openai.InternalServerError), ai_client.AINetworkError
        )

    def test_generic_api_error_maps_to_response_error(self):
        self._assert_maps_to(_make_error(openai.APIError), ai_client.AIResponseError)

    def test_unexpected_exception_maps_to_response_error(self):
        self._assert_maps_to(RuntimeError("boom"), ai_client.AIResponseError)


if __name__ == "__main__":
    unittest.main()
