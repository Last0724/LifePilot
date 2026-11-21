"""``core.models`` 的单元测试。

只使用标准库 ``unittest``，因此不需要安装任何依赖即可运行：

    .venv\\Scripts\\python.exe -m unittest discover -s tests -v
"""

import unittest
from dataclasses import FrozenInstanceError
from datetime import date, datetime, time

from core.models import (
    ENERGY_PEAKS,
    ActivityCategory,
    ActivitySuggestion,
    ConsultationDraft,
    DurationType,
    FixedCommitment,
    FollowUpQuestion,
    ModelError,
    Priority,
    QuestionnaireData,
    RestPeriod,
    ScheduleResult,
    ScheduledItem,
    TaskInput,
    UnscheduledTask,
    UserProfile,
    monday_of,
    parse_hhmm,
)


def at(day: int = 23, hour: int = 9, minute: int = 0) -> datetime:
    """2026-11-23 是周一，方便测试。"""
    return datetime(2026, 11, day, hour, minute)


class HelperTests(unittest.TestCase):
    def test_monday_of_returns_monday(self) -> None:
        self.assertEqual(monday_of(date(2026, 11, 23)), date(2026, 11, 23))
        self.assertEqual(monday_of(date(2026, 11, 29)), date(2026, 11, 23))
        self.assertEqual(monday_of(date(2026, 11, 21)), date(2026, 11, 16))

    def test_monday_of_rejects_datetime(self) -> None:
        with self.assertRaises(ModelError):
            monday_of(datetime(2026, 11, 23, 9, 0))  # type: ignore[arg-type]

    def test_parse_hhmm(self) -> None:
        self.assertEqual(parse_hhmm("00:00"), time(0, 0))
        self.assertEqual(parse_hhmm("09:05"), time(9, 5))
        self.assertEqual(parse_hhmm("23:59"), time(23, 59))
        self.assertEqual(parse_hhmm(" 08:30 "), time(8, 30))

    def test_parse_hhmm_rejects_bad_values(self) -> None:
        for bad in ["9:00", "09:0", "24:00", "09:60", "0900", "", 900]:
            with self.assertRaises(ModelError, msg=f"bad value: {bad!r}"):
                parse_hhmm(bad)  # type: ignore[arg-type]


class PriorityTests(unittest.TestCase):
    def test_rank_order(self) -> None:
        self.assertLess(Priority.HIGH.rank, Priority.MEDIUM.rank)
        self.assertLess(Priority.MEDIUM.rank, Priority.LOW.rank)

    def test_sorted_by_rank(self) -> None:
        priorities = [Priority.LOW, Priority.HIGH, Priority.MEDIUM]
        ordered = sorted(priorities, key=lambda priority: priority.rank)
        self.assertEqual(ordered, [Priority.HIGH, Priority.MEDIUM, Priority.LOW])

    def test_is_json_friendly_str_enum(self) -> None:
        self.assertEqual(Priority.HIGH.value, "high")
        self.assertEqual(Priority.HIGH, "high")


