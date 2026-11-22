"""Scheduler V1 的单元测试。

覆盖产品契约中要求的场景：EDF、优先级、固定承诺、休息时段、跨夜与周边界、
偏好窗口、时间缓冲、不拆分任务、deadline、空 work_days、未排原因、受保护区间冲突。
"""

from __future__ import annotations

import unittest
from datetime import date, datetime, time, timedelta, timezone

from core.models import (
    DurationType,
    FixedCommitment,
    PredictableRoutine,
    Priority,
    QuestionnaireData,
    RestPeriod,
    ScheduledItem,
    TaskInput,
)
from core.scheduler import build_schedule


class SchedulerTestBase(unittest.TestCase):
    """构造固定一周（2026-01-05 周一）的测试辅助方法。"""

    WEEK_START = date(2026, 1, 5)  # Monday

    def at(self, day_offset: int, hour: int, minute: int = 0) -> datetime:
        day = self.WEEK_START + timedelta(days=day_offset)
        return datetime.combine(day, time(hour, minute))

    def make_task(self, title: str, minutes: int, *, predictable: bool = False, **kwargs):
        return TaskInput(
            title=title,
            estimated_minutes=minutes,
            duration_type=(
                DurationType.PREDICTABLE if predictable else DurationType.UNCERTAIN
            ),
            **kwargs,
        )

    def make_questionnaire(self, tasks, **overrides) -> QuestionnaireData:
        options = {
            "name": "Scheduler Tester",
            "tasks": list(tasks),
            "preferred_work_start": "09:00",
            "preferred_work_end": "18:00",
            "work_days": [0, 1, 2, 3, 4, 5, 6],
            "week_start": self.WEEK_START,
        }
        options.update(overrides)
        return QuestionnaireData(**options)

    def build(
        self,
        questionnaire: QuestionnaireData,
        now: datetime | None = None,
        locked_items=None,
    ):
        """默认把 now 固定在周一 00:00，避免真实时间让本周空档被裁掉。"""
        if now is None:
            now = self.at(0, 0)
        return build_schedule(questionnaire, now=now, locked_items=locked_items)

    def item(self, result, title: str):
        matches = [item for item in result.items if item.task.title == title]
        self.assertEqual(
            len(matches), 1, f"expected exactly one scheduled item titled {title!r}"
        )
        return matches[0]

    def assert_all_accounted(self, questionnaire: QuestionnaireData, result) -> None:
        expected = len(questionnaire.tasks) + sum(
            len(routine.weekdays)
            for routine in questionnaire.predictable_routines
        )
        self.assertEqual(
            len(result.items) + len(result.unscheduled_tasks),
            expected,
            "每个输入任务和每个 routine occurrence 都必须出现在 "
            "items 或 unscheduled_tasks 中",
        )

    def assert_items_do_not_overlap(self, result) -> None:
        ordered = sorted(result.items, key=lambda item: item.start)
        for left, right in zip(ordered, ordered[1:]):
            self.assertLessEqual(
                left.end,
                right.start,
                f"items overlap: {left.task.title!r} -> {right.task.title!r}",
            )

    def assert_no_overlap(self, item, start: datetime, end: datetime) -> None:
        self.assertTrue(
            item.end <= start or item.start >= end,
            f"{item.task.title!r} overlaps [{start}, {end})",
        )


class OrderingTests(SchedulerTestBase):
    def test_earliest_deadline_first(self) -> None:
        later = self.make_task("later", 30, deadline=self.at(2, 18))
        earlier = self.make_task("earlier", 30, deadline=self.at(1, 18))

        result = self.build(self.make_questionnaire([later, earlier]))

        self.assertEqual([item.task.title for item in result.items], ["earlier", "later"])
        self.assertEqual(self.item(result, "earlier").start, self.at(0, 9))
        # 默认 UNCERTAIN：30 分钟估算会先经过 planned_minutes 的 20% 缓冲 -> 36 分钟。
        self.assertEqual(self.item(result, "later").start, self.at(0, 9, 36))

    def test_priority_breaks_deadline_tie(self) -> None:
        low = self.make_task("low", 30, priority=Priority.LOW)
        medium = self.make_task("medium", 30, priority=Priority.MEDIUM)
        high = self.make_task("high", 30, priority=Priority.HIGH)

        result = self.build(self.make_questionnaire([low, medium, high]))

        self.assertEqual(
            [item.task.title for item in result.items],
            ["high", "medium", "low"],
        )

    def test_input_order_breaks_full_tie(self) -> None:
        first = self.make_task("first", 30)
        second = self.make_task("second", 30)
        third = self.make_task("third", 30)

        result = self.build(self.make_questionnaire([first, second, third]))

        self.assertEqual(
            [item.task.title for item in result.items],
            ["first", "second", "third"],
        )
        self.assertEqual(self.item(result, "first").start, self.at(0, 9))
        self.assertEqual(self.item(result, "second").start, self.at(0, 9, 36))
        self.assertEqual(self.item(result, "third").start, self.at(0, 10, 12))

    def test_predictable_routines_are_scheduled_before_uncertain(self) -> None:
        urgent = self.make_task(
            "urgent", 30, priority=Priority.HIGH, deadline=self.at(0, 18)
        )
        routine = self.make_task("routine", 30, predictable=True)

        result = self.build(
            self.make_questionnaire(
                [urgent, routine], preferred_work_end="10:30"
            )
        )

        self.assertEqual(self.item(result, "routine").start, self.at(0, 9))
        self.assertEqual(self.item(result, "urgent").start, self.at(0, 9, 30))


