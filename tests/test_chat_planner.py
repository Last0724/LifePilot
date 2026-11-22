"""Offline tests for the Phase 2 chat processing layer (core.chat_planner).

Every test drives ``handle_chat_message`` / ``build_confirmed_schedule`` with a
deterministic FakeClient, so no network, no API key and no Streamlit are
needed. Real DeepSeek API behaviour is reported separately.
"""

import unittest
from datetime import date, datetime

from core.ai_client import AIError
from core.chat_planner import (
    DEFAULT_TASK_MINUTES,
    _default_state,
    build_confirmed_schedule,
    handle_chat_message,
)

MONDAY = date(2026, 11, 23)  # Monday of the demo week
NOW = datetime(2026, 11, 23, 8, 0)


class FakeClient:
    """Deterministic stand-in for DeepSeekClient.

    Extraction prompts (the only LLM call chat_planner itself makes) pop one
    canned response from the queue. Every other call — question phrasing in
    the consultation layer — raises AIError, exactly like an unavailable API
    (the controller then phrases questions deterministically).
    """

    def __init__(self, responses=None):
        self.responses = list(responses or [])
        self.calls = []

    def chat_json(self, messages, **kwargs):
        self.calls.append(messages)
        user_text = "\n".join(
            str(item.get("content", ""))
            for item in messages
            if item.get("role") == "user"
        )
        if "Extract scheduling facts" in user_text:
            if self.responses:
                return self.responses.pop(0)
        raise AIError("offline fake client")


def base_state():
    return _default_state(MONDAY)


def required_only_payload():
    """Resolve the four required scheduling fields, leave goals/routines open."""
    return {
        "add_or_update": {
            "tasks": [{"title": "数学作业", "estimated_minutes": 60}],
            "fixed_commitments": [
                {"title": "物理实验", "day_of_week": 2,
                 "start": "14:00", "end": "16:00"}
            ],
            "rest_periods": [
                {"title": "睡觉", "days": [0, 1, 2, 3, 4, 5, 6],
                 "start_time": "23:00", "end_time": "07:00"}
            ],
            "preferred_work_start": "09:00",
            "preferred_work_end": "18:00",
        },
        "remove": {},
        "explicitly_none": [],
        "unknown": [],
        "ambiguous": None,
    }


def chat(text, state=None, client=None):
    return handle_chat_message(text, state, client=client)


def full_payload():
    """One LLM answer that resolves every REQUIRED_FIELD in a single message."""
    return {
        "add_or_update": {
            "tasks": [
                {"title": "物理作业", "estimated_minutes": 60},
                {"title": "统计报告", "estimated_minutes": 120},
            ],
            "fixed_commitments": [
                {"title": "Team check-in", "day_of_week": 0,
                 "start": "11:00", "end": "11:30"}
            ],
            "rest_periods": [
                {"title": "睡觉", "days": [0, 1, 2, 3, 4, 5, 6],
                 "start_time": "23:00", "end_time": "07:00"}
            ],
            "predictable_routines": [
                {"title": "运动", "weekdays": [0, 1, 2, 3, 4],
                 "estimated_minutes": 30,
                 "preferred_start": "18:00", "preferred_end": "19:00"}
            ],
            "goals": ["完成物理作业"],
            "preferred_work_start": "08:00",
            "preferred_work_end": "21:00",
            "work_days": [0, 1, 2, 3, 4],
            "energy_peak": "morning",
        },
        "remove": {},
        "explicitly_none": [],
        "unknown": [],
        "ambiguous": None,
    }


def schedule_minutes(item):
    start_h, start_m = (int(p) for p in item["start"].split(":"))
    end_h, end_m = (int(p) for p in item["end"].split(":"))
    return (end_h * 60 + end_m) - (start_h * 60 + start_m)