class TaskInputTests(unittest.TestCase):
    def test_valid_task_defaults(self) -> None:
        task = TaskInput("Read paper", 60)
        self.assertEqual(task.title, "Read paper")
        self.assertEqual(task.estimated_minutes, 60)
        self.assertEqual(task.id, "")
        self.assertIs(task.priority, Priority.MEDIUM)
        self.assertIsNone(task.deadline)
        self.assertEqual(task.preferred_period, "")
        self.assertIs(task.duration_type, DurationType.UNCERTAIN)
        self.assertIsNone(task.preferred_start)
        self.assertIsNone(task.preferred_end)
        self.assertIsNone(task.preferred_days)

    def test_title_is_stripped(self) -> None:
        self.assertEqual(TaskInput("  Read paper  ", 30).title, "Read paper")

    def test_empty_title_rejected(self) -> None:
        with self.assertRaises(ModelError):
            TaskInput("   ", 30)
        with self.assertRaises(ModelError):
            TaskInput(123, 30)  # type: ignore[arg-type]

    def test_duration_bounds(self) -> None:
        TaskInput("one minute", 1)
        TaskInput("eight hours", 480)
        for bad in (0, 481, -5):
            with self.assertRaises(ModelError, msg=f"bad duration: {bad}"):
                TaskInput("x", bad)

    def test_duration_must_be_integer(self) -> None:
        for bad in (30.0, "30", True):
            with self.assertRaises(ModelError, msg=f"bad duration: {bad!r}"):
                TaskInput("x", bad)  # type: ignore[arg-type]

    def test_priority_must_be_enum(self) -> None:
        with self.assertRaises(ModelError):
            TaskInput("x", 30, priority="high")  # type: ignore[arg-type]

    def test_deadline_must_be_datetime(self) -> None:
        TaskInput("x", 30, deadline=at(25, 23, 59))
        with self.assertRaises(ModelError):
            TaskInput("x", 30, deadline=date(2026, 11, 25))  # type: ignore[arg-type]

    def test_preferred_period(self) -> None:
        self.assertEqual(
            TaskInput("x", 30, preferred_period=" Evening ").preferred_period,
            "evening",
        )
        with self.assertRaises(ModelError):
            TaskInput("x", 30, preferred_period="night")

    def test_id_must_be_string(self) -> None:
        with self.assertRaises(ModelError):
            TaskInput("x", 30, id=1)  # type: ignore[arg-type]

    def test_duration_type_must_be_enum(self) -> None:
        with self.assertRaises(ModelError):
            TaskInput("x", 30, duration_type="uncertain")  # type: ignore[arg-type]

    def test_planned_minutes_predictable_has_no_buffer(self) -> None:
        task = TaskInput("Lunch", 45, duration_type=DurationType.PREDICTABLE)
        self.assertEqual(task.planned_minutes, 45)
        self.assertEqual(task.estimated_minutes, 45)

    def test_planned_minutes_uncertain_has_buffer(self) -> None:
        self.assertEqual(TaskInput("x", 1).planned_minutes, 1)
        self.assertEqual(TaskInput("x", 10).planned_minutes, 10)
        self.assertEqual(TaskInput("x", 11).planned_minutes, 14)  # ceil(13.2)
        self.assertEqual(TaskInput("x", 30).planned_minutes, 36)
        self.assertEqual(TaskInput("x", 60).planned_minutes, 72)
        self.assertEqual(TaskInput("x", 480).planned_minutes, 576)

    def test_planned_minutes_never_changes_estimate(self) -> None:
        task = TaskInput("x", 11)
        self.assertEqual(task.planned_minutes, 14)
        self.assertEqual(task.estimated_minutes, 11)

    def test_preferred_window_is_normalized(self) -> None:
        task = TaskInput("x", 30, preferred_start=" 08:30 ", preferred_end="09:00")
        self.assertEqual(task.preferred_start, "08:30")
        self.assertEqual(task.preferred_end, "09:00")
        self.assertTrue(task.has_preferred_window)

    def test_preferred_window_requires_both_ends(self) -> None:
        with self.assertRaises(ModelError):
            TaskInput("x", 30, preferred_start="09:00")
        with self.assertRaises(ModelError):
            TaskInput("x", 30, preferred_end="09:00")

    def test_preferred_window_must_be_forward_facing(self) -> None:
        for start, end in [("09:00", "09:00"), ("22:00", "07:00")]:
            with self.assertRaises(ModelError, msg=f"{start} ~ {end}"):
                TaskInput("x", 30, preferred_start=start, preferred_end=end)

    def test_preferred_days_are_normalized(self) -> None:
        self.assertEqual(TaskInput("x", 30, preferred_days=[5, 1, 1]).preferred_days, [1, 5])
        self.assertIsNone(TaskInput("x", 30, preferred_days=[]).preferred_days)
        with self.assertRaises(ModelError):
            TaskInput("x", 30, preferred_days=[7])