class ReservationTests(SchedulerTestBase):
    def test_fixed_commitment_is_reserved(self) -> None:
        lecture = FixedCommitment("Lecture", self.at(0, 10), self.at(0, 11))
        task = self.make_task("deep work", 90, predictable=True)

        result = self.build(
            self.make_questionnaire([task], fixed_commitments=[lecture])
        )

        item = self.item(result, "deep work")
        self.assertEqual(item.start, self.at(0, 11))
        self.assertEqual(item.end, self.at(0, 12, 30))
        self.assert_no_overlap(item, lecture.start, lecture.end)

    def test_rest_period_is_reserved(self) -> None:
        lunch = RestPeriod("Lunch", [0], "12:00", "13:00")
        task = self.make_task("study", 200, predictable=True)

        result = self.build(
            self.make_questionnaire([task], rest_periods=[lunch])
        )

        item = self.item(result, "study")
        self.assertEqual(item.start, self.at(0, 13))
        self.assertEqual(item.end, self.at(0, 16, 20))
        self.assert_no_overlap(item, self.at(0, 12), self.at(0, 13))

    def test_rest_period_is_not_buffered(self) -> None:
        lunch = RestPeriod("Lunch", [0], "12:00", "13:00")
        task = self.make_task("study", 180, predictable=True)

        result = self.build(
            self.make_questionnaire([task], rest_periods=[lunch])
        )

        item = self.item(result, "study")
        self.assertEqual(item.start, self.at(0, 9))
        self.assertEqual(item.end, self.at(0, 12))
        self.assert_no_overlap(item, self.at(0, 12), self.at(0, 13))

    def test_overnight_rest_blocks_next_morning(self) -> None:
        sleep = RestPeriod("Sleep", [0], "23:00", "07:00")
        task = self.make_task("morning run", 60, predictable=True)

        result = self.build(
            self.make_questionnaire(
                [task],
                rest_periods=[sleep],
                work_days=[1],  # Tuesday
                preferred_work_start="06:00",
                preferred_work_end="10:00",
            )
        )

        item = self.item(result, "morning run")
        self.assertEqual(item.start, self.at(1, 7))
        self.assertEqual(item.end, self.at(1, 8))

    def test_rest_starting_sunday_blocks_monday_morning(self) -> None:
        sleep = RestPeriod("Sleep", [6], "23:00", "07:00")  # Sunday 23:00
        task = self.make_task("morning run", 60, predictable=True)

        result = self.build(
            self.make_questionnaire(
                [task],
                rest_periods=[sleep],
                work_days=[0],  # Monday
                preferred_work_start="06:00",
                preferred_work_end="10:00",
            )
        )

        item = self.item(result, "morning run")
        self.assertEqual(item.start, self.at(0, 7))
        self.assertEqual(item.end, self.at(0, 8))

    def test_fixed_commitment_spanning_into_week_is_clipped(self) -> None:
        late_event = FixedCommitment(
            "Late event", self.at(-1, 22), self.at(0, 1)  # Sunday 22:00 -> Monday 01:00
        )
        task = self.make_task("early task", 60, predictable=True)

        result = self.build(
            self.make_questionnaire(
                [task],
                fixed_commitments=[late_event],
                work_days=[0],
                preferred_work_start="00:00",
                preferred_work_end="10:00",
            )
        )

        item = self.item(result, "early task")
        self.assertEqual(item.start, self.at(0, 1))
        self.assertEqual(item.end, self.at(0, 2))


