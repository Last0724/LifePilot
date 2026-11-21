"""Tests for ``core.ai_consultant`` (Core Models V1.2).

A fake client stands in for ``DeepSeekClient`` so every path - success,
sloppy payload, transport failure - is exercised without a network call.

The suites map onto the V1.2 requirements:

* ``FieldStateTests``       - missing-field detection, energy_peak placeholder,
  optional fields, priority mapping.
* ``ControllerTests``       - Python-owned selection, phrasing, state
  transitions, completion, multi-round, MAX_ROUNDS, serialization.
* ``LegacyWrapperTests``    - the three backward-compatible functions.
* ``ActivitySuggestionTests`` - four-category classification and parsing.
* ``MedicationGuardTests``  - timings are never invented for medication.
* ``ConfirmationBoundaryTests`` - suggestions never become facts.
* ``FinalizeProfileTests``  - eight-field profile, V1.2 block bounds, fallback.
* ``FallbackProfileTests``  - deterministic fallback with V1.2 defaults.
* ``ContractShapeTests``    - category vocabulary and nested task objects.
* ``HelperTests``           - small coercions and answer classification.
"""

from __future__ import annotations

import dataclasses
import unittest
from enum import Enum

from core import ai_consultant
from core.ai_client import AINetworkError
from core.models import (
    ConsultationDraft,
    FollowUpQuestion,
    QuestionnaireData,
    UserProfile,
)


class FakeClient:
    """Stand-in for DeepSeekClient that returns one payload for every call."""

    def __init__(self, payload=None, error=None):
        self.payload = payload if payload is not None else {}
        self.error = error
        self.call_count = 0
        self.messages = []

    def chat_json(self, messages, **kwargs):
        self.call_count += 1
        self.messages.append(messages)
        if self.error is not None:
            raise self.error
        return self.payload


QUESTIONNAIRE = {
    "goals": ["Finish the thesis"],
    "tasks": ["Read three papers"],
    "fixed_commitments": ["Wed 14:00 lecture"],
    "work_style": "Prefers short focused sessions",
    "preferences": ["Quiet room"],
}

# Only goals filled, so every other required field is missing.
SPARSE_QUESTIONNAIRE = {"goals": ["Pass calculus"]}

FULL_QUESTIONNAIRE = {
    "goals": ["Pass calculus"],
    "tasks": ["Read papers"],
    "fixed_commitments": ["Lecture"],
    "rest_periods": ["Sleep 23:00-07:00"],
    "predictable_routines": ["Lunch"],
    "preferred_work_start": "09:00",
    "preferred_work_end": "18:00",
    "work_days": [0, 1, 2, 3, 4],
    "energy_peak": "morning",
}

# One question per required field, so the controller can be asked to phrase
# anything without the fake needing to know what was selected.
ALL_FIELD_QUESTIONS = [
    {"question": "What fixed commitments do you have?", "target_field": "fixed_commitments"},
    {"question": "When do you rest?", "target_field": "rest_periods"},
    {"question": "What routines repeat daily?", "target_field": "predictable_routines"},
    {"question": "What tasks must you do?", "target_field": "tasks"},
    {"question": "When do you start work?", "target_field": "preferred_work_start"},
    {"question": "When do you end work?", "target_field": "preferred_work_end"},
    {"question": "Which days do you work?", "target_field": "work_days"},
    {"question": "When is your energy peak?", "target_field": "energy_peak"},
    {"question": "What are your goals?", "target_field": "goals"},
]

FULL_PROFILE_PAYLOAD = {
    "summary": "A focused student.",
    "goals": ["Finish the thesis"],
    "work_style": "Short sessions",
    "preferences": ["Quiet room"],
    "recommended_work_block_minutes": 45,
    "break_preferences": "Take a short break every hour",
    "scheduling_notes": "Avoid Wednesday afternoon.",
}


def _controller(questionnaire=None, payload=None, error=None, max_rounds=ai_consultant.MAX_ROUNDS):
    return ai_consultant.ConsultationController(
        questionnaire if questionnaire is not None else SPARSE_QUESTIONNAIRE,
        client=FakeClient(payload=payload, error=error),
        max_rounds=max_rounds,
    )


def _phrase_payload():
    return {
        "follow_up_questions": ALL_FIELD_QUESTIONS,
        "activity_suggestions": [],
    }


# ---------------------------------------------------------------------------
# Field state
# ---------------------------------------------------------------------------