class FixedCommitmentTests(unittest.TestCase):
    def test_valid_commitment(self) -> None:
        commitment = FixedCommitment("Class", at(23, 9), at(23, 11), "Room 101")
        self.assertEqual(commitment.duration_minutes, 120)
        self.assertEqual(commitment.location, "Room 101")

    def test_end_must_be_later_than_start(self) -> None:
        for end in (at(23, 9), at(23, 8)):
            with self.assertRaises(ModelError):
                FixedCommitment("Class", at(23, 9), end)

    def test_commitment_is_immutable(self) -> None:
        commitment = FixedCommitment("Class", at(23, 9), at(23, 11))
        with self.assertRaises(FrozenInstanceError):
            commitment.title = "Changed"  # type: ignore[misc]

    def test_invalid_types(self) -> None:
        with self.assertRaises(ModelError):
            FixedCommitment("", at(23, 9), at(23, 11))
        with self.assertRaises(ModelError):
            FixedCommitment("Class", date(2026, 11, 23), at(23, 11))  # type: ignore[arg-type]


class RestPeriodTests(unittest.TestCase):
    def test_overnight_rest_period(self) -> None:
        period = RestPeriod("Sleep", [0, 1, 1], "23:00", "07:00")
        self.assertEqual(period.days, [0, 1])
        self.assertTrue(period.is_overnight)
        self.assertEqual(period.duration_minutes, 480)

    def test_same_day_rest_period(self) -> None:
        period = RestPeriod("Lunch break", [2], "12:00", "13:30")
        self.assertFalse(period.is_overnight)
        self.assertEqual(period.duration_minutes, 90)

    def test_title_is_required(self) -> None:
        with self.assertRaises(ModelError):
            RestPeriod("   ", [0], "23:00", "07:00")

    def test_days_are_required_and_validated(self) -> None:
        with self.assertRaises(ModelError):
            RestPeriod("Sleep", [], "23:00", "07:00")
        with self.assertRaises(ModelError):
            RestPeriod("Sleep", [7], "23:00", "07:00")

    def test_equal_start_end_rejected(self) -> None:
        with self.assertRaises(ModelError):
            RestPeriod("Sleep", [0], "23:00", "23:00")

    def test_bad_time_format_rejected(self) -> None:
        with self.assertRaises(ModelError):
            RestPeriod("Sleep", [0], "9:00", "07:00")


class FollowUpQuestionTests(unittest.TestCase):
    def test_valid_question(self) -> None:
        question = FollowUpQuestion("q1", "  How many hours?  ")
        self.assertEqual(question.id, "q1")
        self.assertEqual(question.question, "How many hours?")

    def test_id_must_be_q1_or_q2(self) -> None:
        with self.assertRaises(ModelError):
            FollowUpQuestion("q3", "Why?")
        with self.assertRaises(ModelError):
            FollowUpQuestion(1, "Why?")  # type: ignore[arg-type]

    def test_question_must_not_be_empty(self) -> None:
        with self.assertRaises(ModelError):
            FollowUpQuestion("q1", "   ")


class ActivitySuggestionTests(unittest.TestCase):
    def test_valid_suggestion(self) -> None:
        suggestion = ActivitySuggestion(
            "Morning run", ActivityCategory.PREDICTABLE_ROUTINE, "固定晨跑", "t1"
        )
        self.assertIs(suggestion.suggested_category, ActivityCategory.PREDICTABLE_ROUTINE)
        self.assertEqual(suggestion.source_task_id, "t1")

    def test_source_task_id_is_optional(self) -> None:
        suggestion = ActivitySuggestion(
            "Sleep", ActivityCategory.REST_PERIOD, "每天 23:00 入睡"
        )
        self.assertIsNone(suggestion.source_task_id)

    def test_fields_are_required(self) -> None:
        with self.assertRaises(ModelError):
            ActivitySuggestion("", ActivityCategory.REST_PERIOD, "reason")
        with self.assertRaises(ModelError):
            ActivitySuggestion("Sleep", ActivityCategory.REST_PERIOD, "   ")
        with self.assertRaises(ModelError):
            ActivitySuggestion("Sleep", "rest_period", "reason")  # type: ignore[arg-type]
        with self.assertRaises(ModelError):
            ActivitySuggestion(
                "Sleep", ActivityCategory.REST_PERIOD, "reason", ""
            )

    def test_is_immutable(self) -> None:
        suggestion = ActivitySuggestion(
            "Sleep", ActivityCategory.REST_PERIOD, "reason"
        )
        with self.assertRaises(FrozenInstanceError):
            suggestion.reason = "changed"  # type: ignore[misc]


