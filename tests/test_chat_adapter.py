"""Offline tests for the Phase 3A chat adapter (core.chat_adapter).

Covers the ten scenarios required by the Technical Lead:
  1. complete fields snapshot      2. multi-round accumulation
  3. confirmed card overrides old facts  4. fixed commitments in calendar
  5. overnight sleep               6. weekly repeating tasks
  7. priority/category defaults    8. unschedulable task + reason
  9. invalid times / illegal data  10. full-flow FakeClient offline
"""

import unittest
from datetime import date, datetime

from core.chat_adapter import (
    CATEGORIES,
    adapt_chat,
    adapt_schedule,
    confirmed_fields_to_questionnaire,
    plan_from_confirmed,
    task_meta_from_facts,
)
from core.chat_planner import build_confirmed_schedule
from tests.test_chat_planner import MONDAY, NOW, FakeClient, base_state, chat, full_payload

CARD_KEYS = (
    "goal", "tasks", "commitments", "wake", "bed", "rest",
    "workStart", "workEnd", "routine",
)
ENTRY_KEYS = ("title", "date", "startTime", "endTime", "category",
              "priority", "repeatWeekly")


def minutes(item):
    start_h, start_m = (int(p) for p in item["startTime"].split(":"))
    end_h, end_m = (int(p) for p in item["endTime"].split(":"))
    return (end_h * 60 + end_m) - (start_h * 60 + start_m)


def overlaps(item, start="23:00", end="07:00"):
    s_h, s_m = (int(p) for p in item["startTime"].split(":"))
    e_h, e_m = (int(p) for p in item["endTime"].split(":"))
    s, e = s_h * 60 + s_m, e_h * 60 + e_m
    if s >= 23 * 60 or s < 7 * 60 or e > 23 * 60:
        return True
    return False


def empty_card(**overrides):
    card = {
        "goal": "",
        "tasks": [],
        "commitments": [],
        "wake": None,
        "bed": None,
        "rest": "",
        "workStart": "09:00",
        "workEnd": "17:00",
        "routine": "",
    }
    card.update(overrides)
    return card


class FieldsSnapshotTests(unittest.TestCase):
    def test_full_fields_snapshot_when_ready(self):
        client = FakeClient([full_payload()])
        result = chat("下周我要完成物理作业和统计报告。", base_state(), client=client)
        adapted = adapt_chat(result)
        self.assertTrue(adapted["ready"])
        self.assertEqual(set(adapted["fields"].keys()), set(CARD_KEYS))
        self.assertEqual(adapted["provider"], "deepseek")
        # Snapshot is the FULL accumulated facts, not this round's extraction.
        self.assertEqual([t["title"] for t in adapted["fields"]["tasks"]],
                         ["物理作业", "统计报告"])
        self.assertEqual(adapted["fields"]["goal"], "完成物理作业")
        self.assertEqual(adapted["fields"]["workStart"], "08:00")
        self.assertEqual(adapted["fields"]["workEnd"], "21:00")
        # Sleep is exposed as wake/bed, not inside rest.
        self.assertEqual(adapted["fields"]["bed"], "23:00")
        self.assertEqual(adapted["fields"]["wake"], "07:00")
        self.assertNotIn("睡觉", adapted["fields"]["rest"])
        # Commitments carry B's date/startTime/endTime keys.
        commitment = adapted["fields"]["commitments"][0]
        self.assertEqual(commitment["title"], "Team check-in")
        self.assertEqual(commitment["date"], "2026-11-23")
        self.assertEqual(commitment["startTime"], "11:00")
        self.assertEqual(commitment["endTime"], "11:30")