class PreferenceTests(SchedulerTestBase):
    def test_preferred_window_is_used_when_available(self) -> None:
        task = self.make_task(
            "focused",
            60,
            predictable=True,
            preferred_start="14:00",
            preferred_end="16:00",
        )

        result = self.build(self.make_questionnaire([task]))

        item = self.item(result, "focused")
        self.assertEqual(item.start, self.at(0, 14))
        self.assertEqual(item.end, self.at(0, 15))
        self.assertTrue(item.preferred_window_satisfied)

    def test_falls_back_outside_preferred_window(self) -> None:
        lecture = FixedCommitment("Lecture", self.at(0, 14), self.at(0, 16))
        task = self.make_task(
            "focused",
            60,
            predictable=True,
            preferred_start="14:00",
            preferred_end="16:00",
            preferred_days=[0],
        )

        result = self.build(
            self.make_questionnaire([task], fixed_commitments=[lecture])
        )

        item = self.item(result, "focused")
        self.assertEqual(item.start, self.at(0, 9))
        self.assertFalse(item.preferred_window_satisfied)

    def test_preferred_day_is_used_when_available(self) -> None:
        task = self.make_task("weekly review", 30, predictable=True, preferred_days=[2])

        result = self.build(self.make_questionnaire([task]))

        item = self.item(result, "weekly review")
        self.assertEqual(item.start.weekday(), 2)
        self.assertEqual(item.start, self.at(2, 9))
        self.assertTrue(item.preferred_window_satisfied)

    def test_falls_back_when_preferred_day_is_full(self) -> None:
        busy = FixedCommitment("Busy day", self.at(2, 9), self.at(2, 18))
        task = self.make_task("weekly review", 30, predictable=True, preferred_days=[2])

        result = self.build(
            self.make_questionnaire([task], fixed_commitments=[busy])
        )

        item = self.item(result, "weekly review")
        self.assertNotEqual(item.start.weekday(), 2)
        self.assertEqual(item.start, self.at(0, 9))
        self.assertFalse(item.preferred_window_satisfied)


class ConstraintTests(SchedulerTestBase):
    def test_time_buffer_uses_planned_minutes(self) -> None:
        uncertain = self.make_task("estimate", 60)
        result = self.build(self.make_questionnaire([uncertain]))
        item = self.item(result, "estimate")
        self.assertEqual(item.task.estimated_minutes, 60)
        self.assertEqual(item.task.planned_minutes, 72)
        self.assertEqual(item.duration_minutes, 72)
        self.assertEqual(item.end - item.start, timedelta(minutes=72))

    def test_predictable_task_is_not_buffered(self) -> None:
        routine = self.make_task("routine", 60, predictable=True)
        result = self.build(self.make_questionnaire([routine]))
        item = self.item(result, "routine")
        self.assertEqual(item.task.planned_minutes, 60)
        self.assertEqual(item.duration_minutes, 60)

    def test_short_uncertain_task_is_not_buffered(self) -> None:
        short = self.make_task("short", 10)
        result = self.build(self.make_questionnaire([short]))
        item = self.item(result, "short")
        self.assertEqual(item.task.planned_minutes, 10)
        self.assertEqual(item.duration_minutes, 10)

    def test_task_is_not_split(self) -> None:
        task = self.make_task("too long for the day", 90, predictable=True)

        result = self.build(
            self.make_questionnaire([task], preferred_work_end="10:00")
        )

        self.assertEqual(result.items, [])
        self.assertEqual(len(result.unscheduled_tasks), 1)
        self.assertIn("连续 90 分钟", result.unscheduled_tasks[0].reason)

    def test_deadline_must_be_met(self) -> None:
        task = self.make_task(
            "deadline task", 120, predictable=True, deadline=self.at(0, 10)
        )

        result = self.build(self.make_questionnaire([task]))

        self.assertEqual(result.items, [])
        reason = result.unscheduled_tasks[0].reason
        self.assertIn("截止时间", reason)
        self.assertIn("10:00", reason)
        self.assertTrue(
            any("deadline task" in warning for warning in result.warnings),
            result.warnings,
        )

    def test_deadline_exactly_at_end_is_allowed(self) -> None:
        task = self.make_task(
            "exact deadline", 60, predictable=True, deadline=self.at(0, 10)
        )

        result = self.build(self.make_questionnaire([task]))

        item = self.item(result, "exact deadline")
        self.assertEqual(item.start, self.at(0, 9))
        self.assertEqual(item.end, self.at(0, 10))
        self.assertEqual(result.unscheduled_tasks, [])

    def test_overdue_task_is_scheduled_into_future_with_warning(self) -> None:
        task = self.make_task(
            "overdue", 30, predictable=True, deadline=self.at(-1, 12)
        )

        result = self.build(self.make_questionnaire([task]))

        self.assertEqual(result.unscheduled_tasks, [])
        item = self.item(result, "overdue")
        self.assertEqual(item.start, self.at(0, 9))
        self.assertEqual(item.end, self.at(0, 9, 30))
        warnings = "\n".join(result.warnings)
        self.assertIn("Overdue", warnings)
        self.assertIn("overdue", warnings)

    def test_empty_work_days_does_not_crash(self) -> None:
        task = self.make_task("no workdays", 30, predictable=True)

        result = self.build(self.make_questionnaire([task], work_days=[]))

        self.assertEqual(result.items, [])
        self.assertEqual(len(result.unscheduled_tasks), 1)
        self.assertIn("work_days 为空", result.unscheduled_tasks[0].reason)
        self.assertTrue(
            any("work_days 为空" in warning for warning in result.warnings),
            result.warnings,
        )

    def test_overlapping_protected_intervals_are_reported(self) -> None:
        lecture = FixedCommitment("Lecture", self.at(0, 10), self.at(0, 12))
        nap = RestPeriod("Nap", [0], "11:00", "13:00")
        task = self.make_task("task", 60, predictable=True)

        result = self.build(
            self.make_questionnaire(
                [task], fixed_commitments=[lecture], rest_periods=[nap]
            )
        )

        self.assertTrue(
            any("重叠" in warning for warning in result.warnings),
            result.warnings,
        )
        self.assertTrue(
            any("Lecture" in warning and "Nap" in warning for warning in result.warnings),
            result.warnings,
        )
        item = self.item(result, "task")
        self.assert_no_overlap(item, lecture.start, lecture.end)
        self.assert_no_overlap(item, self.at(0, 11), self.at(0, 13))
        self.assert_items_do_not_overlap(result)

    def test_all_tasks_are_accounted_for(self) -> None:
        lecture = FixedCommitment("Lecture", self.at(0, 10), self.at(0, 11))
        tasks = [
            self.make_task("a", 30),
            self.make_task("b", 60, predictable=True, deadline=self.at(0, 10)),
            self.make_task("c", 90, predictable=True),
        ]

        questionnaire = self.make_questionnaire(
            tasks, fixed_commitments=[lecture]
        )
        result = self.build(questionnaire)

        self.assert_all_accounted(questionnaire, result)
        self.assert_items_do_not_overlap(result)

    def test_empty_questionnaire(self) -> None:
        result = self.build(self.make_questionnaire([]))

        self.assertEqual(result.items, [])
        self.assertEqual(result.unscheduled_tasks, [])
        self.assertEqual(result.warnings, [])