class ConsultationDraftTests(unittest.TestCase):
    def test_zero_one_two_questions_allowed(self) -> None:
        self.assertEqual(ConsultationDraft().follow_up_questions, [])
        one = ConsultationDraft([FollowUpQuestion("q1", "A?")])
        self.assertEqual(len(one.follow_up_questions), 1)
        two = ConsultationDraft(
            [FollowUpQuestion("q1", "A?"), FollowUpQuestion("q2", "B?")]
        )
        self.assertEqual(len(two.follow_up_questions), 2)

    def test_three_questions_rejected(self) -> None:
        with self.assertRaises(ModelError):
            ConsultationDraft(
                [
                    FollowUpQuestion("q1", "A?"),
                    FollowUpQuestion("q2", "B?"),
                    FollowUpQuestion("q1", "C?"),
                ]
            )

    def test_duplicate_ids_rejected(self) -> None:
        with self.assertRaises(ModelError):
            ConsultationDraft(
                [FollowUpQuestion("q1", "A?"), FollowUpQuestion("q1", "B?")]
            )

    def test_from_dict_with_strings_and_missing_ids(self) -> None:
        draft = ConsultationDraft.from_dict(
            {"follow_up_questions": [{"id": "q1", "question": "A?"}, "B?"]}
        )
        self.assertEqual([q.id for q in draft.follow_up_questions], ["q1", "q2"])
        self.assertEqual(draft.follow_up_questions[1].question, "B?")

    def test_from_dict_empty(self) -> None:
        self.assertEqual(
            ConsultationDraft.from_dict({}).follow_up_questions, []
        )
        self.assertEqual(
            ConsultationDraft.from_dict({"follow_up_questions": None}).follow_up_questions,
            [],
        )

    def test_from_dict_does_not_truncate(self) -> None:
        with self.assertRaises(ModelError):
            ConsultationDraft.from_dict(
                {
                    "follow_up_questions": [
                        {"question": "A?"},
                        {"question": "B?"},
                        {"question": "C?"},
                    ]
                }
            )

    def test_from_dict_invalid_id_rejected(self) -> None:
        with self.assertRaises(ModelError):
            ConsultationDraft.from_dict(
                {"follow_up_questions": [{"id": "q3", "question": "A?"}]}
            )

    def test_from_dict_invalid_shape(self) -> None:
        with self.assertRaises(ModelError):
            ConsultationDraft.from_dict("not a dict")  # type: ignore[arg-type]
        with self.assertRaises(ModelError):
            ConsultationDraft.from_dict({"follow_up_questions": "oops"})
        with self.assertRaises(ModelError):
            ConsultationDraft.from_dict({"follow_up_questions": [42]})

    def test_activity_suggestions_are_validated(self) -> None:
        suggestion = ActivitySuggestion(
            "Sleep", ActivityCategory.REST_PERIOD, "作息规律"
        )
        draft = ConsultationDraft(activity_suggestions=[suggestion])
        self.assertEqual(draft.activity_suggestions, [suggestion])
        with self.assertRaises(ModelError):
            ConsultationDraft(activity_suggestions=["nope"])  # type: ignore[list-item]

    def test_from_dict_parses_activity_suggestions(self) -> None:
        draft = ConsultationDraft.from_dict(
            {
                "activity_suggestions": [
                    {
                        "activity_name": " Morning run ",
                        "suggested_category": "predictable_routine",
                        "reason": " 每天晨跑 ",
                        "source_task_id": "t1",
                    },
                    {
                        "activity_name": "Sleep",
                        "suggested_category": "rest_period",
                        "reason": "固定作息",
                    },
                ]
            }
        )
        self.assertEqual(draft.follow_up_questions, [])
        self.assertEqual(len(draft.activity_suggestions), 2)
        first = draft.activity_suggestions[0]
        self.assertEqual(first.activity_name, "Morning run")
        self.assertIs(first.suggested_category, ActivityCategory.PREDICTABLE_ROUTINE)
        self.assertEqual(first.reason, "每天晨跑")
        self.assertIsNone(draft.activity_suggestions[1].source_task_id)

    def test_from_dict_defaults_activity_suggestions(self) -> None:
        self.assertEqual(ConsultationDraft.from_dict({}).activity_suggestions, [])
        self.assertEqual(
            ConsultationDraft.from_dict(
                {"activity_suggestions": None}
            ).activity_suggestions,
            [],
        )

    def test_from_dict_rejects_bad_activity_suggestions(self) -> None:
        payloads = [
            {"activity_suggestions": "oops"},
            {"activity_suggestions": [42]},
            {
                "activity_suggestions": [
                    {
                        "activity_name": "x",
                        "suggested_category": "unknown",
                        "reason": "y",
                    }
                ]
            },
            {
                "activity_suggestions": [
                    {
                        "activity_name": "",
                        "suggested_category": "rest_period",
                        "reason": "y",
                    }
                ]
            },
        ]
        for payload in payloads:
            with self.assertRaises(ModelError, msg=f"bad payload: {payload!r}"):
                ConsultationDraft.from_dict(payload)