class WholeParagraphTests(unittest.TestCase):
    def test_full_paragraph_extracts_tasks_fixed_days_and_preferences(self):
        client = FakeClient(
            [
                {
                    "add_or_update": {
                        "tasks": [
                            {"title": "物理作业", "priority": "high",
                             "deadline": "2026-11-27"},
                            {"title": "统计报告", "estimated_minutes": 120},
                        ],
                        "fixed_commitments": [
                            {"title": "课", "day_of_week": 0,
                             "start": "09:00", "end": "12:00"},
                            {"title": "实验", "day_of_week": 2,
                             "start": "14:00", "end": "17:00"},
                        ],
                        "rest_periods": [
                            {"title": "睡觉", "days": [0, 1, 2, 3, 4, 5, 6],
                             "start_time": "23:00", "end_time": "07:00"}
                        ],
                        "work_days": [0, 1, 2, 3, 4],
                        "energy_peak": "morning",
                    },
                    "remove": {},
                    "explicitly_none": [],
                    "unknown": [],
                    "ambiguous": None,
                }
            ]
        )
        res = chat(
            "下周我要完成物理作业和统计报告，周一到周五有课，周三下午有实验。"
            "我一般早上效率比较高，希望每天睡八小时。",
            state=base_state(),
            client=client,
        )
        facts = res["state"]["facts"]
        self.assertEqual(len(facts["tasks"]), 2)
        self.assertEqual(facts["tasks"][0]["priority"], "high")
        self.assertEqual(facts["work_days"], [0, 1, 2, 3, 4])
        self.assertEqual(facts["energy_peak"], "morning")
        self.assertEqual(len(facts["fixed_commitments"]), 2)
        self.assertEqual(len(facts["rest_periods"]), 1)
        # Still missing: the required work hours. Routines and goals are
        # optional context and must not block confirmation.
        self.assertFalse(res["ready_for_confirmation"])
        self.assertEqual(
            res["missing_fields"],
            ["preferred_work_start", "preferred_work_end"],
        )
        self.assertNotIn("goals", res["missing_fields"])
        self.assertNotIn("predictable_routines", res["missing_fields"])


class MultiRoundTests(unittest.TestCase):
    def test_three_rounds_accumulate_without_loss(self):
        client = FakeClient(
            [
                {"add_or_update": {
                    "tasks": [{"title": "物理作业"}, {"title": "统计报告"}]},
                 "remove": {}, "explicitly_none": [], "unknown": [],
                 "ambiguous": None},
                {"add_or_update": {
                    "fixed_commitments": [
                        {"title": "课", "day_of_week": 1,
                         "start": "09:00", "end": "12:00"}],
                    "work_days": [0, 1, 2, 3, 4]},
                 "remove": {}, "explicitly_none": [], "unknown": [],
                 "ambiguous": None},
                {"add_or_update": {
                    "rest_periods": [
                        {"title": "睡觉", "days": [0, 1, 2, 3, 4, 5, 6],
                         "start_time": "23:00", "end_time": "07:00"}],
                    "predictable_routines": [
                        {"title": "运动", "weekdays": [0, 1, 2, 3, 4],
                         "estimated_minutes": 30}],
                    "energy_peak": "morning",
                    "preferred_work_start": "08:00",
                    "preferred_work_end": "21:00",
                    "goals": ["完成物理作业"]},
                 "remove": {}, "explicitly_none": [], "unknown": [],
                 "ambiguous": None},
            ]
        )
        state = base_state()
        state = chat("我先说任务：物理作业和统计报告。", state, client)["state"]
        state = chat("周一有课，周一到周五工作。", state, client)["state"]
        res = chat("我每天睡八小时，另外每天运动半小时，早上效率高，"
                   "目标是完成物理作业。", state, client)
        facts = res["state"]["facts"]
        self.assertEqual(len(facts["tasks"]), 2)
        self.assertEqual(len(facts["fixed_commitments"]), 1)
        self.assertEqual(len(facts["rest_periods"]), 1)
        self.assertEqual(len(facts["predictable_routines"]), 1)
        self.assertEqual(facts["goals"], ["完成物理作业"])
        self.assertEqual(facts["energy_peak"], "morning")
        self.assertTrue(res["ready_for_confirmation"])
        self.assertEqual(res["missing_fields"], [])