class DeadlinePolicyTests(SchedulerTestBase):
    def test_no_deadline_tasks_are_scheduled_last(self) -> None:
        undated = self.make_task("someday", 30, priority=Priority.HIGH)
        dated = self.make_task(
            "dated", 30, priority=Priority.LOW, deadline=self.at(4, 18)
        )

        result = self.build(self.make_questionnaire([undated, dated]))

        self.assertEqual(
            [item.task.title for item in result.items], ["dated", "someday"]
        )
        self.assertEqual(self.item(result, "dated").start, self.at(0, 9))
        self.assertEqual(self.item(result, "someday").start, self.at(0, 9, 36))

    def test_overdue_task_uses_slot_after_now(self) -> None:
        task = self.make_task(
            "overdue", 60, predictable=True, deadline=self.at(0, 12)
        )

        result = self.build(
            self.make_questionnaire([task], work_days=[0, 1]),
            now=self.at(1, 12),
        )

        item = self.item(result, "overdue")
        self.assertEqual(item.start, self.at(1, 12))
        self.assertIn("Overdue", "\n".join(result.warnings))

    def test_unscheduled_this_week_is_not_marked_overdue(self) -> None:
        task = self.make_task(
            "exam prep", 90, predictable=True, deadline=self.at(8, 12)
        )

        result = self.build(
            self.make_questionnaire(
                [task], work_days=[0], preferred_work_end="10:00"
            )
        )

        self.assertEqual(result.items, [])
        self.assertEqual(len(result.unscheduled_tasks), 1)
        self.assertNotIn("已逾期", result.unscheduled_tasks[0].reason)
        self.assertNotIn("Overdue", "\n".join(result.warnings))


class CurrentTimeTests(SchedulerTestBase):
    def test_no_task_is_scheduled_before_now(self) -> None:
        now = self.at(1, 12)  # Tuesday noon
        task = self.make_task("later today", 60, predictable=True)

        result = self.build(
            self.make_questionnaire([task], work_days=[0, 1]), now=now
        )

        item = self.item(result, "later today")
        self.assertEqual(item.start, self.at(1, 12))
        for scheduled in result.items:
            self.assertGreaterEqual(scheduled.start, now)

    def test_now_must_be_naive(self) -> None:
        task = self.make_task("task", 30, predictable=True)
        with self.assertRaises(ValueError):
            build_schedule(
                self.make_questionnaire([task]),
                now=datetime(2026, 1, 5, 9, 0, tzinfo=timezone.utc),
            )


