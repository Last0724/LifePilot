"""Tests for ``core.ai_client``.

Every test runs offline. The HTTP layer is mocked, so no API key and no
network access are required - which is exactly why the module uses the
standard library instead of a third-party SDK.
"""

from __future__ import annotations

import io
import json
import os
import socket
import unittest
import urllib.error
from unittest import mock

from core import ai_client


def _fake_response(content: str) -> mock.MagicMock:
    """Build a urlopen-compatible context manager returning a chat envelope."""
    payload = {"choices": [{"message": {"content": content}}]}
    handle = mock.MagicMock()
    handle.read.return_value = json.dumps(payload).encode("utf-8")
    handle.__enter__.return_value = handle
    handle.__exit__.return_value = False
    return handle


def _raw_response(body: bytes) -> mock.MagicMock:
    """Build a context manager that returns an arbitrary raw body."""
    handle = mock.MagicMock()
    handle.read.return_value = body
    handle.__enter__.return_value = handle
    handle.__exit__.return_value = False
    return handle


def _http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        url="https://api.deepseek.com/chat/completions",
        code=code,
        msg="error",
        hdrs=None,
        fp=io.BytesIO(b'{"error": "boom"}'),
    )


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
    def _client(self) -> ai_client.DeepSeekClient:
        return ai_client.DeepSeekClient(api_key="test-key")

    def test_successful_call_returns_text(self):
        with mock.patch(
            "urllib.request.urlopen", return_value=_fake_response('{"ok": true}')
        ):
            text = self._client().chat([{"role": "user", "content": "hi"}])
        self.assertEqual(text, '{"ok": true}')

    def test_chat_json_returns_dict(self):
        with mock.patch(
            "urllib.request.urlopen",
            return_value=_fake_response("```json\n{\"ok\": true}\n```"),
        ):
            result = self._client().chat_json([{"role": "user", "content": "hi"}])
        self.assertEqual(result, {"ok": True})

    def test_empty_messages_are_rejected(self):
        with self.assertRaises(ai_client.AIResponseError):
            self._client().chat([])

    def test_unauthorized_raises_config_error(self):
        with mock.patch("urllib.request.urlopen", side_effect=_http_error(401)):
            with self.assertRaises(ai_client.AIConfigError):
                self._client().chat([{"role": "user", "content": "hi"}])

    def test_rate_limit_raises_network_error(self):
        with mock.patch("urllib.request.urlopen", side_effect=_http_error(429)):
            with self.assertRaises(ai_client.AINetworkError):
                self._client().chat([{"role": "user", "content": "hi"}])

    def test_server_error_raises_network_error(self):
        with mock.patch("urllib.request.urlopen", side_effect=_http_error(500)):
            with self.assertRaises(ai_client.AINetworkError):
                self._client().chat([{"role": "user", "content": "hi"}])

    def test_timeout_raises_network_error(self):
        with mock.patch(
            "urllib.request.urlopen", side_effect=socket.timeout("timed out")
        ):
            with self.assertRaises(ai_client.AINetworkError):
                self._client().chat([{"role": "user", "content": "hi"}])

    def test_empty_body_is_rejected(self):
        with mock.patch("urllib.request.urlopen", return_value=_raw_response(b"")):
            with self.assertRaises(ai_client.AIResponseError):
                self._client().chat([{"role": "user", "content": "hi"}])

    def test_missing_choices_are_rejected(self):
        with mock.patch(
            "urllib.request.urlopen", return_value=_raw_response(b'{"choices": []}')
        ):
            with self.assertRaises(ai_client.AIResponseError):
                self._client().chat([{"role": "user", "content": "hi"}])

    def test_non_json_body_is_rejected(self):
        with mock.patch(
            "urllib.request.urlopen", return_value=_raw_response(b"<html>502</html>")
        ):
            with self.assertRaises(ai_client.AIResponseError):
                self._client().chat([{"role": "user", "content": "hi"}])


if __name__ == "__main__":
    unittest.main()