class CorrectionTests(unittest.TestCase):
    def test_update_by_stable_id_replaces_value(self):
        client = FakeClient(
            [
                {"add_or_update": {
                    "tasks": [{"title": "物理作业", "estimated_minutes": 60}]},
                 "remove": {}, "explicitly_none": [], "unknown": [],
                 "ambiguous": None},
                {"add_or_update": {
                    "tasks": [{"id": "task_1", "operation": "update",
                               "title": "物理作业",
                               "estimated_minutes": 90}]},
                 "remove": {}, "explicitly_none": [], "unknown": [],
                 "ambiguous": None},
            ]
        )
        state = base_state()
        state = chat("物理作业一小时。", state, client)["state"]
        res = chat("物理作业改成九十分钟。", state, client)
        tasks = res["state"]["facts"]["tasks"]
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]["estimated_minutes"], 90)

    def test_update_without_id_matches_unique_title(self):
        client = FakeClient(
            [
                {"add_or_update": {
                    "tasks": [{"title": "物理作业", "estimated_minutes": 60}]},
                 "remove": {}, "explicitly_none": [], "unknown": [],
                 "ambiguous": None},
                {"add_or_update": {
                    "tasks": [{"operation": "update", "title": "物理作业",
                               "estimated_minutes": 45}]},
                 "remove": {}, "explicitly_none": [], "unknown": [],
                 "ambiguous": None},
            ]
        )
        state = base_state()
        state = chat("物理作业一小时。", state, client)["state"]
        res = chat("物理作业只要四十五分钟。", state, client)
        tasks = res["state"]["facts"]["tasks"]
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]["estimated_minutes"], 45)


class WeekdayTests(unittest.TestCase):
    def test_chinese_range_weekdays(self):
        client = FakeClient(
            [{"add_or_update": {"work_days": [0, 1, 2, 3, 4]},
              "remove": {}, "explicitly_none": [], "unknown": [],
              "ambiguous": None}]
        )
        res = chat("工作日是周一至周五。", base_state(), client)
        self.assertEqual(res["state"]["facts"]["work_days"], [0, 1, 2, 3, 4])

    def test_english_range_weekdays(self):
        client = FakeClient(
            [{"add_or_update": {"work_days": [0, 1, 2, 3, 4]},
              "remove": {}, "explicitly_none": [], "unknown": [],
              "ambiguous": None}]
        )
        res = chat("I work Monday to Friday.", base_state(), client)
        self.assertEqual(res["state"]["facts"]["work_days"], [0, 1, 2, 3, 4])

    def test_fallback_parser_expands_weekday_range(self):
        # No LLM: the deterministic fallback must handle "1-5" itself.
        res = chat("工作日在1-5。", base_state(), FakeClient([]))
        self.assertEqual(res["provider"], "fallback")
        self.assertIn("1-5", res["state"]["unrecognized"][0])
        self.assertEqual(res["state"]["facts"]["work_days"], [0, 1, 2, 3, 4])


class SchedulingTests(unittest.TestCase):
    def test_task_without_deadline_is_scheduled(self):
        client = FakeClient([full_payload()])
        res = chat("下周我有物理作业和统计报告，周一到周五有课……", base_state(), client)
        state = res["state"]
        self.assertTrue(res["ready_for_confirmation"])
        plan = build_confirmed_schedule(state, now=NOW)
        self.assertTrue(plan["schedule"])
        titles = {item["title"] for item in plan["schedule"]}
        self.assertIn("物理作业", titles)
        self.assertIn("统计报告", titles)

    def test_schedule_reflects_inputs_and_protects_fixed_and_rest(self):
        client = FakeClient([full_payload()])
        res = chat("下周我有物理作业和统计报告……", base_state(), client)
        plan = build_confirmed_schedule(res["state"], now=NOW)
        fixed = [i for i in plan["schedule"] if i["is_fixed"]]
        self.assertEqual(len(fixed), 1)
        self.assertEqual(fixed[0]["title"], "Team check-in")
        self.assertEqual(fixed[0]["date"], "2026-11-23")
        self.assertEqual(fixed[0]["start"], "11:00")
        self.assertEqual(fixed[0]["end"], "11:30")
        for item in plan["schedule"]:
            if item["is_fixed"]:
                continue
            # Nothing may run inside the 23:00-07:00 rest window.
            end_h = int(item["end"].split(":")[0])
            start_h = int(item["start"].split(":")[0])
            self.assertFalse(end_h > 23 or end_h <= 7)
            self.assertGreaterEqual(start_h, 8)
            self.assertLessEqual(end_h, 21)

    def test_uncertain_task_gets_default_45_minutes_and_buffer(self):
        client = FakeClient(
            [
                {
                    "add_or_update": {
                        "tasks": [{"title": "写周报"}],
                        "work_days": [0, 1, 2, 3, 4],
                        "energy_peak": "morning",
                        "goals": ["完成周报"],
                        "preferred_work_start": "09:00",
                        "preferred_work_end": "18:00",
                    },
                    "remove": {},
                    "explicitly_none": ["fixed_commitments", "rest_periods",
                                       "predictable_routines"],
                    "unknown": [],
                    "ambiguous": None,
                }
            ]
        )
        res = chat("我写个周报，没别的事。", base_state(), client)
        self.assertTrue(res["ready_for_confirmation"])
        task = res["state"]["facts"]["tasks"][0]
        self.assertIsNone(task.get("estimated_minutes"))
        plan = build_confirmed_schedule(res["state"], now=NOW)
        item = next(i for i in plan["schedule"] if i["title"] == "写周报")
        # 45 minutes UNCERTAIN -> 20% buffer -> 54 planned minutes.
        self.assertEqual(schedule_minutes(item), 54)


