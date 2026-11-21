"""Tests for ``core.ai_consultant`` (Core Models V1.1).

A fake client stands in for ``DeepSeekClient`` so every path - success,
sloppy payload, transport failure - is exercised without a network call.

The suites map onto the V1.1 requirements:

* ``DraftShapeTests``           - both draft keys always present.
* ``QuestionPriorityTests``     - P0 asked before P3, cap applied after sorting.
* ``NoRepeatTests``             - nothing the user already answered is re-asked.
* ``ActivitySuggestionTests``   - four-category classification and parsing.
* ``MedicationGuardTests``      - timings are never invented for medication.
* ``ConfirmationBoundaryTests`` - suggestions never become facts.
* ``FinalizeProfileTests``      - eight-field profile, fallback on failure.
* ``ContractShapeTests``        - category vocabulary and nested task objects.
"""

from __future__ import annotations

import dataclasses
import unittest
from enum import Enum

from core import ai_consultant
from core.ai_client import AINetworkError


class FakeClient:
    """Minimal stand-in for DeepSeekClient."""

    def __init__(self, payload=None, error=None):
        self.payload = payload
        self.error = error
        self.call_count = 0

    def chat_json(self, messages, **kwargs):
        self.call_count += 1
        if self.error is not None:
            raise self.error
        return self.payload


class CapturingClient(FakeClient):
    """FakeClient that also records the messages it was given."""

    def __init__(self, payload=None, error=None):
        super().__init__(payload=payload, error=error)
        self.messages = []

    def chat_json(self, messages, **kwargs):
        self.messages.append(messages)
        return super().chat_json(messages, **kwargs)


QUESTIONNAIRE = {
    "goals": ["Finish the thesis"],
    "tasks": ["Read three papers"],
    "fixed_commitments": ["Wed 14:00 lecture"],
    "preferred_work_hours": ["morning"],
    "work_style": "Prefers short focused sessions",
    "preferences": ["Quiet room"],
}

# Only one field filled, so individual fields can be tested as "missing"
# without the repeated-question rule interfering.
SPARSE_QUESTIONNAIRE = {"goals": ["Pass calculus"]}

FULL_PROFILE_PAYLOAD = {
    "summary": "A focused student.",
    "goals": ["Finish the thesis"],
    "work_style": "Short sessions",
    "preferences": ["Quiet room"],
    "recommended_work_block_minutes": 45,
    "break_preferences": ["Tea"],
    "scheduling_notes": "Avoid Wednesday afternoon.",
}


# ---------------------------------------------------------------------------
# Draft shape
# ---------------------------------------------------------------------------


class DraftShapeTests(unittest.TestCase):
    def test_draft_always_carries_both_keys(self):
        client = FakeClient({"follow_up_questions": [], "activity_suggestions": []})
        draft = ai_consultant.start_consultation(QUESTIONNAIRE, client=client)

        self.assertEqual(set(draft.keys()), set(ai_consultant.DRAFT_KEYS))

    def test_question_objects_carry_id_and_text_only(self):
        client = FakeClient(
            {
                "follow_up_questions": [
                    {"id": "q1", "question": "Which deadline is closest?"}
                ]
            }
        )
        draft = ai_consultant.start_consultation(QUESTIONNAIRE, client=client)

        self.assertEqual(
            draft["follow_up_questions"],
            [{"id": "q1", "question": "Which deadline is closest?"}],
        )

    def test_bare_strings_are_accepted_and_ided(self):
        client = FakeClient({"follow_up_questions": ["First?", "Second?"]})
        draft = ai_consultant.start_consultation(QUESTIONNAIRE, client=client)

        self.assertEqual(
            [item["id"] for item in draft["follow_up_questions"]], ["q1", "q2"]
        )

    def test_model_supplied_ids_are_replaced(self):
        client = FakeClient({"follow_up_questions": [{"id": "zzz", "question": "A?"}]})
        draft = ai_consultant.start_consultation(QUESTIONNAIRE, client=client)

        self.assertEqual(draft["follow_up_questions"][0]["id"], "q1")

    def test_never_returns_more_than_two(self):
        client = FakeClient({"follow_up_questions": ["a", "b", "c", "d"]})
        draft = ai_consultant.start_consultation(QUESTIONNAIRE, client=client)

        self.assertEqual(len(draft["follow_up_questions"]), 2)

    def test_blank_questions_are_dropped(self):
        client = FakeClient(
            {"follow_up_questions": [{"id": "q1", "question": "   "}, "Real?"]}
        )
        draft = ai_consultant.start_consultation(QUESTIONNAIRE, client=client)

        self.assertEqual(
            draft["follow_up_questions"], [{"id": "q1", "question": "Real?"}]
        )

    def test_non_list_questions_are_ignored(self):
        client = FakeClient({"follow_up_questions": 123})
        draft = ai_consultant.start_consultation(QUESTIONNAIRE, client=client)

        self.assertEqual(draft["follow_up_questions"], [])

    def test_api_failure_returns_empty_draft(self):
        client = FakeClient(error=AINetworkError("service down"))
        draft = ai_consultant.start_consultation(QUESTIONNAIRE, client=client)

        self.assertEqual(
            draft, {"follow_up_questions": [], "activity_suggestions": []}
        )

    def test_payload_that_is_not_a_mapping_is_survivable(self):
        client = FakeClient(payload="not a mapping")
        draft = ai_consultant.start_consultation(QUESTIONNAIRE, client=client)

        self.assertEqual(
            draft, {"follow_up_questions": [], "activity_suggestions": []}
        )