class MultiRoundTests(unittest.TestCase):
    def test_multi_round_accumulation_reflected_in_fields(self):
        round1 = {
            "add_or_update": {
                "tasks": [{"title": "物理作业", "estimated_minutes": 60}],
                "fixed_commitments": [
                    {"title": "Team check-in", "day_of_week": 0,
                     "start": "11:00", "end": "11:30"}
                ],
                "rest_periods": [
                    {"title": "睡觉", "days": [0, 1, 2, 3, 4, 5, 6],
                     "start_time": "23:00", "end_time": "07:00"}
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
        round2 = {
            "add_or_update": {
                "tasks": [{"title": "统计报告", "estimated_minutes": 120}],
                "predictable_routines": [
                    {"title": "运动", "weekdays": [0, 1, 2, 3, 4],
                     "estimated_minutes": 30,
                     "preferred_start": "18:00", "preferred_end": "19:00"}
                ],
            },
            "remove": {},
            "explicitly_none": [],
            "unknown": [],
            "ambiguous": None,
        }
        client = FakeClient([round1, round2])
        state = base_state()
        first = chat("有物理作业。", state, client=client)
        # Goals and routines are optional context: they never block readiness.
        self.assertTrue(first["ready_for_confirmation"])
        state = first["state"]
        second = chat("还有统计报告，每天运动30分钟。", state, client=client)
        adapted = adapt_chat(second)
        self.assertTrue(adapted["ready"])
        self.assertEqual([t["title"] for t in adapted["fields"]["tasks"]],
                         ["物理作业", "统计报告"])
        self.assertIn("运动", adapted["fields"]["routine"])
        plan = plan_from_confirmed(adapted["fields"], week_start=MONDAY, now=NOW)
        routines = [entry for entry in plan["entries"] if entry["repeatWeekly"]]
        self.assertEqual(len(routines), 5)
        self.assertEqual({entry["title"] for entry in routines}, {"运动"})
        self.assertTrue(all("18:00" <= entry["startTime"] < entry["endTime"] <= "19:00" for entry in routines))


class ConfirmedOverrideTests(unittest.TestCase):
    def test_confirmed_fields_override_old_facts(self):
        # Old chat facts say 60 minutes; the user edits the card to 90.
        client = FakeClient([full_payload()])
        old_state = chat("下周我有物理作业。", base_state(), client=client)["state"]
        self.assertIsNotNone(old_state["facts"]["tasks"])

        plan = plan_from_confirmed(
            empty_card(
                goal="完成物理作业",
                tasks=[{"title": "物理作业", "details": "时长 90 分钟"}],
            ),
            week_start=MONDAY,
            now=NOW,
        )
        entry = next(e for e in plan["entries"] if e["title"] == "物理作业")
        self.assertEqual(minutes(entry), 90)
        # Card has no fixed commitment even though old facts had one.
        self.assertNotIn("Team check-in",
                         [e["title"] for e in plan["entries"]])


class FixedCommitmentTests(unittest.TestCase):
    def test_fixed_commitments_enter_calendar(self):
        plan = plan_from_confirmed(
            empty_card(
                commitments=[{
                    "title": "Team check-in", "date": "2026-11-23",
                    "startTime": "11:00", "endTime": "11:30",
                }],
                tasks=[{"title": "写代码", "details": "时长 60 分钟"}],
            ),
            week_start=MONDAY,
            now=NOW,
        )
        for entry in plan["entries"]:
            self.assertEqual(set(entry.keys()), set(ENTRY_KEYS))
        commitment = next(e for e in plan["entries"]
                          if e["title"] == "Team check-in")
        self.assertEqual(commitment["date"], "2026-11-23")
        self.assertEqual(commitment["startTime"], "11:00")
        self.assertEqual(commitment["endTime"], "11:30")
        self.assertEqual(commitment["category"], "Other")
        # No task overlaps the commitment slot.
        for entry in plan["entries"]:
            if entry["title"] == "Team check-in":
                continue
            self.assertFalse(
                entry["startTime"] < "11:30" and entry["endTime"] > "11:00",
                f"{entry['title']} overlaps the fixed commitment",
            )


class SleepTests(unittest.TestCase):
    def test_overnight_sleep_blocks_both_sides_of_midnight(self):
        plan = plan_from_confirmed(
            empty_card(
                wake="07:00", bed="23:00",
                workStart="00:00", workEnd="23:59",
                tasks=[{"title": "写代码", "details": "时长 60 分钟"}],
            ),
            week_start=MONDAY,
            now=NOW,
        )
        task = next(e for e in plan["entries"] if e["title"] == "写代码")
        # Sleep runs 23:00-07:00; the earliest free slot is 07:00.
        self.assertGreaterEqual(task["startTime"], "07:00")
        for entry in plan["entries"]:
            self.assertFalse(overlaps(entry),
                             f"{entry['title']} invades sleep time")


class RepeatTests(unittest.TestCase):
    def test_weekly_repeat_task_and_routine_flags(self):
        plan = plan_from_confirmed(
            empty_card(
                tasks=[
                    {"title": "周会", "details": "每周重复，时长 30 分钟"},
                    {"title": "写代码", "details": "时长 60 分钟"},
                ],
                routine="运动 30 分钟",
            ),
            week_start=MONDAY,
            now=NOW,
        )
        meeting = next(e for e in plan["entries"] if e["title"] == "周会")
        coding = next(e for e in plan["entries"] if e["title"] == "写代码")
        routines = [e for e in plan["entries"] if e["title"] == "运动"]
        self.assertIs(meeting["repeatWeekly"], True)
        self.assertIs(coding["repeatWeekly"], False)
        self.assertTrue(routines, "routine entries should be in the calendar")
        for entry in routines:
            self.assertIs(entry["repeatWeekly"], True)


class DefaultsTests(unittest.TestCase):
    def test_priority_category_defaults_and_explicit_values(self):
        plan = plan_from_confirmed(
            empty_card(
                tasks=[
                    {"title": "普通任务", "details": ""},
                    {"title": "重要作业", "details": "优先级 High，类别 学习，时长 30 分钟"},
                    {"title": "健身", "details": "时长 40 分钟，类别 锻炼"},
                ],
            ),
            week_start=MONDAY,
            now=NOW,
        )
        entries = {e["title"]: e for e in plan["entries"]}
        plain = entries["普通任务"]
        self.assertEqual(plain["priority"], "Medium")   # system default
        self.assertEqual(plain["category"], "Other")    # no reliable category
        important = entries["重要作业"]
        self.assertEqual(important["priority"], "High")
        self.assertEqual(important["category"], "Study")
        gym = entries["健身"]
        self.assertEqual(gym["category"], "Exercise")
        for entry in plan["entries"]:
            self.assertIn(entry["category"], CATEGORIES)
            self.assertIn(entry["priority"], ("High", "Medium", "Low"))
            self.assertIsInstance(entry["repeatWeekly"], bool)


class UnscheduledTests(unittest.TestCase):
    def test_unschedulable_task_reports_reason(self):
        # The card has no work_days key, so the questionnaire defaults to all
        # seven days — block every one of them with a full-day commitment.
        commitments = [
            {"title": f"整天会议{d}", "date": f"2026-11-{23 + d}",
             "startTime": "09:00", "endTime": "17:00"}
            for d in range(7)
        ]
        plan = plan_from_confirmed(
            empty_card(
                commitments=commitments,
                tasks=[{"title": "大作业", "details": "时长 480 分钟"}],
            ),
            week_start=MONDAY,
            now=NOW,
        )
        self.assertNotIn("大作业", [e["title"] for e in plan["entries"]])
        self.assertTrue(plan["unscheduled"],
                        "the 480-minute task cannot fit and must be reported")
        unscheduled = plan["unscheduled"][0]
        self.assertEqual(unscheduled["title"], "大作业")
        self.assertTrue(unscheduled["reason"],
                        "unscheduled reason must not be empty")


class InvalidDataTests(unittest.TestCase):
    def test_invalid_commitment_time_raises(self):
        with self.assertRaises(ValueError):
            plan_from_confirmed(empty_card(
                commitments=[{"title": "坏", "date": "2026-11-23",
                              "startTime": "11:00", "endTime": "10:00"}]),
                week_start=MONDAY)

    def test_equal_wake_and_bed_raises(self):
        with self.assertRaises(ValueError):
            plan_from_confirmed(empty_card(wake="07:00", bed="07:00"),
                                week_start=MONDAY)

    def test_invalid_work_hour_raises(self):
        with self.assertRaises(ValueError):
            plan_from_confirmed(empty_card(workStart="25:00"), week_start=MONDAY)

    def test_non_mapping_confirmed_fields_raises(self):
        with self.assertRaises(ValueError):
            plan_from_confirmed("nope", week_start=MONDAY)

    def test_non_list_tasks_raises(self):
        with self.assertRaises(ValueError):
            plan_from_confirmed(empty_card(tasks="not a list"), week_start=MONDAY)

    def test_unparseable_rest_is_warned_not_invented(self):
        plan = plan_from_confirmed(
            empty_card(rest="午休一会儿", tasks=[{"title": "写代码", "details": ""}]),
            week_start=MONDAY,
        )
        self.assertTrue(any("午休一会儿" in w for w in plan["warnings"]),
                        "unparseable rest text must be preserved in warnings")


class FullFlowTests(unittest.TestCase):
    def test_full_flow_fakeclient_offline(self):
        client = FakeClient([full_payload()])
        result = chat("下周我要完成物理作业和统计报告。", base_state(), client=client)
        adapted = adapt_chat(result)
        self.assertTrue(adapted["ready"])
        self.assertEqual(adapted["provider"], "deepseek")

        state = result["state"]
        plan = build_confirmed_schedule(state, now=NOW)
        entries = adapt_schedule(
            plan,
            meta=task_meta_from_facts(state["facts"]),
            provider=adapted["provider"],
        )
        for entry in entries["entries"]:
            self.assertEqual(set(entry.keys()), set(ENTRY_KEYS))
        self.assertTrue(entries["entries"], "schedule must not be empty")
        fixed = next(e for e in entries["entries"]
                     if e["title"] == "Team check-in")
        self.assertEqual(fixed["startTime"], "11:00")
        # Sleep 23:00-07:00 stays protected.
        for entry in entries["entries"]:
            self.assertFalse(overlaps(entry),
                             f"{entry['title']} invades sleep time")
        # Routine occurrences are flagged as genuinely weekly.
        for entry in entries["entries"]:
            if entry["title"] == "运动":
                self.assertIs(entry["repeatWeekly"], True)
            else:
                self.assertIs(entry["repeatWeekly"], False)
        # One-time tasks fall back to the system Medium priority.
        physics = next(e for e in entries["entries"]
                       if e["title"] == "物理作业")
        self.assertEqual(physics["priority"], "Medium")
        self.assertEqual(entries["provider"], "deepseek")
        self.assertIn("unscheduled", entries)
        self.assertIn("warnings", entries)


if __name__ == "__main__":
    unittest.main()
