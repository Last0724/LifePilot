"""Offline tests for ui/integration.py — no real API is used anywhere."""

import unittest
from datetime import date, datetime, time

from core.models import (
    DurationType,
    QuestionnaireData,
    TaskInput,
)
from ui.integration import (
    DEFAULT_UNCERTAIN_MINUTES,
    SCHEDULE_FIELDS,
    build_questionnaire,
    plan_week,
    schedule_to_dicts,
    unscheduled_to_dicts,
)

MON = date(2026, 11, 23)  # a Monday
MON_MIDNIGHT = datetime.combine(MON, time(0, 0))


def payload(**overrides):
    base = {
        "goals": ["Finish the proposal"],
        "tasks": ["Draft the outline", "Review reading notes"],
        "fixed_commitments": [
            {"title": "Team check-in", "date": "2026-11-23", "start": "11:00", "end": "11:30"}
        ],
        "preferred_work_hours": {"start": "09:00", "end": "17:00"},
    }
    base.update(overrides)
    return base


def overlaps(entry: dict, day: date, start: str, end: str) -> bool:
    """True when the schedule entry overlaps [day start, day end)."""
    if entry["date"] != day.isoformat():
        return False
    return entry["start"] < end and start < entry["end"]


class QuestionnaireConversionTests(unittest.TestCase):
    def test_normal_payload_conversion(self):
        build = build_questionnaire(payload(), week_start=MON)
        q = build.questionnaire
        self.assertEqual(q.goals, ["Finish the proposal"])
        self.assertEqual([task.title for task in q.tasks], ["Draft the outline", "Review reading notes"])
        self.assertEqual(q.preferred_work_start, "09:00")
        self.assertEqual(q.preferred_work_end, "17:00")
        self.assertEqual(len(q.fixed_commitments), 1)
        self.assertEqual(q.fixed_commitments[0].title, "Team check-in")
        self.assertEqual(q.fixed_commitments[0].start, datetime(2026, 11, 23, 11, 0))
        self.assertEqual(q.week_start, MON)
        self.assertIn("goals", build.confirmed_fields)
        self.assertIn("tasks", build.confirmed_fields)
        self.assertIn("preferred_work_start", build.confirmed_fields)

    def test_missing_fields_are_not_guessed(self):
        build = build_questionnaire({}, week_start=MON)
        q = build.questionnaire
        self.assertEqual(q.goals, [])
        self.assertEqual(q.tasks, [])
        self.assertEqual(q.fixed_commitments, [])
        # Model defaults are left untouched but are NOT claimed as confirmed.
        self.assertEqual(q.energy_peak, "unknown")
        self.assertEqual(q.work_days, [0, 1, 2, 3, 4, 5, 6])
        self.assertNotIn("energy_peak", build.confirmed_fields)
        self.assertNotIn("work_days", build.confirmed_fields)

    def test_payload_work_days_and_energy_peak_only_when_present(self):
        build = build_questionnaire(
            payload(work_days=[1, 3, 5], energy_peak="morning"), week_start=MON
        )
        self.assertEqual(build.questionnaire.work_days, [1, 3, 5])
        self.assertEqual(build.questionnaire.energy_peak, "morning")
        self.assertIn("work_days", build.confirmed_fields)
        self.assertIn("energy_peak", build.confirmed_fields)

    def test_fixed_commitments_deduplicated(self):
        fixed = {"title": "Class", "date": "2026-11-24", "start": "10:00", "end": "11:00"}
        build = build_questionnaire(payload(fixed_commitments=[fixed, dict(fixed)]), week_start=MON)
        self.assertEqual(len(build.questionnaire.fixed_commitments), 1)

    def test_invalid_fixed_commitment_raises(self):
        bad = {"title": "Class", "date": "2026-11-24", "start": "11:00", "end": "10:00"}
        with self.assertRaises(ValueError):
            build_questionnaire(payload(fixed_commitments=[bad]), week_start=MON)

    def test_overnight_rest_period_conversion(self):
        build = build_questionnaire(
            payload(
                rest_periods=[
                    {"title": "Sleep", "days": [0], "start": "23:00", "end": "07:00"}
                ]
            ),
            week_start=MON,
        )
        rest = build.questionnaire.rest_periods[0]
        self.assertTrue(rest.is_overnight)
        self.assertEqual(rest.duration_minutes, 480)


class TaskInputConversionTests(unittest.TestCase):
    def test_string_tasks_get_uncertain_estimate(self):
        build = build_questionnaire(payload(), week_start=MON)
        task = build.questionnaire.tasks[0]
        self.assertEqual(task.title, "Draft the outline")
        self.assertIs(task.duration_type, DurationType.UNCERTAIN)
        self.assertEqual(task.estimated_minutes, DEFAULT_UNCERTAIN_MINUTES)
        self.assertEqual(task.planned_minutes, 54)  # 45 * 1.2 buffer
        self.assertIn(task.id, build.estimated_task_ids)

    def test_dict_tasks_with_minutes_are_confirmed_predictable(self):
        build = build_questionnaire(
            payload(
                tasks=[
                    {"title": "Write intro", "estimated_minutes": 30},
                    "Freeform task",
                ]
            ),
            week_start=MON,
        )
        first, second = build.questionnaire.tasks
        self.assertIs(first.duration_type, DurationType.PREDICTABLE)
        self.assertEqual(first.estimated_minutes, 30)
        self.assertEqual(first.planned_minutes, 30)  # no buffer
        self.assertNotIn(first.id, build.estimated_task_ids)
        self.assertIn(second.id, build.estimated_task_ids)

    def test_stable_task_ids_across_builds(self):
        first = build_questionnaire(payload(), week_start=MON).questionnaire
        second = build_questionnaire(payload(), week_start=MON).questionnaire
        self.assertEqual([task.id for task in first.tasks], ["t1", "t2"])
        self.assertEqual([task.id for task in first.tasks], [task.id for task in second.tasks])