class IdentityAndRemovalTests(unittest.TestCase):
    def test_same_title_different_tasks_are_not_overwritten(self):
        client = FakeClient(
            [
                {"add_or_update": {"tasks": [{"title": "作业"}]},
                 "remove": {}, "explicitly_none": [], "unknown": [],
                 "ambiguous": None},
                {"add_or_update": {"tasks": [{"title": "作业"}]},
                 "remove": {}, "explicitly_none": [], "unknown": [],
                 "ambiguous": None},
            ]
        )
        state = base_state()
        state = chat("有数学作业。", state, client)["state"]
        res = chat("还有一个物理作业，也叫作业。", state, client)
        tasks = res["state"]["facts"]["tasks"]
        self.assertEqual(len(tasks), 2)
        ids = {t["chat_id"] for t in tasks}
        self.assertEqual(len(ids), 2)

    def test_explicit_cancel_removes_task(self):
        client = FakeClient(
            [
                {"add_or_update": {"tasks": [{"title": "物理作业"}]},
                 "remove": {}, "explicitly_none": [], "unknown": [],
                 "ambiguous": None},
                {"add_or_update": {},
                 "remove": {"tasks": ["task_1"]},
                 "explicitly_none": [], "unknown": [], "ambiguous": None},
            ]
        )
        state = base_state()
        state = chat("要做物理作业。", state, client)["state"]
        res = chat("物理作业不用做了。", state, client)
        self.assertEqual(res["state"]["facts"]["tasks"], [])

    def test_ambiguous_removal_asks_instead_of_guessing(self):
        client = FakeClient(
            [
                {"add_or_update": {
                    "tasks": [{"title": "作业"}, {"title": "作业"}]},
                 "remove": {}, "explicitly_none": [], "unknown": [],
                 "ambiguous": None},
                {"add_or_update": {},
                 "remove": {"tasks": ["作业"]},
                 "explicitly_none": [], "unknown": [], "ambiguous": None},
            ]
        )
        state = base_state()
        state = chat("数学和物理作业。", state, client)["state"]
        res = chat("作业取消一个。", state, client)
        self.assertEqual(len(res["state"]["facts"]["tasks"]), 2)
        self.assertIn("哪一个", res["reply"])


class FieldStateTests(unittest.TestCase):
    def test_explicitly_none_never_reasked(self):
        client = FakeClient(
            [
                {"add_or_update": {"tasks": [{"title": "写周报"}]},
                 "remove": {},
                 "explicitly_none": ["fixed_commitments", "rest_periods"],
                 "unknown": [], "ambiguous": None},
                {"add_or_update": {"work_days": [0, 1, 2, 3, 4]},
                 "remove": {}, "explicitly_none": [], "unknown": [],
                 "ambiguous": None},
            ]
        )
        state = base_state()
        state = chat("我没有固定安排，晚上也不休息。", state, client)["state"]
        field_states = state["field_states"]
        self.assertIn("fixed_commitments", field_states["resolved"])
        self.assertIn("rest_periods", field_states["resolved"])
        res = chat("工作日是一到五。", state, client)
        self.assertNotIn("fixed_commitments", res["missing_fields"])
        self.assertNotIn("rest_periods", res["missing_fields"])

    def test_unknown_answer_never_reasked_or_resolved(self):
        client = FakeClient(
            [
                {"add_or_update": {"tasks": [{"title": "写周报"}]},
                 "remove": {},
                 "explicitly_none": ["fixed_commitments", "rest_periods",
                                     "predictable_routines"],
                 "unknown": ["energy_peak"], "ambiguous": None},
            ]
        )
        res = chat("不知道什么时候效率高。", base_state(), client)
        field_states = res["state"]["field_states"]
        self.assertIn("energy_peak", field_states["unknown"])
        self.assertNotIn("energy_peak", field_states["resolved"])
        self.assertNotIn("energy_peak", res["missing_fields"])