class FieldStateTests(unittest.TestCase):
    def test_missing_fields_are_detected(self):
        controller = _controller(SPARSE_QUESTIONNAIRE)
        self.assertEqual(controller.resolved, ["goals"])
        self.assertEqual(controller.unknown, [])
        self.assertEqual(
            set(controller.unresolved),
            {
                "fixed_commitments",
                "rest_periods",
                "predictable_routines",
                "tasks",
                "preferred_work_start",
                "preferred_work_end",
                "work_days",
                "energy_peak",
            },
        )

    def test_full_questionnaire_is_complete_up_front(self):
        controller = _controller(FULL_QUESTIONNAIRE)
        self.assertTrue(controller.is_complete)
        self.assertEqual(controller.unresolved, [])

    def test_energy_peak_unknown_is_missing(self):
        questionnaire = dict(FULL_QUESTIONNAIRE, energy_peak="unknown")
        controller = _controller(questionnaire)
        self.assertIn("energy_peak", controller.unresolved)

    def test_energy_peak_real_value_is_resolved(self):
        controller = _controller(FULL_QUESTIONNAIRE)
        self.assertIn("energy_peak", controller.resolved)

    def test_optional_fields_never_block_completion(self):
        questionnaire = dict(FULL_QUESTIONNAIRE)  # no habits/challenges/notes
        controller = _controller(questionnaire)
        self.assertTrue(controller.is_complete)

    def test_priority_mapping_covers_p0_to_p4(self):
        self.assertEqual(ai_consultant.QUESTION_PRIORITIES, ("P0", "P1", "P2", "P3", "P4"))
        self.assertEqual(ai_consultant.FIELD_PRIORITY["fixed_commitments"], 0)
        self.assertEqual(ai_consultant.FIELD_PRIORITY["goals"], 4)


# ---------------------------------------------------------------------------
# Controller
# ---------------------------------------------------------------------------


class ControllerTests(unittest.TestCase):
    def test_next_round_selects_two_highest_priority(self):
        controller = _controller(SPARSE_QUESTIONNAIRE, payload=_phrase_payload())
        draft = controller.next_round()
        targets = [q.target_field for q in draft.follow_up_questions]
        self.assertEqual(targets, ["fixed_commitments", "rest_periods"])

    def test_next_round_caps_at_two(self):
        controller = _controller(SPARSE_QUESTIONNAIRE, payload=_phrase_payload())
        draft = controller.next_round()
        self.assertEqual(len(draft.follow_up_questions), 2)

    def test_question_ids_and_priorities_are_python_owned(self):
        controller = _controller(SPARSE_QUESTIONNAIRE, payload=_phrase_payload())
        draft = controller.next_round()
        self.assertEqual(
            [(q.id, q.priority, q.target_field) for q in draft.follow_up_questions],
            [("q1", 0, "fixed_commitments"), ("q2", 1, "rest_periods")],
        )

    def test_draft_is_a_typed_model(self):
        controller = _controller(SPARSE_QUESTIONNAIRE, payload=_phrase_payload())
        self.assertIsInstance(controller.next_round(), ConsultationDraft)

    def test_draft_carries_field_states(self):
        controller = _controller(SPARSE_QUESTIONNAIRE, payload=_phrase_payload())
        draft = controller.next_round()
        self.assertEqual(set(dataclasses.asdict(draft)), set(ai_consultant.DRAFT_KEYS))

    def test_apply_answers_resolves_field(self):
        controller = _controller(SPARSE_QUESTIONNAIRE, payload=_phrase_payload())
        controller.next_round()
        controller.apply_answers({"q1": "Physics class MWF 9am"})
        self.assertIn("fixed_commitments", controller.resolved)
        self.assertNotIn("fixed_commitments", controller.unresolved)

    def test_unknown_answer_moves_to_unknown(self):
        controller = _controller(SPARSE_QUESTIONNAIRE, payload=_phrase_payload())
        controller.next_round()
        controller.apply_answers({"q1": "I don't know"})
        self.assertIn("fixed_commitments", controller.unknown)
        self.assertNotIn("fixed_commitments", controller.unresolved)

    def test_unknown_field_is_never_asked_again(self):
        controller = _controller(SPARSE_QUESTIONNAIRE, payload=_phrase_payload())
        controller.next_round()
        controller.apply_answers({"q1": "not sure"})
        draft = controller.next_round()
        targets = [q.target_field for q in draft.follow_up_questions]
        self.assertNotIn("fixed_commitments", targets)

    def test_skipped_answer_stays_unresolved(self):
        controller = _controller(SPARSE_QUESTIONNAIRE, payload=_phrase_payload())
        controller.next_round()
        controller.apply_answers({})  # nothing answered
        self.assertIn("fixed_commitments", controller.unresolved)

    def test_confirmed_empty_answer_is_resolved(self):
        controller = _controller(SPARSE_QUESTIONNAIRE, payload=_phrase_payload())
        controller.next_round()
        controller.apply_answers({"q1": "none"})
        self.assertIn("fixed_commitments", controller.resolved)

    def test_is_complete_derived_from_unresolved(self):
        controller = _controller(FULL_QUESTIONNAIRE, payload=_phrase_payload())
        self.assertTrue(controller.is_complete)
        draft = controller.next_round()
        self.assertEqual(draft.follow_up_questions, [])
        self.assertTrue(draft.is_complete)

    def test_multi_round_asks_more_than_two_total(self):
        controller = _controller(SPARSE_QUESTIONNAIRE, payload=_phrase_payload())
        seen = []
        for _ in range(5):
            draft = controller.next_round()
            seen.extend(q.id for q in draft.follow_up_questions)
            answers = {q.id: "value" for q in draft.follow_up_questions}
            controller.apply_answers(answers)
            if controller.is_complete:
                break
        self.assertGreater(len(seen), 2)

    def test_max_rounds_stops_asking(self):
        controller = _controller(SPARSE_QUESTIONNAIRE, payload=_phrase_payload(), max_rounds=12)
        for _ in range(12):
            draft = controller.next_round()
            controller.apply_answers({})  # skip every answer
        draft = controller.next_round()
        self.assertEqual(draft.follow_up_questions, [])
        self.assertFalse(controller.is_complete)  # still unresolved, but stopped

    def test_to_state_from_state_roundtrip(self):
        controller = _controller(SPARSE_QUESTIONNAIRE, payload=_phrase_payload())
        controller.next_round()
        controller.apply_answers({"q1": "Lecture 9am"})
        state = controller.to_state()

        restored = ai_consultant.ConsultationController.from_state(
            state, SPARSE_QUESTIONNAIRE, client=FakeClient(payload=_phrase_payload())
        )
        self.assertEqual(sorted(restored.resolved), sorted(controller.resolved))
        self.assertEqual(sorted(restored.unknown), sorted(controller.unknown))
        self.assertEqual(sorted(restored.unresolved), sorted(controller.unresolved))
        self.assertEqual(restored.round_count, controller.round_count)
        self.assertEqual(restored._question_targets, controller._question_targets)

    def test_state_is_json_serializable(self):
        import json

        controller = _controller(SPARSE_QUESTIONNAIRE, payload=_phrase_payload())
        controller.next_round()
        controller.apply_answers({"q1": "x"})
        json.dumps(controller.to_state())  # must not raise

    def test_controllers_do_not_share_state(self):
        first = _controller(SPARSE_QUESTIONNAIRE, payload=_phrase_payload())
        second = _controller(SPARSE_QUESTIONNAIRE, payload=_phrase_payload())
        first.next_round()
        first.apply_answers({"q1": "x"})
        self.assertNotIn("fixed_commitments", second.resolved)