class ProtectedOverlapTests(SchedulerTestBase):
    def test_all_three_overlap_combinations_are_reported(self) -> None:
        lecture_a = FixedCommitment("A", self.at(0, 10), self.at(0, 12))
        lecture_b = FixedCommitment("B", self.at(0, 11), self.at(0, 13))
        nap = RestPeriod("Nap", [0], "11:30", "12:30")
        lunch = RestPeriod("Lunch", [0], "12:00", "13:30")

        result = self.build(
            self.make_questionnaire(
                [],
                fixed_commitments=[lecture_a, lecture_b],
                rest_periods=[nap, lunch],
            )
        )

        warnings = "\n".join(result.warnings)
        self.assertIn("固定承诺 'A' 与 固定承诺 'B' 重叠", warnings)
        self.assertIn("休息时段 'Nap' 与 休息时段 'Lunch' 重叠", warnings)
        self.assertIn("固定承诺 'A' 与 休息时段 'Nap' 重叠", warnings)


class ImportanceRankTests(SchedulerTestBase):
    def test_explicit_importance_rank_orders_tasks(self) -> None:
        third = self.make_task("third", 30, importance_rank=3)
        first = self.make_task("first", 30, importance_rank=1)
        second = self.make_task("second", 30, importance_rank=2)

        result = self.build(self.make_questionnaire([third, first, second]))

        self.assertEqual(
            [item.task.title for item in result.items], ["first", "second", "third"]
        )
        self.assertEqual(self.item(result, "first").start, self.at(0, 9))
        self.assertEqual(self.item(result, "second").start, self.at(0, 9, 36))
        self.assertEqual(self.item(result, "third").start, self.at(0, 10, 12))

    def test_equal_importance_rank_uses_input_order(self) -> None:
        alpha = self.make_task("alpha", 30, importance_rank=2)
        beta = self.make_task("beta", 30, importance_rank=2)

        result = self.build(self.make_questionnaire([beta, alpha]))

        self.assertEqual(
            [item.task.title for item in result.items], ["beta", "alpha"]
        )
        self.assertEqual(self.item(result, "beta").start, self.at(0, 9))
        self.assertEqual(self.item(result, "alpha").start, self.at(0, 9, 36))

    def test_earlier_deadline_beats_importance_rank(self) -> None:
        important = self.make_task("important someday", 30, importance_rank=1)
        dated = self.make_task(
            "dated late", 30, importance_rank=9, deadline=self.at(1, 18)
        )

        result = self.build(self.make_questionnaire([important, dated]))

        self.assertEqual(
            [item.task.title for item in result.items],
            ["dated late", "important someday"],
        )

    def test_explicit_rank_overrides_legacy_priority(self) -> None:
        legacy_high = self.make_task(
            "legacy high", 30, priority=Priority.HIGH, importance_rank=4
        )
        explicit_first = self.make_task("explicit first", 30, importance_rank=1)

        result = self.build(self.make_questionnaire([legacy_high, explicit_first]))

        self.assertEqual(
            [item.task.title for item in result.items],
            ["explicit first", "legacy high"],
        )