# ---------------------------------------------------------------------------
# Question priority
# ---------------------------------------------------------------------------


class QuestionPriorityTests(unittest.TestCase):
    def _ask(self, questions, questionnaire=None):
        client = FakeClient({"follow_up_questions": questions})
        draft = ai_consultant.start_consultation(
            questionnaire or SPARSE_QUESTIONNAIRE, client=client
        )
        return [item["question"] for item in draft["follow_up_questions"]]

    def test_p0_sorts_before_p2(self):
        questions = [
            {"question": "What time do you usually eat lunch?", "priority": "P2"},
            {"question": "What time is your physics class?", "priority": "P0"},
        ]
        self.assertEqual(
            self._ask(questions),
            ["What time is your physics class?", "What time do you usually eat lunch?"],
        )

    def test_higher_priority_displaces_lower_when_slots_are_full(self):
        questions = [
            {"question": "How long can you focus?", "priority": "P3"},
            {"question": "What time is your physics class?", "priority": "P0"},
            {"question": "When do you sleep?", "priority": "P1"},
            {"question": "When do you do laundry?", "priority": "P2"},
        ]
        self.assertEqual(
            self._ask(questions),
            ["What time is your physics class?", "When do you sleep?"],
        )

    def test_missing_priority_loses_to_a_real_one(self):
        questions = [
            {"question": "Something vague?"},
            {"question": "What time is your physics class?", "priority": "P0"},
        ]
        self.assertEqual(
            self._ask(questions),
            ["What time is your physics class?", "Something vague?"],
        )

    def test_ids_follow_the_sorted_order(self):
        client = FakeClient(
            {
                "follow_up_questions": [
                    {"question": "Low?", "priority": "P3"},
                    {"question": "High?", "priority": "P0"},
                ]
            }
        )
        draft = ai_consultant.start_consultation(SPARSE_QUESTIONNAIRE, client=client)

        self.assertEqual(
            [(item["id"], item["question"]) for item in draft["follow_up_questions"]],
            [("q1", "High?"), ("q2", "Low?")],
        )

    def test_verbose_priority_labels_are_understood(self):
        self.assertEqual(
            ai_consultant._normalise_priority("P0 - hard commitments"), "P0"
        )
        self.assertEqual(ai_consultant._normalise_priority("priority 2"), "P2")
        self.assertEqual(ai_consultant._normalise_priority("p1"), "P1")
        self.assertEqual(ai_consultant._normalise_priority(None), "P3")
        self.assertEqual(ai_consultant._normalise_priority("nonsense"), "P3")

    def test_priority_order_constant_is_ordered(self):
        self.assertEqual(ai_consultant.QUESTION_PRIORITIES, ("P0", "P1", "P2", "P3"))


# ---------------------------------------------------------------------------
# No repeated questions
# ---------------------------------------------------------------------------


