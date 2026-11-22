import json
import unittest
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from unittest.mock import patch

from core.ai_client import AIConfigError, DeepSeekClient
from core.chat_bridge import OPERATION_CHAT, OPERATION_SCHEDULE, handle_bridge_request


FIXTURES = Path(__file__).with_name("fixtures")
WEEK_START = date(2026, 11, 23)
NOW = datetime(2026, 11, 22, 11, 40)
REQUIRED_TASKS = {
    "数学分析作业": (120, datetime(2026, 11, 26, 20)),
    "EAP 演讲 PPT": (90, datetime(2026, 11, 25, 12)),
    "物理实验报告": (180, datetime(2026, 11, 27, 18)),
}


class Phase3BWeekRegression(unittest.TestCase):
    def bridge(self, operation, payload):
        request = {"requestId": operation, "operation": operation, "payload": payload}
        response = handle_bridge_request(request, now=NOW)
        self.assertEqual(response["requestId"], operation)
        self.assertTrue(response["ok"], response.get("error"))
        return response["result"]

    def test_original_message_through_offline_handler_and_manually_confirmed_schedule(self):
        message = (FIXTURES / "phase3b-week-plan.zh.txt").read_text(encoding="utf-8").rstrip("\n")
        # Exercise the real handler and fallback without requiring API credentials.
        with patch.object(DeepSeekClient, "chat_json", side_effect=AIConfigError("offline")), patch(
            "core.chat_planner._next_monday", return_value=WEEK_START
        ):
            chat = self.bridge(OPERATION_CHAT, {"message": message, "state": None})
        self.assertEqual(chat["provider"], "fallback")
        self.assertEqual(chat["state"]["history"][0]["content"], message)

        # The existing fallback does not extract the full set of classes and tasks.
        # This fixture represents the same facts entered in the editable confirmation card.
        card = json.loads((FIXTURES / "phase3b-week-confirmed.zh.json").read_text(encoding="utf-8"))
        plan = self.bridge(OPERATION_SCHEDULE, {"state": chat["state"], "confirmed_fields": card})
        self.assertEqual(plan["provider"], "python")
        self.assertEqual(plan["unscheduled"], [])

        fixed = {
            (item["title"], item["date"], item["startTime"], item["endTime"])
            for item in card["commitments"]
        }
        returned_fixed = set()
        minutes = defaultdict(int)
        by_day = defaultdict(list)
        for item in plan["entries"]:
            title, day, start, end = (item[key] for key in ("title", "date", "startTime", "endTime"))
            self.assertIn((date.fromisoformat(day) - WEEK_START).days, range(5))
            self.assertTrue(end <= "12:00" or start >= "13:00", item)
            by_day[day].append((start, end))
            if title in REQUIRED_TASKS:
                start_at = datetime.fromisoformat(f"{day}T{start}")
                end_at = datetime.fromisoformat(f"{day}T{end}")
                minutes[title] += int((end_at - start_at).total_seconds() / 60)
                self.assertLessEqual(end_at, REQUIRED_TASKS[title][1])
                self.assertEqual(item["priority"], "High")
            else:
                returned_fixed.add((title, day, start, end))

        self.assertEqual(returned_fixed, fixed)
        self.assertEqual(dict(minutes), {title: duration for title, (duration, _) in REQUIRED_TASKS.items()})
        for blocks in by_day.values():
            ordered = sorted(blocks)
            for (_, previous_end), (start, _) in zip(ordered, ordered[1:]):
                self.assertLessEqual(previous_end, start)