class LockedItemTests(SchedulerTestBase):
    def test_locked_item_retains_time_and_reserves_slot(self) -> None:
        locked = self.make_task("locked", 60, predictable=True, id="t1")
        other = self.make_task("other", 60, predictable=True, id="t2")
        questionnaire = self.make_questionnaire([locked, other])
        lock = ScheduledItem(locked, self.at(0, 14), self.at(0, 15), locked=True)

        result = self.build(questionnaire, locked_items=[lock])

        retained = self.item(result, "locked")
        self.assertEqual(retained.start, self.at(0, 14))
        self.assertEqual(retained.end, self.at(0, 15))
        self.assertTrue(retained.locked)
        self.assertEqual(self.item(result, "other").start, self.at(0, 9))
        self.assert_items_do_not_overlap(result)
        self.assert_all_accounted(questionnaire, result)

    def test_unlocked_items_are_not_retained(self) -> None:
        task = self.make_task("not locked", 60, predictable=True, id="t1")
        questionnaire = self.make_questionnaire([task])
        item = ScheduledItem(task, self.at(0, 14), self.at(0, 15), locked=False)

        result = self.build(questionnaire, locked_items=[item])

        self.assertEqual(self.item(result, "not locked").start, self.at(0, 9))
        self.assertFalse(self.item(result, "not locked").locked)

    def test_locked_item_conflicting_with_fixed_commitment_is_released(self) -> None:
        task = self.make_task("locked", 60, predictable=True, id="t1")
        lecture = FixedCommitment("Lecture", self.at(0, 14), self.at(0, 15))
        questionnaire = self.make_questionnaire(
            [task], fixed_commitments=[lecture]
        )
        lock = ScheduledItem(task, self.at(0, 14), self.at(0, 15), locked=True)

        result = self.build(questionnaire, locked_items=[lock])

        retained = self.item(result, "locked")
        self.assertFalse(retained.locked)
        self.assertEqual(retained.start, self.at(0, 9))
        self.assertTrue(
            any("未被保留" in warning for warning in result.warnings),
            result.warnings,
        )
        self.assert_all_accounted(questionnaire, result)

    def test_locked_item_that_breaks_upcoming_deadline_is_released(self) -> None:
        task = self.make_task(
            "deadline", 60, predictable=True, deadline=self.at(0, 12)
        )
        questionnaire = self.make_questionnaire([task])
        lock = ScheduledItem(task, self.at(0, 14), self.at(0, 15), locked=True)

        result = self.build(questionnaire, locked_items=[lock])

        retained = self.item(result, "deadline")
        self.assertFalse(retained.locked)
        self.assertEqual(retained.start, self.at(0, 9))
        self.assertTrue(
            any("截止" in warning for warning in result.warnings), result.warnings
        )
        self.assertEqual(retained.end, self.at(0, 10))

    def test_locked_item_in_the_past_is_released(self) -> None:
        task = self.make_task("past lock", 60, predictable=True)
        questionnaire = self.make_questionnaire([task])
        lock = ScheduledItem(task, self.at(0, 9), self.at(0, 10), locked=True)

        result = self.build(questionnaire, now=self.at(0, 12), locked_items=[lock])

        retained = self.item(result, "past lock")
        self.assertFalse(retained.locked)
        self.assertEqual(retained.start, self.at(0, 12))
        self.assertTrue(
            any("过去" in warning for warning in result.warnings), result.warnings
        )

    def test_locked_item_with_changed_duration_is_released(self) -> None:
        task = self.make_task("changed", 30, predictable=True)
        questionnaire = self.make_questionnaire([task])
        lock = ScheduledItem(task, self.at(0, 9), self.at(0, 10), locked=True)

        result = self.build(questionnaire, locked_items=[lock])

        retained = self.item(result, "changed")
        self.assertFalse(retained.locked)
        self.assertEqual(retained.start, self.at(0, 9))
        self.assertEqual(retained.end, self.at(0, 9, 30))
        self.assertTrue(
            any("时长" in warning for warning in result.warnings), result.warnings
        )

    def test_unknown_locked_task_is_ignored(self) -> None:
        task = self.make_task("real", 30, predictable=True)
        ghost = TaskInput("ghost", 30, id="t99")
        questionnaire = self.make_questionnaire([task])
        lock = ScheduledItem(ghost, self.at(0, 14), self.at(0, 14, 30), locked=True)

        result = self.build(questionnaire, locked_items=[lock])

        self.assertEqual([item.task.title for item in result.items], ["real"])
        self.assertTrue(
            any("不在当前问卷" in warning for warning in result.warnings),
            result.warnings,
        )
        self.assert_all_accounted(questionnaire, result)

    def test_locked_item_with_overdue_deadline_keeps_overdue_warning(self) -> None:
        task = self.make_task(
            "overdue lock", 60, predictable=True, deadline=self.at(-1, 12)
        )
        questionnaire = self.make_questionnaire([task])
        lock = ScheduledItem(task, self.at(0, 14), self.at(0, 15), locked=True)

        result = self.build(questionnaire, locked_items=[lock])

        retained = self.item(result, "overdue lock")
        self.assertTrue(retained.locked)
        self.assertEqual(retained.start, self.at(0, 14))
        self.assertIn("Overdue", "\n".join(result.warnings))

    def test_overlapping_locks_only_first_is_kept(self) -> None:
        first = self.make_task("first lock", 60, predictable=True, id="t1")
        second = self.make_task("second lock", 60, predictable=True, id="t2")
        questionnaire = self.make_questionnaire([first, second])
        locks = [
            ScheduledItem(first, self.at(0, 14), self.at(0, 15), locked=True),
            ScheduledItem(second, self.at(0, 14, 30), self.at(0, 15, 30), locked=True),
        ]

        result = self.build(questionnaire, locked_items=locks)

        self.assertTrue(self.item(result, "first lock").locked)
        self.assertEqual(self.item(result, "first lock").start, self.at(0, 14))
        self.assertFalse(self.item(result, "second lock").locked)
        self.assertIn(
            "未被保留", "\n".join(warning for warning in result.warnings)
        )
        self.assert_all_accounted(questionnaire, result)

    def test_locked_item_outside_work_hours_is_released(self) -> None:
        task = self.make_task("late", 60, predictable=True)
        questionnaire = self.make_questionnaire([task])
        lock = ScheduledItem(task, self.at(0, 20), self.at(0, 21), locked=True)

        result = self.build(questionnaire, locked_items=[lock])

        retained = self.item(result, "late")
        self.assertFalse(retained.locked)
        self.assertEqual(retained.start, self.at(0, 9))
        self.assertTrue(
            any("工作时间" in warning for warning in result.warnings),
            result.warnings,
        )

    def test_locked_item_outside_work_days_is_released(self) -> None:
        task = self.make_task("weekend", 60, predictable=True)
        questionnaire = self.make_questionnaire([task], work_days=[0, 1, 2, 3, 4])
        lock = ScheduledItem(task, self.at(6, 9), self.at(6, 10), locked=True)

        result = self.build(questionnaire, locked_items=[lock])

        retained = self.item(result, "weekend")
        self.assertFalse(retained.locked)
        self.assertEqual(retained.start, self.at(0, 9))
        self.assertTrue(
            any("工作星期" in warning for warning in result.warnings),
            result.warnings,
        )

    def test_aware_locked_item_is_released(self) -> None:
        task = self.make_task("aware", 60, predictable=True)
        questionnaire = self.make_questionnaire([task])
        lock = ScheduledItem(
            task,
            datetime(2026, 1, 5, 14, tzinfo=timezone.utc),
            datetime(2026, 1, 5, 15, tzinfo=timezone.utc),
            locked=True,
        )

        result = self.build(questionnaire, locked_items=[lock])

        retained = self.item(result, "aware")
        self.assertFalse(retained.locked)
        self.assertEqual(retained.start, self.at(0, 9))
        self.assertTrue(
            any("时区" in warning for warning in result.warnings), result.warnings
        )

    def test_locked_item_is_not_scheduled_twice(self) -> None:
        task = self.make_task("once", 60, predictable=True, id="t1")
        questionnaire = self.make_questionnaire([task])
        lock = ScheduledItem(task, self.at(0, 14), self.at(0, 15), locked=True)

        result = self.build(questionnaire, locked_items=[lock])

        self.assertEqual(len([item for item in result.items if item.task_id == "t1"]), 1)
        self.assert_all_accounted(questionnaire, result)