class FallbackSafetyTests(unittest.TestCase):
    def test_api_failure_keeps_raw_message(self):
        res = chat("完全无关的聊天内容 abcxyz。", base_state(), FakeClient([]))
        self.assertEqual(res["provider"], "fallback")
        self.assertEqual(res["state"]["unrecognized"],
                         ["完全无关的聊天内容 abcxyz。"])
        self.assertEqual(res["state"]["provider_history"], ["fallback"])

    def test_rerun_of_same_message_does_not_merge_twice(self):
        client = FakeClient(
            [{"add_or_update": {"tasks": [{"title": "物理作业"}]},
              "remove": {}, "explicitly_none": [], "unknown": [],
              "ambiguous": None}]
        )
        state = base_state()
        first = chat("要做物理作业。", state, client)
        second = chat("要做物理作业。", first["state"], FakeClient([]))
        self.assertEqual(second["reply"], first["reply"])
        self.assertEqual(len(second["state"]["facts"]["tasks"]), 1)
        self.assertEqual(
            len([h for h in second["state"]["history"]
                 if h["role"] == "user"]),
            1,
        )

    def test_modified_confirmed_field_changes_final_schedule(self):
        client = FakeClient(
            [
                full_payload(),
                {"add_or_update": {
                    "tasks": [{"id": "task_1", "operation": "update",
                               "title": "物理作业",
                               "estimated_minutes": 240}]},
                 "remove": {}, "explicitly_none": [], "unknown": [],
                 "ambiguous": None},
            ]
        )
        state = base_state()
        state = chat("下周我有物理作业和统计报告……", state, client)["state"]
        first = build_confirmed_schedule(state, now=NOW)
        first_item = next(i for i in first["schedule"]
                          if i["title"] == "物理作业")
        self.assertEqual(schedule_minutes(first_item), 72)  # 60 * 1.2

        state = chat("物理作业其实要四个小时。", state, client)["state"]
        second = build_confirmed_schedule(state, now=NOW)
        second_item = next(i for i in second["schedule"]
                           if i["title"] == "物理作业")
        self.assertEqual(schedule_minutes(second_item), 288)  # 240 * 1.2


class WorkDaysSupplementTests(unittest.TestCase):
    """Deterministic work-day parsing that backs up the LLM extraction."""

    def turn(self, text, state=None):
        return chat(text, state=state, client=FakeClient([{"add_or_update": {}}]))

    def assert_work_days(self, result, expected):
        state = result["state"]
        self.assertEqual(state["facts"].get("work_days"), expected)
        self.assertIn("work_days", state["field_states"]["resolved"])
        self.assertNotIn("work_days", state["field_states"]["unresolved"])
        self.assertNotIn("work_days", state["field_states"]["unknown"])
        self.assertEqual(result["extracted_fields"].get("work_days"), expected)

    def assert_no_work_days(self, result):
        state = result["state"]
        self.assertNotIn("work_days", state["facts"])
        self.assertNotIn("work_days", state["field_states"]["resolved"])

    def test_chinese_work_range(self):
        self.assert_work_days(self.turn("周一到周五工作，周末休息"), [0, 1, 2, 3, 4])

    def test_english_work_range(self):
        self.assert_work_days(self.turn("Monday to Friday working"), [0, 1, 2, 3, 4])

    def test_bare_english_range(self):
        self.assert_work_days(self.turn("Mon-Fri"), [0, 1, 2, 3, 4])

    def test_bare_numeric_range(self):
        self.assert_work_days(self.turn("1-5"), [0, 1, 2, 3, 4])

    def test_class_days_count_as_work_context(self):
        self.assert_work_days(self.turn("周一到周五有课"), [0, 1, 2, 3, 4])

    def test_activity_days_are_not_work_days(self):
        self.assert_no_work_days(self.turn("周一、周三跑步"))

    def test_clock_times_are_not_work_days(self):
        self.assert_no_work_days(self.turn("11:00-12:30 开会"))

    def test_latest_explicit_statement_wins(self):
        first = self.turn("周一到周五工作")
        second = self.turn("周六周日工作", state=first["state"])
        self.assertEqual(second["state"]["facts"]["work_days"], [5, 6])
        self.assertEqual(second["extracted_fields"].get("work_days"), [5, 6])

    def test_llm_work_days_kept_without_explicit_range(self):
        client = FakeClient([{"add_or_update": {"work_days": [0, 1, 2]}}])
        result = chat("我早上效率比较高", client=client)
        self.assertEqual(result["state"]["facts"]["work_days"], [0, 1, 2])

    def test_fallback_path_still_extracts_work_days(self):
        result = chat("周一到周五工作", client=FakeClient([]))
        self.assertEqual(result["provider"], "fallback")
        self.assertEqual(result["state"]["facts"]["work_days"], [0, 1, 2, 3, 4])