# ---------------------------------------------------------------------------
# Legacy wrappers
# ---------------------------------------------------------------------------


class LegacyWrapperTests(unittest.TestCase):
    def test_start_consultation_returns_legacy_dict_shape(self):
        client = FakeClient(payload=_phrase_payload())
        result = ai_consultant.start_consultation(SPARSE_QUESTIONNAIRE, client=client)
        self.assertEqual(set(result), {"follow_up_questions", "activity_suggestions"})
        self.assertTrue(all(set(q) == {"id", "question"} for q in result["follow_up_questions"]))

    def test_start_consultation_api_failure_returns_empty(self):
        client = FakeClient(error=AINetworkError("down"))
        result = ai_consultant.start_consultation(SPARSE_QUESTIONNAIRE, client=client)
        self.assertEqual(result, {"follow_up_questions": [], "activity_suggestions": []})

    def test_finalize_profile_returns_eight_keys(self):
        profile = ai_consultant.finalize_profile(
            QUESTIONNAIRE, {}, client=FakeClient(FULL_PROFILE_PAYLOAD)
        )
        self.assertEqual(set(profile), set(ai_consultant.PROFILE_KEYS))
        self.assertEqual(len(ai_consultant.PROFILE_KEYS), 8)

    def test_break_preferences_is_a_string(self):
        profile = ai_consultant.finalize_profile(
            QUESTIONNAIRE, {}, client=FakeClient(FULL_PROFILE_PAYLOAD)
        )
        self.assertIsInstance(profile["break_preferences"], str)
        self.assertEqual(profile["break_preferences"], "Take a short break every hour")

    def test_finalize_accepts_list_break_preferences_and_joins(self):
        payload = dict(FULL_PROFILE_PAYLOAD, break_preferences=["Tea", "Stretch"])
        profile = ai_consultant.finalize_profile(
            QUESTIONNAIRE, {}, client=FakeClient(payload)
        )
        self.assertEqual(profile["break_preferences"], "Tea, Stretch")