class PredictableRoutineTests(SchedulerTestBase):
    def test_routine_is_scheduled_on_each_weekday_without_buffer(self) -> None:
        routine = PredictableRoutine("Morning run", [0, 2], 30)
        questionnaire = self.make_questionnaire(
            [], predictable_routines=[routine]
        )

        result = self.build(questionnaire)

        self.assertEqual(len(result.items), 2)
        self.assertEqual(result.unscheduled_tasks, [])
        monday = [item for item in result.items if item.start.weekday() == 0][0]
        wednesday = [item for item in result.items if item.start.weekday() == 2][0]
        self.assertEqual(monday.start, self.at(0, 9))
        self.assertEqual(wednesday.start, self.at(2, 9))
        # 30 分钟 routine 必须原样 30 分钟，不能像 UNCERTAIN 任务一样变成 36。
        self.assertEqual(monday.duration_minutes, 30)
        self.assertEqual(wednesday.duration_minutes, 30)
        self.assertEqual(monday.task.category, "predictable_routine")
        self.assertEqual(
            len({item.task.id for item in result.items}),
            2,
            "每个 routine occurrence 必须有唯一 id",
        )
        self.assert_all_accounted(questionnaire, result)

    def test_routine_prefers_requested_window(self) -> None:
        routine = PredictableRoutine(
            "Gym",
            [0],
            30,
            preferred_start="14:00",
            preferred_end="15:00",
        )
        questionnaire = self.make_questionnaire(
            [], predictable_routines=[routine]
        )

        result = self.build(questionnaire)

        self.assertEqual(self.item(result, "Gym").start, self.at(0, 14))

    def test_routine_start_only_preference_is_respected_when_possible(self) -> None:
        routine = PredictableRoutine(
            "Evening reading", [0], 30, preferred_start="13:00"
        )
        questionnaire = self.make_questionnaire(
            [], predictable_routines=[routine]
        )

        result = self.build(questionnaire)

        self.assertEqual(self.item(result, "Evening reading").start, self.at(0, 13))

    def test_routine_falls_back_when_preferred_window_is_occupied(self) -> None:
        routine = PredictableRoutine(
            "Gym",
            [0],
            30,
            preferred_start="14:00",
            preferred_end="15:00",
        )
        commitment = FixedCommitment("Class", self.at(0, 14), self.at(0, 15))
        questionnaire = self.make_questionnaire(
            [],
            fixed_commitments=[commitment],
            predictable_routines=[routine],
        )

        result = self.build(questionnaire)

        item = self.item(result, "Gym")
        self.assertEqual(item.start, self.at(0, 9))
        self.assert_no_overlap(item, self.at(0, 14), self.at(0, 15))

    def test_routine_respects_rest_period(self) -> None:
        routine = PredictableRoutine(
            "Reading", [0], 30, preferred_start="12:00"
        )
        rest = RestPeriod("Lunch", [0], "12:00", "13:00")
        questionnaire = self.make_questionnaire(
            [],
            rest_periods=[rest],
            predictable_routines=[routine],
        )

        result = self.build(questionnaire)

        item = self.item(result, "Reading")
        self.assertEqual(item.start, self.at(0, 13))
        self.assert_no_overlap(item, self.at(0, 12), self.at(0, 13))
        self.assert_all_accounted(questionnaire, result)

    def test_routine_occupies_slot_before_uncertain_task(self) -> None:
        routine = PredictableRoutine("Daily review", [0], 60)
        task = self.make_task("uncertain task", 60)
        questionnaire = self.make_questionnaire(
            [task], predictable_routines=[routine]
        )

        result = self.build(questionnaire)

        self.assertEqual(self.item(result, "Daily review").start, self.at(0, 9))
        self.assertEqual(self.item(result, "uncertain task").start, self.at(0, 10))

    def test_routine_on_non_work_day_is_scheduled(self) -> None:
        routine = PredictableRoutine("Weekend walk", [5], 30)
        questionnaire = self.make_questionnaire(
            [],
            work_days=[0, 1, 2, 3, 4],
            predictable_routines=[routine],
        )

        result = self.build(questionnaire)

        self.assertEqual(len(result.items), 1)
        self.assertEqual(result.unscheduled_tasks, [])
        self.assertEqual(result.items[0].start, self.at(5, 9))
        self.assertEqual(result.items[0].duration_minutes, 30)
        self.assert_all_accounted(questionnaire, result)

    def test_routine_without_free_slot_on_non_work_day_is_unscheduled(self) -> None:
        routine = PredictableRoutine("Weekend walk", [5], 30)
        commitment = FixedCommitment("All-day event", self.at(5, 9), self.at(5, 18))
        questionnaire = self.make_questionnaire(
            [],
            work_days=[0, 1, 2, 3, 4],
            fixed_commitments=[commitment],
            predictable_routines=[routine],
        )

        result = self.build(questionnaire)

        self.assertEqual(result.items, [])
        self.assertEqual(len(result.unscheduled_tasks), 1)
        reason = result.unscheduled_tasks[0].reason
        self.assertIn("找不到连续 30 分钟", reason)
        self.assertNotIn("work_days", reason)
        self.assert_all_accounted(questionnaire, result)

    def test_routine_is_scheduled_when_work_days_is_empty(self) -> None:
        routine = PredictableRoutine("Weekend walk", [5], 30)
        questionnaire = self.make_questionnaire(
            [],
            work_days=[],
            predictable_routines=[routine],
        )

        result = self.build(questionnaire)

        self.assertEqual([item.start for item in result.items], [self.at(5, 9)])
        self.assertEqual(result.unscheduled_tasks, [])
        self.assertTrue(
            any("work_days 为空" in warning for warning in result.warnings)
        )
        self.assert_all_accounted(questionnaire, result)

    def test_routine_does_not_append_to_questionnaire_tasks(self) -> None:
        routine = PredictableRoutine("Morning run", [0, 2], 30)
        real = self.make_task("real task", 30)
        questionnaire = self.make_questionnaire(
            [real], predictable_routines=[routine]
        )

        result = self.build(questionnaire)

        self.assertEqual(questionnaire.tasks, [real])
        routine_items = [
            item
            for item in result.items
            if item.task.category == "predictable_routine"
        ]
        self.assertEqual(len(routine_items), 2)
        self.assert_all_accounted(questionnaire, result)

    def test_routine_adapter_id_avoids_real_task_ids(self) -> None:
        real = self.make_task("real task", 30, id="routine-1-0")
        routine = PredictableRoutine("Morning run", [0], 30)
        questionnaire = self.make_questionnaire(
            [real], predictable_routines=[routine]
        )

        result = self.build(questionnaire)

        self.assertEqual(len(result.items), 2)
        routine_items = [
            item
            for item in result.items
            if item.task.category == "predictable_routine"
        ]
        self.assertEqual(len(routine_items), 1)
        self.assertNotEqual(routine_items[0].task_id, "routine-1-0")
        self.assert_all_accounted(questionnaire, result)


if __name__ == "__main__":
    unittest.main()