class OptionalGoalFlowTests(unittest.TestCase):
    """A long-term goal is useful context, never a blocker for scheduling."""

    def ready_turn(self):
        return chat(
            "下周完成数学作业，周三 14:00-16:00 有物理实验，"
            "23:00 睡觉，09:00-18:00 工作。",
            state=base_state(),
            client=FakeClient([required_only_payload()]),
        )

    def test_ready_without_goal_and_goal_is_asked_once(self):
        res = self.ready_turn()
        self.assertTrue(res["ready_for_confirmation"])
        self.assertEqual(res["missing_fields"], [])
        self.assertNotIn("goals", res["state"]["field_states"]["resolved"])
        self.assertIn("长期坚持的目标", res["reply"])
        self.assertEqual(res["state"]["optional_asked"], ["goals"])

    def test_goal_answer_is_recorded_and_not_repeated(self):
        first = self.ready_turn()
        second = chat("健身", state=first["state"], client=FakeClient([{}]))
        self.assertTrue(second["ready_for_confirmation"])
        self.assertEqual(second["state"]["facts"]["goals"], ["健身"])
        self.assertIn("goals", second["state"]["field_states"]["resolved"])
        self.assertNotIn("goals", second["state"]["field_states"]["unresolved"])
        self.assertNotIn("长期坚持的目标", second["reply"])

    def test_explicit_no_goal_is_accepted(self):
        first = self.ready_turn()
        second = chat("没有了", state=first["state"], client=FakeClient([{}]))
        self.assertTrue(second["ready_for_confirmation"])
        self.assertEqual(second["state"]["facts"]["goals"], [])
        self.assertIn("goals", second["state"]["field_states"]["resolved"])
        self.assertNotIn("goals", second["state"]["field_states"]["unresolved"])
        self.assertNotIn("长期坚持的目标", second["reply"])

    def test_unknown_goal_is_not_reasked(self):
        first = self.ready_turn()
        second = chat("不知道", state=first["state"], client=FakeClient([{}]))
        self.assertTrue(second["ready_for_confirmation"])
        self.assertIn("goals", second["state"]["field_states"]["unknown"])
        self.assertNotIn("goals", second["state"]["field_states"]["unresolved"])
        self.assertNotIn("长期坚持的目标", second["reply"])

    def test_generate_request_is_not_blocked(self):
        first = self.ready_turn()
        second = chat(
            "完成了，请生成日程", state=first["state"], client=FakeClient([{}])
        )
        self.assertTrue(second["ready_for_confirmation"])
        self.assertEqual(second["missing_fields"], [])
        self.assertEqual(second["state"]["facts"]["goals"], [])
        self.assertIn("信息已经齐了", second["reply"])
        self.assertNotIn("长期坚持的目标", second["reply"])

    def test_required_facts_survive_goal_turns(self):
        first = self.ready_turn()
        second = chat("健身", state=first["state"], client=FakeClient([{}]))
        facts = second["state"]["facts"]
        self.assertEqual([item["title"] for item in facts["tasks"]], ["数学作业"])
        self.assertEqual([item["title"] for item in facts["fixed_commitments"]],
                         ["物理实验"])
        self.assertEqual(len(facts["rest_periods"]), 1)
        self.assertEqual(facts["preferred_work_start"], "09:00")
        self.assertEqual(facts["preferred_work_end"], "18:00")

    def test_confirmation_uses_real_scheduler(self):
        first = self.ready_turn()
        plan = build_confirmed_schedule(first["state"], now=NOW)
        titles = [entry["title"] for entry in plan["schedule"]]
        self.assertIn("数学作业", titles)
        self.assertIn("物理实验", titles)
        self.assertEqual(plan["unscheduled"], [])
        self.assertEqual(plan["warnings"], [])


if __name__ == "__main__":
    unittest.main()