# ---------------------------------------------------------------------------
# Activity suggestions
# ---------------------------------------------------------------------------


class ActivitySuggestionTests(unittest.TestCase):
    def _suggest(self, activities, questionnaire=None):
        client = FakeClient(
            {
                "activity_suggestions": activities,
                "follow_up_questions": [],
            }
        )
        draft = ai_consultant.start_consultation(
            questionnaire or SPARSE_QUESTIONNAIRE, client=client
        )
        return draft["activity_suggestions"]

    def test_all_four_categories_are_preserved(self):
        for category in ai_consultant.ACTIVITY_CATEGORIES:
            with self.subTest(category=category):
                result = self._suggest(
                    [{"activity_name": "Physics class", "suggested_category": category, "reason": "x"}]
                )
                self.assertEqual(result[0]["suggested_category"], category)

    def test_unknown_category_is_discarded(self):
        result = self._suggest(
            [{"activity_name": "Physics class", "suggested_category": "SOMETHING_ELSE", "reason": "x"}]
        )
        self.assertEqual(result, [])

    def test_short_aliases_are_normalised(self):
        result = self._suggest([{"activity_name": "Sleep", "suggested_category": "rest", "reason": "x"}])
        self.assertEqual(result[0]["suggested_category"], "rest_period")

    def test_empty_reason_gets_a_default(self):
        result = self._suggest([{"activity_name": "Lunch", "suggested_category": "predictable_routine"}])
        self.assertEqual(result[0]["reason"], "Mentioned in the questionnaire.")

    def test_duplicate_names_are_collapsed(self):
        result = self._suggest(
            [
                {"activity_name": "Lunch", "suggested_category": "predictable_routine"},
                {"activity_name": "lunch", "suggested_category": "predictable_routine"},
            ]
        )
        self.assertEqual(len(result), 1)

    def test_suggestions_are_capped(self):
        activities = [
            {"activity_name": f"Activity {i}", "suggested_category": "rest_period"}
            for i in range(20)
        ]
        self.assertEqual(len(self._suggest(activities)), ai_consultant.MAX_ACTIVITY_SUGGESTIONS)


# ---------------------------------------------------------------------------
# Medication guard
# ---------------------------------------------------------------------------