class UserProfileTests(unittest.TestCase):
    def test_defaults(self) -> None:
        profile = UserProfile()
        self.assertEqual(profile.summary, "")
        self.assertEqual(profile.goals, [])
        self.assertEqual(profile.recommended_work_block_minutes, 50)
        self.assertFalse(profile.is_fallback)

    def test_work_block_bounds(self) -> None:
        UserProfile(recommended_work_block_minutes=15)
        UserProfile(recommended_work_block_minutes=180)
        for bad in (14, 181):
            with self.assertRaises(ModelError, msg=f"bad block: {bad}"):
                UserProfile(recommended_work_block_minutes=bad)

    def test_invalid_types(self) -> None:
        with self.assertRaises(ModelError):
            UserProfile(goals="not a list")  # type: ignore[arg-type]
        with self.assertRaises(ModelError):
            UserProfile(is_fallback="yes")  # type: ignore[arg-type]
        with self.assertRaises(ModelError):
            UserProfile(recommended_work_block_minutes=True)  # type: ignore[arg-type]

    def test_from_dict_full(self) -> None:
        profile = UserProfile.from_dict(
            {
                "summary": " A focused student. ",
                "goals": [" Pass finals ", "Sleep more"],
                "work_style": "Deep worker",
                "preferences": ["Morning study"],
                "recommended_work_block_minutes": 45,
                "break_preferences": "5 minutes every 45",
                "scheduling_notes": "Avoid late nights",
                "is_fallback": True,
            }
        )
        self.assertEqual(profile.summary, "A focused student.")
        self.assertEqual(profile.goals, ["Pass finals", "Sleep more"])
        self.assertEqual(profile.recommended_work_block_minutes, 45)
        self.assertTrue(profile.is_fallback)

    def test_from_dict_defaults_and_single_string_lists(self) -> None:
        profile = UserProfile.from_dict({})
        self.assertEqual(profile.recommended_work_block_minutes, 50)
        self.assertFalse(profile.is_fallback)
        self.assertEqual(
            UserProfile.from_dict({"goals": "Pass finals"}).goals,
            ["Pass finals"],
        )

    def test_from_dict_accepts_numeric_string_block(self) -> None:
        self.assertEqual(
            UserProfile.from_dict(
                {"recommended_work_block_minutes": "45"}
            ).recommended_work_block_minutes,
            45,
        )

    def test_from_dict_does_not_silently_clamp(self) -> None:
        with self.assertRaises(ModelError):
            UserProfile.from_dict({"recommended_work_block_minutes": 5})
        with self.assertRaises(ModelError):
            UserProfile.from_dict({"recommended_work_block_minutes": 999})

    def test_from_dict_invalid_types(self) -> None:
        with self.assertRaises(ModelError):
            UserProfile.from_dict("not a dict")  # type: ignore[arg-type]
        with self.assertRaises(ModelError):
            UserProfile.from_dict({"summary": 123})
        with self.assertRaises(ModelError):
            UserProfile.from_dict({"goals": 123})
        with self.assertRaises(ModelError):
            UserProfile.from_dict({"recommended_work_block_minutes": True})

    def test_from_dict_ignores_unknown_keys(self) -> None:
        profile = UserProfile.from_dict({"summary": "Hi", "unknown": "ignored"})
        self.assertEqual(profile.summary, "Hi")


