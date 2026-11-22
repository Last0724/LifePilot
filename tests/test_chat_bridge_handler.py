"""Offline tests for the chat bridge dispatcher (core.chat_bridge).

All tests run without a real DeepSeek API key: chat operations use the
FakeClient from tests.test_chat_planner, schedule operations are pure
Python. Real API verification is tracked separately in the Phase 3B report.
"""

import unittest

from core.chat_bridge import (
    OPERATION_CHAT,
    OPERATION_SCHEDULE,
    handle_bridge_request,
)
from tests.test_chat_adapter import CARD_KEYS, ENTRY_KEYS, empty_card
from tests.test_chat_planner import MONDAY, NOW, FakeClient, base_state, full_payload

CHAT_RESULT_KEYS = {"reply", "state", "fields", "ready", "provider"}


def chat_request(message, state=None, request_id="abc:1"):
    return {
        "requestId": request_id,
        "operation": OPERATION_CHAT,
        "payload": {"message": message, "state": state},
    }


def schedule_request(confirmed_fields, state=None, request_id="abc:2"):
    return {
        "requestId": request_id,
        "operation": OPERATION_SCHEDULE,
        "payload": {"state": state, "confirmed_fields": confirmed_fields},
    }


class ChatOperationTests(unittest.TestCase):
    def test_chat_returns_adapted_result_with_request_id(self):
        request = chat_request("下周我要完成物理作业和统计报告。", base_state())
        response = handle_bridge_request(request, client=FakeClient([full_payload()]))
        self.assertTrue(response["ok"], response.get("error"))
        self.assertEqual(response["requestId"], "abc:1")
        result = response["result"]
        self.assertEqual(set(result.keys()), CHAT_RESULT_KEYS)
        self.assertEqual(set(result["fields"].keys()), set(CARD_KEYS))
        self.assertEqual(result["provider"], "deepseek")
        self.assertTrue(result["ready"])
        self.assertFalse(result["reply"].startswith("Echo"),
                          "Echo Mock 不得冒充真实 AI 响应")

    def test_blank_message_gets_prompt_reply(self):
        response = handle_bridge_request(
            chat_request("   "), client=FakeClient([]))
        self.assertTrue(response["ok"], response.get("error"))
        self.assertTrue(response["result"]["reply"])

    def test_non_string_message_fails_cleanly(self):
        response = handle_bridge_request(
            chat_request(12345), client=FakeClient([]))
        self.assertFalse(response["ok"])
        self.assertEqual(response["requestId"], "abc:1")
        self.assertIn("message", response["error"])

    def test_bad_state_type_fails_cleanly(self):
        request = chat_request("hello", state="not-a-dict")
        response = handle_bridge_request(request, client=FakeClient([]))
        self.assertFalse(response["ok"])
        self.assertIn("state", response["error"])

    def test_fallback_provider_when_api_unavailable(self):
        # FakeClient with an empty queue raises AIError for every call,
        # which is exactly the "no API key" situation.
        request = chat_request("1-5", base_state())
        response = handle_bridge_request(request, client=FakeClient([]))
        self.assertTrue(response["ok"], response.get("error"))
        result = response["result"]
        self.assertEqual(result["provider"], "fallback")
        self.assertTrue(result["reply"])
        # The original raw message is preserved, not silently dropped.
        self.assertIn("1-5", result["state"]["unrecognized"][0])


class MultiRoundBridgeTests(unittest.TestCase):
    def test_state_round_trips_across_requests(self):
        round1 = {
            "add_or_update": {
                "tasks": [{"title": "物理作业", "estimated_minutes": 60}],
                "goals": ["完成物理作业"],
                "preferred_work_start": "08:00",
                "preferred_work_end": "21:00",
                "work_days": [0, 1, 2, 3, 4],
                "energy_peak": "morning",
                "fixed_commitments": [
                    {"title": "Team check-in", "day_of_week": 0,
                     "start": "11:00", "end": "11:30"}
                ],
                "rest_periods": [
                    {"title": "睡觉", "days": [0, 1, 2, 3, 4, 5, 6],
                     "start_time": "23:00", "end_time": "07:00"}
                ],
            },
            "remove": {}, "explicitly_none": [], "unknown": [],
            "ambiguous": None,
        }
        round2 = {
            "add_or_update": {
                "tasks": [{"title": "统计报告", "estimated_minutes": 120}],
                "predictable_routines": [
                    {"title": "运动", "weekdays": [0, 1, 2, 3, 4],
                     "estimated_minutes": 30,
                     "preferred_start": "18:00", "preferred_end": "19:00"}
                ],
            },
            "remove": {}, "explicitly_none": [], "unknown": [],
            "ambiguous": None,
        }
        client = FakeClient([round1, round2])
        first = handle_bridge_request(
            chat_request("有物理作业。", base_state(), "abc:1"), client=client)
        self.assertTrue(first["ok"], first.get("error"))
        # Optional goals/routines never block the confirmation step.
        self.assertTrue(first["result"]["ready"])

        second = handle_bridge_request(
            chat_request("还有统计报告，每天运动。", first["result"]["state"], "abc:2"),
            client=client,
        )
        self.assertTrue(second["ok"], second.get("error"))
        result = second["result"]
        self.assertTrue(result["ready"])
        self.assertEqual([t["title"] for t in result["fields"]["tasks"]],
                         ["物理作业", "统计报告"])