class ScheduleConversionTests(unittest.TestCase):
    def setUp(self):
        self.build = build_questionnaire(payload(), week_start=MON)
        self.questionnaire = self.build.questionnaire

    def test_normal_schedule_conversion_shape(self):
        plan = plan_week(self.questionnaire, now=MON_MIDNIGHT)
        for entry in plan.schedule:
            for key in SCHEDULE_FIELDS:
                self.assertIn(key, entry)
        tasks = [entry for entry in plan.schedule if not entry["is_fixed"]]
        fixed = [entry for entry in plan.schedule if entry["is_fixed"]]
        self.assertEqual({entry["title"] for entry in tasks}, {"Draft the outline", "Review reading notes"})
        self.assertEqual([entry["title"] for entry in fixed], ["Team check-in"])
        self.assertTrue(all(entry["id"].startswith("t") for entry in tasks))

    def test_fixed_commitments_appear_exactly_once(self):
        plan = plan_week(self.questionnaire, now=MON_MIDNIGHT)
        fixed = [entry for entry in plan.schedule if entry["title"] == "Team check-in"]
        self.assertEqual(len(fixed), 1)
        self.assertTrue(fixed[0]["is_fixed"])

    def test_rest_periods_keep_blocking_after_conversion(self):
        build = build_questionnaire(
            payload(
                rest_periods=[{"title": "Lunch break", "days": [0, 1, 2, 3, 4, 5, 6], "start": "12:00", "end": "13:00"}]
            ),
            week_start=MON,
        )
        plan = plan_week(build.questionnaire, now=MON_MIDNIGHT)
        for entry in plan.schedule:
            if entry["is_fixed"]:
                continue
            day = date.fromisoformat(entry["date"])
            self.assertFalse(overlaps(entry, day, "12:00", "13:00"), entry)
        # Rest periods are never rendered as their own entries.
        self.assertNotIn("Lunch break", [entry["title"] for entry in plan.schedule])

    def test_overnight_rest_blocks_both_days(self):
        build = build_questionnaire(
            payload(
                tasks=["Write at dawn"],
                rest_periods=[{"title": "Sleep", "days": [0], "start": "23:00", "end": "07:00"}],
                preferred_work_hours={"start": "00:00", "end": "23:59"},
            ),
            week_start=MON,
        )
        plan = plan_week(build.questionnaire, now=MON_MIDNIGHT)
        for entry in plan.schedule:
            if entry["is_fixed"]:
                continue
            day = date.fromisoformat(entry["date"])
            if day == MON:
                self.assertFalse(overlaps(entry, MON, "23:00", "23:59"), entry)
            if day == date(2026, 11, 24):
                self.assertFalse(overlaps(entry, date(2026, 11, 24), "00:00", "07:00"), entry)

    def test_unscheduled_tasks_keep_reason(self):
        build = build_questionnaire(
            payload(
                tasks=[{"title": "Huge report", "estimated_minutes": 480, "duration_type": "predictable"}],
                fixed_commitments=[
                    {"title": "Full day", "date": "2026-11-23", "start": "09:00", "end": "17:00"}
                ],
                work_days=[0],
            ),
            week_start=MON,
        )
        plan = plan_week(build.questionnaire, now=MON_MIDNIGHT)
        self.assertEqual(len(plan.unscheduled), 1)
        self.assertEqual(plan.unscheduled[0]["title"], "Huge report")
        self.assertTrue(plan.unscheduled[0]["reason"])
        titles = [entry["title"] for entry in plan.schedule]
        self.assertNotIn("Huge report", titles)

    def test_completed_state_preserved_across_replan(self):
        plan = plan_week(self.questionnaire, now=MON_MIDNIGHT)
        first_tasks = [entry for entry in plan.schedule if not entry["is_fixed"]]
        task_id = first_tasks[0]["id"]
        previous = [{**entry, "completed": entry["id"] == task_id} for entry in first_tasks]
        replan = plan_week(self.questionnaire, now=MON_MIDNIGHT, previous=previous)
        by_id = {entry["id"]: entry for entry in replan.schedule}
        self.assertTrue(by_id[task_id]["completed"])
        self.assertFalse(by_id[first_tasks[1]["id"]]["completed"])

    def test_previous_completed_unknown_ids_ignored(self):
        plan = plan_week(self.questionnaire, now=MON_MIDNIGHT, previous=[{"id": "ghost", "completed": True}])
        self.assertTrue(all(entry["completed"] is False for entry in plan.schedule))


if __name__ == "__main__":
    unittest.main()