class QuestionnaireDataTests(unittest.TestCase):
    def test_defaults(self) -> None:
        questionnaire = QuestionnaireData()
        self.assertEqual(questionnaire.goals, [])
        self.assertEqual(questionnaire.work_days, [0, 1, 2, 3, 4, 5, 6])
        self.assertEqual(questionnaire.energy_peak, "unknown")
        self.assertEqual(questionnaire.work_window, (time(9, 0), time(22, 0)))
        self.assertEqual(questionnaire.week_start, monday_of(date.today()))

    def test_rest_periods_are_validated(self) -> None:
        period = RestPeriod("Sleep", [0, 1], "23:00", "07:00")
        questionnaire = QuestionnaireData(rest_periods=[period])
        self.assertEqual(questionnaire.rest_periods, [period])
        self.assertEqual(QuestionnaireData().rest_periods, [])
        with self.assertRaises(ModelError):
            QuestionnaireData(rest_periods=["sleep"])  # type: ignore[list-item]

    def test_normalizes_questionnaire_fields(self) -> None:
        questionnaire = QuestionnaireData(
            name="  Alice ",
            goals=["  Pass finals ", "", "Sleep more"],
            habits=["sleep early"],
            challenges=["procrastination"],
            energy_peak="Morning",
            preferred_work_start="08:30",
            preferred_work_end="21:00",
            work_days=[5, 1, 1],
        )
        self.assertEqual(questionnaire.name, "Alice")
        self.assertEqual(questionnaire.goals, ["Pass finals", "Sleep more"])
        self.assertEqual(questionnaire.habits, ["sleep early"])
        self.assertEqual(questionnaire.challenges, ["procrastination"])
        self.assertEqual(questionnaire.energy_peak, "morning")
        self.assertEqual(questionnaire.preferred_work_start, "08:30")
        self.assertEqual(questionnaire.work_days, [1, 5])
        self.assertEqual(questionnaire.work_window, (time(8, 30), time(21, 0)))

    def test_task_ids_auto_assigned(self) -> None:
        first = TaskInput("A", 30)
        second = TaskInput("B", 30)
        questionnaire = QuestionnaireData(tasks=[first, second])
        self.assertEqual([task.id for task in questionnaire.tasks], ["t1", "t2"])
        self.assertIs(questionnaire.tasks[0], first)

    def test_auto_id_skips_explicit_ids(self) -> None:
        explicit = TaskInput("A", 30, id="t1")
        automatic = TaskInput("B", 30)
        questionnaire = QuestionnaireData(tasks=[automatic, explicit])
        self.assertEqual(automatic.id, "t2")
        self.assertEqual([task.id for task in questionnaire.tasks], ["t2", "t1"])

    def test_explicit_duplicate_task_ids_rejected(self) -> None:
        with self.assertRaises(ModelError):
            QuestionnaireData(
                tasks=[
                    TaskInput("A", 30, id="custom"),
                    TaskInput("B", 30, id="custom"),
                ]
            )

    def test_week_start_normalized_to_monday(self) -> None:
        questionnaire = QuestionnaireData(week_start=date(2026, 11, 22))
        self.assertEqual(questionnaire.week_start, date(2026, 11, 16))
        with self.assertRaises(ModelError):
            QuestionnaireData(week_start=at(23))  # type: ignore[arg-type]

    def test_work_window_validation(self) -> None:
        for start, end in [
            ("9:00", "22:00"),
            ("22:00", "09:00"),
            ("09:00", "09:00"),
            ("24:00", "25:00"),
            (900, "22:00"),
        ]:
            with self.assertRaises(ModelError, msg=f"{start!r} ~ {end!r}"):
                QuestionnaireData(
                    preferred_work_start=start,  # type: ignore[arg-type]
                    preferred_work_end=end,  # type: ignore[arg-type]
                )

    def test_work_days_validation(self) -> None:
        for bad in ([0, 7], [-1], [True], ["1"]):
            with self.assertRaises(ModelError, msg=f"bad work_days: {bad!r}"):
                QuestionnaireData(work_days=bad)  # type: ignore[arg-type]
        self.assertEqual(QuestionnaireData(work_days=[]).work_days, [])

    def test_energy_peak_validation(self) -> None:
        for valid in sorted(ENERGY_PEAKS):
            self.assertEqual(QuestionnaireData(energy_peak=valid).energy_peak, valid)
        with self.assertRaises(ModelError):
            QuestionnaireData(energy_peak="night")

    def test_invalid_types(self) -> None:
        with self.assertRaises(ModelError):
            QuestionnaireData(habits="not a list")  # type: ignore[arg-type]
        with self.assertRaises(ModelError):
            QuestionnaireData(challenges=None)  # type: ignore[arg-type]
        with self.assertRaises(ModelError):
            QuestionnaireData(tasks=["not a task"])  # type: ignore[list-item]
        with self.assertRaises(ModelError):
            QuestionnaireData(fixed_commitments=["not a commitment"])  # type: ignore[list-item]
        with self.assertRaises(ModelError):
            QuestionnaireData(name=None)  # type: ignore[arg-type]

    def test_accepts_tuple_of_tasks(self) -> None:
        questionnaire = QuestionnaireData(tasks=(TaskInput("A", 30),))  # type: ignore[arg-type]
        self.assertIsInstance(questionnaire.tasks, list)