class ScheduleOperationTests(unittest.TestCase):
    def test_schedule_returns_entries_with_request_id(self):
        card = empty_card(
            goal="完成物理作业",
            tasks=[{"title": "物理作业", "details": "时长 60 分钟"}],
            commitments=[{
                "title": "Team check-in", "date": "2026-11-23",
                "startTime": "11:00", "endTime": "11:30",
            }],
        )
        response = handle_bridge_request(
            schedule_request(card, request_id="abc:2"), now=NOW)
        self.assertTrue(response["ok"], response.get("error"))
        self.assertEqual(response["requestId"], "abc:2")
        result = response["result"]
        self.assertEqual(set(result.keys()),
                         {"entries", "unscheduled", "warnings", "provider"})
        self.assertEqual(result["provider"], "python")
        self.assertTrue(result["entries"])
        for entry in result["entries"]:
            self.assertEqual(set(entry.keys()), set(ENTRY_KEYS))
        self.assertIn("Team check-in", [e["title"] for e in result["entries"]])

    def test_state_week_start_anchors_the_plan(self):
        card = empty_card(tasks=[{"title": "写代码", "details": "时长 60 分钟"}])
        response = handle_bridge_request(
            schedule_request(card, state={"week_start": "2026-11-30"},
                             request_id="abc:3"),
            now=NOW,
        )
        self.assertTrue(response["ok"], response.get("error"))
        dates = [e["date"] for e in response["result"]["entries"]]
        self.assertTrue(dates, "plan should not be empty")
        for day in dates:
            self.assertGreaterEqual(day, "2026-11-30")
            self.assertLess(day, "2026-12-07")

    def test_missing_confirmed_fields_fails_cleanly(self):
        response = handle_bridge_request({
            "requestId": "abc:4",
            "operation": OPERATION_SCHEDULE,
            "payload": {"state": None},
        })
        self.assertFalse(response["ok"])
        self.assertEqual(response["requestId"], "abc:4")
        self.assertIn("confirmed_fields", response["error"])

    def test_invalid_confirmed_fields_fails_cleanly(self):
        card = empty_card(commitments=[{
            "title": "坏数据", "date": "2026-11-23",
            "startTime": "11:00", "endTime": "10:00",
        }])
        response = handle_bridge_request(schedule_request(card), now=NOW)
        self.assertFalse(response["ok"])
        self.assertTrue(response["error"])


class ErrorEnvelopeTests(unittest.TestCase):
    def test_unknown_operation_fails_cleanly(self):
        response = handle_bridge_request({
            "requestId": "abc:9", "operation": "do_something_else",
            "payload": {},
        })
        self.assertFalse(response["ok"])
        self.assertEqual(response["requestId"], "abc:9")
        self.assertIn("operation", response["error"])

    def test_non_mapping_request_fails_cleanly(self):
        response = handle_bridge_request("not-json")
        self.assertFalse(response["ok"])
        self.assertIsNone(response["requestId"])
        self.assertTrue(response["error"])

    def test_request_id_preserved_on_error(self):
        response = handle_bridge_request(
            {"requestId": "abc:10", "operation": OPERATION_CHAT, "payload": {}})
        self.assertFalse(response["ok"])
        self.assertEqual(response["requestId"], "abc:10")


class RerunDedupeTests(unittest.TestCase):
    def test_needs_response_rule(self):
        from ui.chat_bridge import needs_response
        self.assertTrue(needs_response("r1", None, False))      # first arrival
        self.assertFalse(needs_response("r1", "r1", True))      # rerun replay
        self.assertTrue(needs_response("r2", "r1", True))       # new request


if __name__ == "__main__":
    unittest.main()