class NoRepeatTests(unittest.TestCase):
    def test_question_targeting_an_answered_field_is_dropped(self):
        client = FakeClient(
            {
                "follow_up_questions": [
                    {
                        "question": "What are your fixed commitments?",
                        "priority": "P0",
                        "target_field": "fixed_commitments",
                    }
                ]
            }
        )
        draft = ai_consultant.start_consultation(QUESTIONNAIRE, client=client)

        self.assertEqual(draft["follow_up_questions"], [])

    def test_question_targeting_a_missing_field_is_kept(self):
        client = FakeClient(
            {
                "follow_up_questions": [
                    {
                        "question": "What time is your physics class?",
                        "priority": "P0",
                        "target_field": "fixed_commitments",
                    }
                ]
            }
        )
        draft = ai_consultant.start_consultation(SPARSE_QUESTIONNAIRE, client=client)

        self.assertEqual(len(draft["follow_up_questions"]), 1)

    def test_duplicate_wording_is_collapsed(self):
        client = FakeClient(
            {
                "follow_up_questions": [
                    {"question": "How long can you focus?", "priority": "P3"},
                    {"question": "How long can you focus", "priority": "P3"},
                ]
            }
        )
        draft = ai_consultant.start_consultation(SPARSE_QUESTIONNAIRE, client=client)

        self.assertEqual(len(draft["follow_up_questions"]), 1)

    def test_blank_field_values_do_not_count_as_answered(self):
        client = FakeClient(
            {
                "follow_up_questions": [
                    {
                        "question": "What are your fixed commitments?",
                        "priority": "P0",
                        "target_field": "fixed_commitments",
                    }
                ]
            }
        )
        draft = ai_consultant.start_consultation(
            {"fixed_commitments": ["  ", ""]}, client=client
        )

        self.assertEqual(len(draft["follow_up_questions"]), 1)


# ---------------------------------------------------------------------------
# Activity suggestions
# ---------------------------------------------------------------------------


class ActivitySuggestionTests(unittest.TestCase):
    def _suggest(self, activities, questionnaire=None):
        client = FakeClient({"activity_suggestions": activities})
        draft = ai_consultant.start_consultation(
            questionnaire or SPARSE_QUESTIONNAIRE, client=client
        )
        return draft["activity_suggestions"]

    def test_all_four_categories_are_preserved(self):
        for category in ai_consultant.ACTIVITY_CATEGORIES:
            with self.subTest(category=category):
                result = self._suggest(
                    [
                        {
                            "activity_name": "Physics class",
                            "suggested_category": category,
                            "reason": "Mentioned in the questionnaire",
                        }
                    ]
                )
                self.assertEqual(result[0]["suggested_category"], category)

    def test_unknown_category_is_discarded(self):
        result = self._suggest(
            [
                {
                    "activity_name": "Physics class",
                    "suggested_category": "SOMETHING_ELSE",
                    "reason": "x",
                }
            ]
        )

        self.assertEqual(result, [])

    def test_short_aliases_are_normalised(self):
        result = self._suggest(
            [{"activity_name": "Sleep", "suggested_category": "rest", "reason": "x"}]
        )

        self.assertEqual(result[0]["suggested_category"], "rest_period")

    def test_shouty_and_spaced_variants_are_tolerated(self):
        result = self._suggest(
            [
                {
                    "activity_name": "Physics class",
                    "suggested_category": "HARD-COMMITMENT",
                    "reason": "x",
                }
            ]
        )

        self.assertEqual(result[0]["suggested_category"], "hard_commitment")

    def test_full_suggestion_shape(self):
        result = self._suggest(
            [
                {
                    "activity_name": "Study calculus",
                    "suggested_category": "uncertain_task",
                    "reason": "Goal without a fixed slot",
                    "source_task_id": "task-3",
                }
            ]
        )

        self.assertEqual(
            result,
            [
                {
                    "activity_name": "Study calculus",
                    "suggested_category": "uncertain_task",
                    "reason": "Goal without a fixed slot",
                    "source_task_id": "task-3",
                }
            ],
        )

    def test_source_task_id_is_omitted_when_absent(self):
        result = self._suggest(
            [{"activity_name": "Lunch", "suggested_category": "predictable_routine"}]
        )

        self.assertNotIn("source_task_id", result[0])
        self.assertEqual(result[0]["reason"], "")

    def test_duplicate_names_are_collapsed(self):
        result = self._suggest(
            [
                {"activity_name": "Lunch", "suggested_category": "predictable_routine"},
                {"activity_name": "lunch", "suggested_category": "predictable_routine"},
            ]
        )

        self.assertEqual(len(result), 1)

    def test_same_name_different_category_is_kept(self):
        result = self._suggest(
            [
                {"activity_name": "Reading", "suggested_category": "rest_period"},
                {"activity_name": "Reading", "suggested_category": "uncertain_task"},
            ]
        )

        self.assertEqual(len(result), 2)

    def test_activity_without_a_name_is_dropped(self):
        result = self._suggest([{"suggested_category": "rest_period", "reason": "x"}])

        self.assertEqual(result, [])

    def test_non_list_payload_yields_empty(self):
        self.assertEqual(self._suggest("nope"), [])

    def test_suggestions_are_capped(self):
        activities = [
            {"activity_name": f"Activity {index}", "suggested_category": "rest_period"}
            for index in range(20)
        ]

        self.assertEqual(len(self._suggest(activities)), ai_consultant.MAX_ACTIVITY_SUGGESTIONS)

    def test_unknown_category_word_is_not_reclassified(self):
        # A wrong category must remove the item, not silently reclassify it
        # into something the scheduler would then trust.
        result = self._suggest(
            [{"activity_name": "Thesis", "suggested_category": "goal", "reason": "x"}]
        )

        self.assertEqual(result, [])