class ScheduledItemTests(unittest.TestCase):
    def test_valid_item(self) -> None:
        task = TaskInput("A", 60, id="t1")
        item = ScheduledItem(task, at(23, 9), at(23, 10))
        self.assertEqual(item.task_id, "t1")
        self.assertEqual(item.duration_minutes, 60)
        self.assertFalse(item.completed)
        self.assertIs(item.task, task)

    def test_preferred_window_satisfied_is_none_without_preferences(self) -> None:
        item = ScheduledItem(TaskInput("A", 60), at(23, 9), at(23, 10))
        self.assertIsNone(item.preferred_window_satisfied)

    def test_preferred_window_satisfied_time_window(self) -> None:
        task = TaskInput("A", 60, preferred_start="09:00", preferred_end="11:00")
        self.assertTrue(
            ScheduledItem(task, at(23, 9), at(23, 10)).preferred_window_satisfied
        )
        self.assertFalse(
            ScheduledItem(task, at(23, 8), at(23, 9)).preferred_window_satisfied
        )
        self.assertFalse(
            ScheduledItem(task, at(23, 10, 30), at(23, 11, 30)).preferred_window_satisfied
        )

    def test_preferred_window_satisfied_end_at_boundary(self) -> None:
        task = TaskInput("A", 60, preferred_start="09:00", preferred_end="10:00")
        self.assertTrue(
            ScheduledItem(task, at(23, 9), at(23, 10)).preferred_window_satisfied
        )

    def test_preferred_window_satisfied_weekdays(self) -> None:
        task = TaskInput("A", 60, preferred_days=[1])  # 星期二
        self.assertTrue(
            ScheduledItem(task, at(24, 9), at(24, 10)).preferred_window_satisfied
        )
        self.assertFalse(
            ScheduledItem(task, at(23, 9), at(23, 10)).preferred_window_satisfied
        )

    def test_end_must_be_later_than_start(self) -> None:
        task = TaskInput("A", 60)
        with self.assertRaises(ModelError):
            ScheduledItem(task, at(23, 10), at(23, 9))
        with self.assertRaises(ModelError):
            ScheduledItem(task, at(23, 10), at(23, 10))

    def test_invalid_types(self) -> None:
        with self.assertRaises(ModelError):
            ScheduledItem("task", at(23, 9), at(23, 10))  # type: ignore[arg-type]
        with self.assertRaises(ModelError):
            ScheduledItem(TaskInput("A", 60), date(2026, 11, 23), at(23, 10))  # type: ignore[arg-type]
        with self.assertRaises(ModelError):
            ScheduledItem(TaskInput("A", 60), at(23, 9), at(23, 10), completed="yes")  # type: ignore[arg-type]