class MedicationGuardTests(unittest.TestCase):
    def _suggest_reason(self, name, reason, questionnaire=None):
        client = FakeClient(
            {
                "activity_suggestions": [
                    {"activity_name": name, "suggested_category": "rest_period", "reason": reason}
                ],
                "follow_up_questions": [],
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
        self.assertIn("a time you confirm", reason)

    def test_user_supplied_time_is_kept(self):
        reason = self._suggest_reason(
            "Blood pressure medication",
            "Take one tablet at 08:00.",
            questionnaire={"fixed_commitments": ["Medication at 08:00 every day"]},
        )
        self.assertIn("08:00", reason)


# ---------------------------------------------------------------------------
# Confirmation boundary
# ---------------------------------------------------------------------------


class ConfirmationBoundaryTests(unittest.TestCase):
    def test_profile_prompt_never_contains_suggestions(self):
        client = FakeClient(FULL_PROFILE_PAYLOAD)
        contaminated = dict(
            QUESTIONNAIRE,
            activity_suggestions=[{"activity_name": "Study Calculus", "suggested_category": "uncertain_task", "reason": "x"}],
        )
        ai_consultant.finalize_profile(contaminated, {}, client=client)
        prompt = client.messages[0][-1]["content"]
        self.assertNotIn("Study Calculus", prompt)
        self.assertNotIn("suggested_category", prompt)

    def test_draft_state_fields_are_stripped_from_profile_input(self):
        client = FakeClient(FULL_PROFILE_PAYLOAD)
        contaminated = dict(QUESTIONNAIRE, resolved_fields=["goals"], unresolved_fields=["tasks"])
        ai_consultant.finalize_profile(contaminated, {}, client=client)
        self.assertNotIn("resolved_fields", client.messages[0][-1]["content"])

    def test_fallback_ignores_suggestions(self):
        contaminated = dict(
            QUESTIONNAIRE,
            activity_suggestions=[{"activity_name": "Study Calculus", "suggested_category": "uncertain_task", "reason": "x"}],
        )
        profile = ai_consultant.build_fallback_profile(contaminated)
        self.assertNotIn("Study Calculus", str(profile))


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

    def test_default_block_is_50(self):
        payload = dict(FULL_PROFILE_PAYLOAD, recommended_work_block_minutes=50)
        profile = ai_consultant.finalize_profile(QUESTIONNAIRE, {}, client=FakeClient(payload))
        self.assertEqual(profile["recommended_work_block_minutes"], 50)

    def test_block_up_to_180_is_accepted(self):
        payload = dict(FULL_PROFILE_PAYLOAD, recommended_work_block_minutes=180)
        profile = ai_consultant.finalize_profile(QUESTIONNAIRE, {}, client=FakeClient(payload))
        self.assertEqual(profile["recommended_work_block_minutes"], 180)

    def test_block_above_180_falls_back_to_default(self):
        payload = {"recommended_work_block_minutes": 181}
        profile = ai_consultant.finalize_profile(QUESTIONNAIRE, {}, client=FakeClient(payload))
        self.assertEqual(profile["recommended_work_block_minutes"], ai_consultant.DEFAULT_WORK_BLOCK_MINUTES)

    def test_out_of_range_block_falls_back_to_default(self):
        payload = {"recommended_work_block_minutes": 999}
        profile = ai_consultant.finalize_profile(QUESTIONNAIRE, {}, client=FakeClient(payload))
        self.assertEqual(profile["recommended_work_block_minutes"], ai_consultant.DEFAULT_WORK_BLOCK_MINUTES)

    def test_fixed_commitments_never_leak(self):
        payload = dict(FULL_PROFILE_PAYLOAD, fixed_commitments=["Wed 14:00 lecture"])
        profile = ai_consultant.finalize_profile(QUESTIONNAIRE, {}, client=FakeClient(payload))
        self.assertNotIn("fixed_commitments", profile)

    def test_malformed_payload_still_yields_full_shape(self):
        profile = ai_consultant.finalize_profile(QUESTIONNAIRE, {}, client=FakeClient("not a mapping"))
        for key in ai_consultant.PROFILE_KEYS:
            self.assertIn(key, profile)

    def test_api_failure_degrades_to_fallback(self):
        client = FakeClient(error=AINetworkError("down"))
        profile = ai_consultant.finalize_profile(QUESTIONNAIRE, {}, client=client)
        self.assertTrue(profile["is_fallback"])
        self.assertEqual(profile["goals"], ["Finish the thesis"])

    def test_answers_accept_any_question_id(self):
        self.assertEqual(
            ai_consultant._clean_answers({"q1": "Morning", "q3": "50 minutes"}),
            {"q1": "Morning", "q3": "50 minutes"},
        )

    def test_unknown_answer_keys_are_dropped(self):
        self.assertEqual(
            ai_consultant._clean_answers({"q1": "Morning", "q9x": "junk", "q2": ""}),
            {"q1": "Morning"},
        )


class FallbackProfileTests(unittest.TestCase):
    def test_uses_only_explicit_information(self):
        profile = ai_consultant.build_fallback_profile(QUESTIONNAIRE)
        self.assertTrue(profile["is_fallback"])
        self.assertEqual(profile["goals"], ["Finish the thesis"])
        self.assertEqual(profile["work_style"], "Prefers short focused sessions")

    def test_default_block_is_50(self):
        profile = ai_consultant.build_fallback_profile(QUESTIONNAIRE)
        self.assertEqual(profile["recommended_work_block_minutes"], 50)

    def test_break_preferences_is_string(self):
        profile = ai_consultant.build_fallback_profile(QUESTIONNAIRE)
        self.assertIsInstance(profile["break_preferences"], str)

    def test_empty_questionnaire_still_returns_full_shape(self):
        profile = ai_consultant.build_fallback_profile({})
        for key in ai_consultant.PROFILE_KEYS:
            self.assertIn(key, profile)
        self.assertEqual(profile["goals"], [])

    def test_deterministic_across_calls(self):
        self.assertEqual(
            ai_consultant.build_fallback_profile(QUESTIONNAIRE),
            ai_consultant.build_fallback_profile(QUESTIONNAIRE),
        )


# ---------------------------------------------------------------------------
# Contract shape
# ---------------------------------------------------------------------------


class ContractShapeTests(unittest.TestCase):
    def test_categories_are_the_four_documented_values(self):
        self.assertEqual(
            tuple(ai_consultant.ACTIVITY_CATEGORIES),
            ("hard_commitment", "rest_period", "predictable_routine", "uncertain_task"),
        )

    def test_duration_types_are_the_two_documented_values(self):
        self.assertEqual(tuple(ai_consultant.DURATION_TYPES), ("predictable", "uncertain"))

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
            title: str
            estimated_minutes: int
            duration_type: str

        client = FakeClient(FULL_PROFILE_PAYLOAD)
        questionnaire = {
            "goals": ["Pass calculus"],
            "tasks": [TaskInput(title="Read papers", estimated_minutes=45, duration_type="uncertain")],
        }
        ai_consultant.finalize_profile(questionnaire, {}, client=client)
        prompt = client.messages[0][-1]["content"]
        self.assertIn("estimated_minutes", prompt)
        self.assertIn("Read papers", prompt)
        self.assertNotIn("TaskInput(", prompt)

    def test_classify_prompt_lists_categories(self):
        from core import prompts

        prompt = prompts.render_classify_prompt("{}")
        for category in ai_consultant.ACTIVITY_CATEGORIES:
            self.assertIn(category, prompt)

    def test_phrase_prompt_lists_selected_fields(self):
        from core import prompts

        prompt = prompts.render_phrase_prompt(
            "{}", [{"field": "fixed_commitments", "priority": "P0", "meaning": "hard commitments"}]
        )
        self.assertIn("fixed_commitments", prompt)
        self.assertIn("P0", prompt)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class HelperTests(unittest.TestCase):
    def test_as_mapping_accepts_dataclass(self):
        @dataclasses.dataclass
        class Questionnaire:
            goals: list

        self.assertEqual(
            ai_consultant._as_mapping(Questionnaire(goals=["a"])), {"goals": ["a"]}
        )

    def test_clean_list_wraps_bare_string(self):
        self.assertEqual(ai_consultant._clean_list("single"), ["single"])

    def test_coerce_break_preferences_joins_list(self):
        self.assertEqual(
            ai_consultant._coerce_break_preferences(["Tea", "Stretch"]), "Tea, Stretch"
        )
        self.assertEqual(ai_consultant._coerce_break_preferences("Tea"), "Tea")
        self.assertEqual(ai_consultant._coerce_break_preferences(None), "")

    def test_classify_answer(self):
        self.assertEqual(ai_consultant._classify_answer("Physics class 9am"), "resolved")
        self.assertEqual(ai_consultant._classify_answer("none"), "resolved")
        self.assertEqual(ai_consultant._classify_answer("I don't know"), "unknown")
        self.assertEqual(ai_consultant._classify_answer("not sure"), "unknown")
        self.assertEqual(ai_consultant._classify_answer(""), "unresolved")
        self.assertEqual(ai_consultant._classify_answer("   "), "unresolved")

    def test_extract_question_texts_first_wins(self):
        raw = [
            {"question": "First?", "target_field": "goals"},
            {"question": "Second?", "target_field": "goals"},
            {"question": "No target"},
        ]
        self.assertEqual(ai_consultant._extract_question_texts(raw), {"goals": "First?"})


# ---------------------------------------------------------------------------
# Answer mapping (V1.2)
# ---------------------------------------------------------------------------


class AnswerMappingTests(unittest.TestCase):
    def test_maps_question_ids_to_fields(self):
        result = ai_consultant.map_answers_to_fields(
            {"q1": "rest_periods", "q2": "work_days"},
            {"q1": "Sleep 23:00-07:00", "q2": "Mon Wed Fri"},
        )
        self.assertEqual(
            result,
            {"rest_periods": ["Sleep 23:00-07:00"], "work_days": ["Mon Wed Fri"]},
        )

    def test_question_id_without_target_is_dropped(self):
        result = ai_consultant.map_answers_to_fields(
            {"q1": "rest_periods"},
            {"q1": "Sleep", "q2": "orphan answer"},
        )
        self.assertEqual(result, {"rest_periods": ["Sleep"]})

    def test_target_without_field_name_is_dropped(self):
        result = ai_consultant.map_answers_to_fields(
            {"q1": ""}, {"q1": "Sleep"}
        )
        self.assertEqual(result, {})

    def test_empty_targets_returns_empty(self):
        result = ai_consultant.map_answers_to_fields({}, {"q1": "Sleep"})
        self.assertEqual(result, {})

    def test_unknown_question_ids_are_ignored(self):
        result = ai_consultant.map_answers_to_fields(
            {"q1": "goals"},
            {"q1": "Pass", "q9x": "junk"},
        )
        self.assertEqual(result, {"goals": ["Pass"]})


# ---------------------------------------------------------------------------
# Field state vs defaults (V1.2)
# ---------------------------------------------------------------------------


class FieldStateDefaultTests(unittest.TestCase):
    def test_defaulted_fields_are_unresolved(self):
        questionnaire = QuestionnaireData(goals=["Pass calculus"])
        controller = ai_consultant.ConsultationController(questionnaire, client=FakeClient())
        self.assertIn("preferred_work_start", controller.unresolved)
        self.assertIn("preferred_work_end", controller.unresolved)
        self.assertIn("work_days", controller.unresolved)

    def test_confirmed_fields_resolve_defaulted_fields(self):
        questionnaire = QuestionnaireData(goals=["Pass calculus"])
        controller = ai_consultant.ConsultationController(
            questionnaire,
            client=FakeClient(),
            confirmed_fields={"goals", "preferred_work_start", "preferred_work_end", "work_days"},
        )
        self.assertIn("preferred_work_start", controller.resolved)
        self.assertIn("work_days", controller.resolved)

    def test_confirmed_but_empty_stays_unresolved(self):
        controller = ai_consultant.ConsultationController(
            {"goals": ["x"], "preferred_work_start": ""},
            client=FakeClient(),
            confirmed_fields={"preferred_work_start"},
        )
        self.assertIn("preferred_work_start", controller.unresolved)

    def test_legacy_dict_filled_fields_still_resolve(self):
        controller = ai_consultant.ConsultationController(FULL_QUESTIONNAIRE, client=FakeClient())
        self.assertTrue(controller.is_complete)

    def test_non_default_start_resolves_even_without_confirmation(self):
        questionnaire = QuestionnaireData(goals=["x"], preferred_work_start="07:00")
        controller = ai_consultant.ConsultationController(questionnaire, client=FakeClient())
        self.assertIn("preferred_work_start", controller.resolved)


# ---------------------------------------------------------------------------
# Fallback preserves confirmed answers (V1.2)
# ---------------------------------------------------------------------------


class FallbackPreserveAnswersTests(unittest.TestCase):
    def test_fallback_preserves_follow_up_answers(self):
        client = FakeClient(error=AINetworkError("down"))
        profile = ai_consultant.finalize_profile(
            {"goals": ["x"]},
            {"q1": "Sleep 23:00-07:00", "q2": "morning"},
            client=client,
            question_targets={"q1": "rest_periods", "q2": "energy_peak"},
        )
        self.assertTrue(profile["is_fallback"])
        self.assertIn("Sleep", profile["scheduling_notes"])

    def test_fallback_merges_goal_answers_into_goals(self):
        client = FakeClient(error=AINetworkError("down"))
        profile = ai_consultant.finalize_profile(
            {"goals": ["Finish thesis"]},
            {"q1": "Pass calculus"},
            client=client,
            question_targets={"q1": "goals"},
        )
        self.assertIn("Pass calculus", profile["goals"])

    def test_legacy_build_fallback_without_answers_still_works(self):
        profile = ai_consultant.build_fallback_profile(QUESTIONNAIRE)
        self.assertTrue(profile["is_fallback"])
        self.assertEqual(profile["goals"], ["Finish the thesis"])

    def test_fallback_marks_answers_not_ai_generated(self):
        profile = ai_consultant.build_fallback_profile(
            {"goals": ["x"]},
            {"q1": "Sleep 23:00-07:00"},
            question_targets={"q1": "rest_periods"},
        )
        self.assertIn("not AI-generated", profile["scheduling_notes"])


# ---------------------------------------------------------------------------
# Structured integration (V1.2)
# ---------------------------------------------------------------------------


class StructuredIntegrationTests(unittest.TestCase):
    def _controller_with_answers(self, answers, targets, unknown=None, questionnaire=None):
        controller = ai_consultant.ConsultationController(
            questionnaire or {"goals": ["x"]}, client=FakeClient()
        )
        controller._question_targets = dict(targets)
        controller._answers = dict(answers)
        if unknown:
            controller.unknown = list(unknown)
        return controller

    def test_parses_rest_period(self):
        controller = self._controller_with_answers(
            {"q1": "Sleep 23:00-07:00"}, {"q1": "rest_periods"}
        )
        result = controller.build_questionnaire_inputs(use_llm=False)
        self.assertEqual(
            result["fields"]["rest_periods"],
            [{"title": "Sleep", "days": [0, 1, 2, 3, 4, 5, 6], "start_time": "23:00", "end_time": "07:00"}],
        )

    def test_parses_predictable_routine(self):
        controller = self._controller_with_answers(
            {"q1": "Morning run 30 minutes at 07:00"}, {"q1": "predictable_routines"}
        )
        result = controller.build_questionnaire_inputs(use_llm=False)
        routine = result["fields"]["predictable_routines"][0]
        self.assertEqual(routine["title"], "Morning run")
        self.assertEqual(routine["estimated_minutes"], 30)

    def test_parses_work_days(self):
        controller = self._controller_with_answers(
            {"q1": "Monday Wednesday Friday"}, {"q1": "work_days"}
        )
        result = controller.build_questionnaire_inputs(use_llm=False)
        self.assertEqual(result["fields"]["work_days"], [0, 2, 4])

    def test_parses_energy_peak(self):
        controller = self._controller_with_answers(
            {"q1": "I'm most productive in the morning"}, {"q1": "energy_peak"}
        )
        result = controller.build_questionnaire_inputs(use_llm=False)
        self.assertEqual(result["fields"]["energy_peak"], "morning")

    def test_parses_am_pm_time(self):
        controller = self._controller_with_answers(
            {"q1": "I start at 7am"}, {"q1": "preferred_work_start"}
        )
        result = controller.build_questionnaire_inputs(use_llm=False)
        self.assertEqual(result["fields"]["preferred_work_start"], "07:00")

    def test_unparseable_goes_to_needs_confirmation(self):
        controller = self._controller_with_answers(
            {"q1": "whenever I feel like it"}, {"q1": "preferred_work_start"}
        )
        result = controller.build_questionnaire_inputs(use_llm=False)
        self.assertNotIn("preferred_work_start", result["fields"])
        self.assertIn("preferred_work_start", result["needs_confirmation"])

    def test_unknown_fields_are_excluded_entirely(self):
        controller = self._controller_with_answers(
            {"q1": "I don't know"}, {"q1": "energy_peak"}, unknown=["energy_peak"]
        )
        result = controller.build_questionnaire_inputs(use_llm=False)
        self.assertNotIn("energy_peak", result["fields"])
        self.assertNotIn("energy_peak", result["needs_confirmation"])

    def test_parse_energy_peak_unknown_returns_none(self):
        self.assertIsNone(ai_consultant._parse_energy_peak("unknown"))

    def test_finalize_uses_field_map_in_prompt(self):
        client = FakeClient(FULL_PROFILE_PAYLOAD)
        ai_consultant.finalize_profile(
            {"goals": ["x"]},
            {"q1": "Sleep 23:00-07:00"},
            client=client,
            question_targets={"q1": "rest_periods"},
        )
        prompt = client.messages[0][-1]["content"]
        self.assertIn("rest_periods", prompt)
        self.assertNotIn('"q1"', prompt)

    def test_controller_finalize_returns_typed_profile(self):
        client = FakeClient(FULL_PROFILE_PAYLOAD)
        controller = ai_consultant.ConsultationController({"goals": ["x"]}, client=client)
        profile = controller.finalize()
        self.assertIsInstance(profile, UserProfile)

    def test_controller_finalize_api_failure_degrades(self):
        client = FakeClient(error=AINetworkError("down"))
        controller = ai_consultant.ConsultationController({"goals": ["x"]}, client=client)
        profile = controller.finalize()
        self.assertTrue(profile.is_fallback)


# ---------------------------------------------------------------------------
# Deterministic parsers (V1.2)
# ---------------------------------------------------------------------------


class ParserTests(unittest.TestCase):
    def test_parse_time_24h(self):
        self.assertEqual(ai_consultant._parse_time("Start at 09:00"), "09:00")

    def test_parse_time_am_pm(self):
        self.assertEqual(ai_consultant._parse_time("7 pm"), "19:00")
        self.assertEqual(ai_consultant._parse_time("7am"), "07:00")

    def test_parse_weekdays_english_and_chinese(self):
        self.assertEqual(ai_consultant._parse_weekdays("Mon Wed Fri"), [0, 2, 4])
        self.assertEqual(ai_consultant._parse_weekdays("周一 周三 周五"), [0, 2, 4])

    def test_parse_weekdays_none(self):
        self.assertIsNone(ai_consultant._parse_weekdays("no days here"))

    def test_parse_minutes(self):
        self.assertEqual(ai_consultant._parse_minutes("30 minutes"), 30)
        self.assertEqual(ai_consultant._parse_minutes("1 hour"), 60)
        self.assertEqual(ai_consultant._parse_minutes("半小时"), 30)

    def test_parse_rest_period_defaults_days(self):
        result = ai_consultant._parse_rest_period("Sleep 23:00-07:00")
        self.assertEqual(result["title"], "Sleep")
        self.assertEqual(result["days"], [0, 1, 2, 3, 4, 5, 6])

    def test_parse_rest_period_rejects_same_time(self):
        self.assertIsNone(ai_consultant._parse_rest_period("Break 09:00-09:00"))


if __name__ == "__main__":
    unittest.main()