# ---------------------------------------------------------------------------
# Medication timing guard
# ---------------------------------------------------------------------------


class MedicationGuardTests(unittest.TestCase):
    def _suggest_reason(self, name, reason, questionnaire=None):
        client = FakeClient(
            {
                "activity_suggestions": [
                    {
                        "activity_name": name,
                        "suggested_category": "rest_period",
                        "reason": reason,
                    }
                ]
            }
        )
        draft = ai_consultant.start_consultation(
            questionnaire or {"goals": ["Stay healthy"]}, client=client
        )
        return draft["activity_suggestions"][0]["reason"]

    def test_invented_time_is_scrubbed(self):
        reason = self._suggest_reason(
            "Blood pressure medication", "Take one tablet at 08:00 and 20:00."
        )

        self.assertNotIn("08:00", reason)
        self.assertNotIn("20:00", reason)
        self.assertIn("a time you confirm", reason)

    def test_user_supplied_time_is_kept(self):
        reason = self._suggest_reason(
            "Blood pressure medication",
            "Take one tablet at 08:00.",
            questionnaire={"fixed_commitments": ["Medication at 08:00 every day"]},
        )

        self.assertIn("08:00", reason)

    def test_non_medication_reasons_are_untouched(self):
        reason = self._suggest_reason("Lunch", "Eat at 12:30.", questionnaire={})

        self.assertEqual(reason, "Eat at 12:30.")

    def test_chinese_medication_keyword_is_recognised(self):
        reason = self._suggest_reason("吃药", "每天 08:00 服用", questionnaire={})

        self.assertNotIn("08:00", reason)


# ---------------------------------------------------------------------------
# Confirmation boundary
# ---------------------------------------------------------------------------


class ConfirmationBoundaryTests(unittest.TestCase):
    def test_profile_prompt_never_contains_suggestions(self):
        client = CapturingClient(payload=FULL_PROFILE_PAYLOAD)
        contaminated = dict(
            QUESTIONNAIRE,
            activity_suggestions=[
                {
                    "activity_name": "Study Calculus",
                    "suggested_category": "uncertain_task",
                    "reason": "Guessed from goals",
                }
            ],
        )

        ai_consultant.finalize_profile(contaminated, {}, client=client)

        prompt = client.messages[0][-1]["content"]
        self.assertNotIn("Study Calculus", prompt)
        self.assertNotIn("suggested_category", prompt)

    def test_follow_up_questions_are_stripped_from_profile_input(self):
        client = CapturingClient(payload=FULL_PROFILE_PAYLOAD)
        contaminated = dict(
            QUESTIONNAIRE,
            follow_up_questions=[{"id": "q1", "question": "Secret question?"}],
        )

        ai_consultant.finalize_profile(contaminated, {}, client=client)

        self.assertNotIn("Secret question?", client.messages[0][-1]["content"])

    def test_fallback_ignores_suggestions(self):
        contaminated = dict(
            QUESTIONNAIRE,
            activity_suggestions=[
                {
                    "activity_name": "Study Calculus",
                    "suggested_category": "uncertain_task",
                    "reason": "Guessed",
                }
            ],
        )

        profile = ai_consultant.build_fallback_profile(contaminated)

        self.assertNotIn("Study Calculus", str(profile))

    def test_confirmed_questionnaire_keyword_is_accepted(self):
        client = FakeClient(FULL_PROFILE_PAYLOAD)
        profile = ai_consultant.finalize_profile(
            confirmed_questionnaire=QUESTIONNAIRE, follow_up_answers={}, client=client
        )

        self.assertFalse(profile["is_fallback"])
        self.assertEqual(profile["goals"], ["Finish the thesis"])


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------