class UnscheduledTaskTests(unittest.TestCase):
    def test_valid_unscheduled_task(self) -> None:
        task = TaskInput("A", 60, id="t1")
        unscheduled = UnscheduledTask(task, "本周剩余时间不足")
        self.assertIs(unscheduled.task, task)
        self.assertEqual(unscheduled.reason, "本周剩余时间不足")

    def test_reason_is_required(self) -> None:
        with self.assertRaises(ModelError):
            UnscheduledTask(TaskInput("A", 60), "   ")

    def test_is_immutable(self) -> None:
        unscheduled = UnscheduledTask(TaskInput("A", 60), "no slot")
        with self.assertRaises(FrozenInstanceError):
            unscheduled.reason = "changed"  # type: ignore[misc]


class ScheduleResultTests(unittest.TestCase):
    def test_items_are_sorted_and_week_start_normalized(self) -> None:
        early = ScheduledItem(TaskInput("A", 60, id="t1"), at(23, 9), at(23, 10))
        late = ScheduledItem(TaskInput("B", 60, id="t2"), at(23, 14), at(23, 15))
        result = ScheduleResult(week_start=date(2026, 11, 29), items=[late, early])
        self.assertEqual([item.task.id for item in result.items], ["t1", "t2"])
        self.assertEqual(result.week_start, date(2026, 11, 23))
        self.assertEqual(result.total_scheduled_minutes, 120)

    def test_items_on(self) -> None:
        monday_item = ScheduledItem(TaskInput("A", 30, id="t1"), at(23, 9), at(23, 10))
        tuesday_item = ScheduledItem(TaskInput("B", 30, id="t2"), at(24, 9), at(24, 10))
        result = ScheduleResult(
            week_start=date(2026, 11, 23), items=[monday_item, tuesday_item]
        )
        self.assertEqual(result.items_on(date(2026, 11, 23)), [monday_item])
        self.assertEqual(result.items_on(date(2026, 11, 24)), [tuesday_item])
        self.assertEqual(result.items_on(date(2026, 11, 25)), [])
        with self.assertRaises(ModelError):
            result.items_on(at(23))  # type: ignore[arg-type]

    def test_unscheduled_and_warnings(self) -> None:
        task = TaskInput("A", 60, id="t1")
        unscheduled = UnscheduledTask(task, "no slot")
        result = ScheduleResult(
            week_start=date(2026, 11, 23),
            unscheduled_tasks=[unscheduled],
            warnings=["  deadline missed  ", ""],
        )
        self.assertEqual(result.unscheduled_tasks, [unscheduled])
        self.assertEqual(result.warnings, ["deadline missed"])
        self.assertTrue(result.is_empty)

    def test_invalid_types(self) -> None:
        with self.assertRaises(ModelError):
            ScheduleResult(week_start=at(23))  # type: ignore[arg-type]
        with self.assertRaises(ModelError):
            ScheduleResult(week_start=date(2026, 11, 23), items=["oops"])  # type: ignore[list-item]


class PackageExportTests(unittest.TestCase):
    def test_core_package_exports_models(self) -> None:
        import core

        self.assertIs(core.TaskInput, TaskInput)
        self.assertIs(core.QuestionnaireData, QuestionnaireData)
        self.assertIs(core.ModelError, ModelError)
        self.assertIs(core.DurationType, DurationType)
        self.assertIs(core.RestPeriod, RestPeriod)
        self.assertIs(core.ActivityCategory, ActivityCategory)
        self.assertIs(core.ActivitySuggestion, ActivitySuggestion)


if __name__ == "__main__":
    unittest.main()