class FinalizeProfileTests(unittest.TestCase):
    def test_normalises_full_payload(self):
        profile = ai_consultant.finalize_profile(
            QUESTIONNAIRE, {}, client=FakeClient(FULL_PROFILE_PAYLOAD)
        )

        for key in ai_consultant.PROFILE_KEYS:
            self.assertIn(key, profile)
        self.assertEqual(profile["recommended_work_block_minutes"], 45)
        self.assertFalse(profile["is_fallback"])

    def test_profile_has_exactly_eight_fields(self):
        profile = ai_consultant.finalize_profile(
            QUESTIONNAIRE, {}, client=FakeClient(FULL_PROFILE_PAYLOAD)
        )

        self.assertEqual(set(profile.keys()), set(ai_consultant.PROFILE_KEYS))
        self.assertEqual(len(ai_consultant.PROFILE_KEYS), 8)

    def test_fixed_commitments_never_leak(self):
        payload = dict(FULL_PROFILE_PAYLOAD, fixed_commitments=["Wed 14:00 lecture"])
        profile = ai_consultant.finalize_profile(
            QUESTIONNAIRE, {}, client=FakeClient(payload)
        )

        self.assertNotIn("fixed_commitments", profile)

    def test_out_of_range_block_falls_back_to_default(self):
        payload = {"recommended_work_block_minutes": 999}
        profile = ai_consultant.finalize_profile(
            QUESTIONNAIRE, {}, client=FakeClient(payload)
        )

        self.assertEqual(
            profile["recommended_work_block_minutes"],
            ai_consultant.DEFAULT_WORK_BLOCK_MINUTES,
        )

    def test_malformed_payload_still_yields_full_shape(self):
        profile = ai_consultant.finalize_profile(
            QUESTIONNAIRE, {}, client=FakeClient("not a mapping")
        )

        for key in ai_consultant.PROFILE_KEYS:
            self.assertIn(key, profile)

    def test_api_failure_degrades_to_fallback(self):
        client = FakeClient(error=AINetworkError("service down"))
        profile = ai_consultant.finalize_profile(QUESTIONNAIRE, {}, client=client)

        self.assertTrue(profile["is_fallback"])
        self.assertEqual(profile["goals"], ["Finish the thesis"])

    def test_missing_answers_are_accepted(self):
        profile = ai_consultant.finalize_profile(
            QUESTIONNAIRE, None, client=FakeClient({"summary": "x"})
        )

        self.assertFalse(profile["is_fallback"])

    def test_answers_are_keyed_by_question_id(self):
        self.assertEqual(
            ai_consultant._clean_answers({"q1": "Morning", "q2": "50 minutes"}),
            {"q1": "Morning", "q2": "50 minutes"},
        )

    def test_unknown_answer_keys_are_dropped(self):
        self.assertEqual(
            ai_consultant._clean_answers({"q1": "Morning", "q9": "junk", "q2": ""}),
            {"q1": "Morning"},
        )


class FallbackProfileTests(unittest.TestCase):
    def test_uses_only_explicit_information(self):
        profile = ai_consultant.build_fallback_profile(QUESTIONNAIRE)

        self.assertTrue(profile["is_fallback"])
        self.assertEqual(profile["goals"], ["Finish the thesis"])
        self.assertEqual(profile["work_style"], "Prefers short focused sessions")
        self.assertEqual(profile["preferences"], ["Quiet room"])

    def test_empty_questionnaire_still_returns_full_shape(self):
        profile = ai_consultant.build_fallback_profile({})

        for key in ai_consultant.PROFILE_KEYS:
            self.assertIn(key, profile)
        self.assertEqual(profile["goals"], [])
        self.assertEqual(
            profile["recommended_work_block_minutes"],
            ai_consultant.DEFAULT_WORK_BLOCK_MINUTES,
        )

    def test_default_block_is_labelled_as_default(self):
        profile = ai_consultant.build_fallback_profile(QUESTIONNAIRE)

        self.assertIn("system default", profile["scheduling_notes"])

    def test_fixed_commitments_are_not_restated(self):
        profile = ai_consultant.build_fallback_profile(QUESTIONNAIRE)

        self.assertNotIn("fixed_commitments", profile)
        self.assertIn("not modified", profile["scheduling_notes"])

    def test_none_questionnaire_is_safe(self):
        self.assertTrue(ai_consultant.build_fallback_profile(None)["is_fallback"])

    def test_deterministic_across_calls(self):
        first = ai_consultant.build_fallback_profile(QUESTIONNAIRE)
        second = ai_consultant.build_fallback_profile(QUESTIONNAIRE)

        self.assertEqual(first, second)


# ---------------------------------------------------------------------------
# Contract shape
# ---------------------------------------------------------------------------


class ContractShapeTests(unittest.TestCase):
    def test_categories_are_the_four_documented_values(self):
        self.assertEqual(
            tuple(ai_consultant.ACTIVITY_CATEGORIES),
            (
                "hard_commitment",
                "rest_period",
                "predictable_routine",
                "uncertain_task",
            ),
        )

    def test_duration_types_are_the_two_documented_values(self):
        self.assertEqual(
            tuple(ai_consultant.DURATION_TYPES), ("predictable", "uncertain")
        )

    def test_enum_value_is_accepted_as_a_category(self):
        class FakeCategory(Enum):
            HARD_COMMITMENT = "hard_commitment"

        self.assertEqual(
            ai_consultant._normalise_category(FakeCategory.HARD_COMMITMENT),
            "hard_commitment",
        )

    def test_nested_task_objects_reach_the_prompt_as_data(self):
        @dataclasses.dataclass
        class TaskInput:
            name: str
            estimated_minutes: int
            duration_type: str

        client = CapturingClient(payload=FULL_PROFILE_PAYLOAD)
        questionnaire = {
            "goals": ["Pass calculus"],
            "tasks": [
                TaskInput(
                    name="Read papers", estimated_minutes=45, duration_type="uncertain"
                )
            ],
        }

        ai_consultant.finalize_profile(questionnaire, {}, client=client)

        prompt = client.messages[0][-1]["content"]
        self.assertIn("estimated_minutes", prompt)
        self.assertIn("Read papers", prompt)
        self.assertIn("uncertain", prompt)
        self.assertNotIn("TaskInput(", prompt)

    def test_analysis_prompt_lists_lowercase_categories(self):
        client = CapturingClient(payload={"follow_up_questions": []})
        ai_consultant.start_consultation(SPARSE_QUESTIONNAIRE, client=client)

        prompt = client.messages[0][-1]["content"]
        for category in ai_consultant.ACTIVITY_CATEGORIES:
            self.assertIn(category, prompt)

    def test_analysis_prompt_states_the_priority_ladder(self):
        client = CapturingClient(payload={"follow_up_questions": []})
        ai_consultant.start_consultation(SPARSE_QUESTIONNAIRE, client=client)

        prompt = client.messages[0][-1]["content"]
        for priority in ai_consultant.QUESTION_PRIORITIES:
            self.assertIn(priority, prompt)


class HelperTests(unittest.TestCase):
    def test_as_mapping_accepts_dataclass(self):
        @dataclasses.dataclass
        class Questionnaire:
            goals: list

        result = ai_consultant._as_mapping(Questionnaire(goals=["a"]))
        self.assertEqual(result, {"goals": ["a"]})

    def test_clean_list_wraps_bare_string(self):
        self.assertEqual(ai_consultant._clean_list("single"), ["single"])

    def test_clean_list_drops_blank_entries(self):
        self.assertEqual(ai_consultant._clean_list(["a", "", "  ", None]), ["a"])

    def test_clean_list_reads_object_names(self):
        @dataclasses.dataclass
        class TaskInput:
            name: str
            estimated_minutes: int

        self.assertEqual(
            ai_consultant._clean_list([TaskInput("Read papers", 45)]),
            ["Read papers"],
        )

    def test_follow_up_ids_match_documented_keys(self):
        self.assertEqual(ai_consultant.FOLLOW_UP_IDS, ("q1", "q2"))


if __name__ == "__main__":
    unittest.main()
