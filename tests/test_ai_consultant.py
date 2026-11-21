"""Tests for ``core.ai_consultant``.

A fake client stands in for ``DeepSeekClient`` so every path - success,
sloppy payload, transport failure - is exercised without a network call.
"""

from __future__ import annotations

import dataclasses
import unittest

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


QUESTIONNAIRE = {
    "goals": ["Finish the thesis"],
    "tasks": ["Read three papers"],
    "fixed_commitments": ["Wed 14:00 lecture"],
    "preferred_work_hours": ["morning"],
    "work_style": "Prefers short focused sessions",
    "preferences": ["Quiet room"],
}


class StartConsultationTests(unittest.TestCase):
    def test_returns_question_objects_with_ids(self):
        client = FakeClient(
            {
                "follow_up_questions": [
                    {"id": "q1", "question": "Which deadline is closest?"},
                    {"id": "q2", "question": "How long can you focus?"},
                ]
            }
        )
        draft = ai_consultant.start_consultation(QUESTIONNAIRE, client=client)

        self.assertEqual(
            draft["follow_up_questions"],
            [
                {"id": "q1", "question": "Which deadline is closest?"},
                {"id": "q2", "question": "How long can you focus?"},
            ],
        )

    def test_draft_contains_only_questions(self):
        client = FakeClient({"follow_up_questions": []})
        draft = ai_consultant.start_consultation(QUESTIONNAIRE, client=client)

        self.assertEqual(set(draft.keys()), {"follow_up_questions"})

    def test_bare_strings_are_accepted_and_ided(self):
        client = FakeClient({"follow_up_questions": ["First?", "Second?"]})
        draft = ai_consultant.start_consultation(QUESTIONNAIRE, client=client)

        ids = [item["id"] for item in draft["follow_up_questions"]]
        self.assertEqual(ids, ["q1", "q2"])

    def test_model_supplied_ids_are_replaced(self):
        client = FakeClient(
            {"follow_up_questions": [{"id": "zzz", "question": "A?"}]}
        )
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

    def test_api_failure_returns_empty_list(self):
        client = FakeClient(error=AINetworkError("service down"))
        draft = ai_consultant.start_consultation(QUESTIONNAIRE, client=client)

        self.assertEqual(draft, {"follow_up_questions": []})


class FinalizeProfileTests(unittest.TestCase):
    def test_normalises_full_payload(self):
        payload = {
            "summary": "A focused student.",
            "goals": ["Finish the thesis"],
            "work_style": "Short sessions",
            "preferences": ["Quiet room"],
            "recommended_work_block_minutes": 45,
            "break_preferences": ["Tea"],
            "scheduling_notes": "Avoid Wednesday afternoon.",
        }
        profile = ai_consultant.finalize_profile(
            QUESTIONNAIRE, {}, client=FakeClient(payload)
        )

        for key in ai_consultant.PROFILE_KEYS:
            self.assertIn(key, profile)
        self.assertEqual(profile["recommended_work_block_minutes"], 45)
        self.assertFalse(profile["is_fallback"])

    def test_fixed_commitments_never_leak(self):
        payload = {
            "summary": "x",
            "goals": [],
            "work_style": "",
            "preferences": [],
            "recommended_work_block_minutes": 25,
            "break_preferences": [],
            "scheduling_notes": "",
            "fixed_commitments": ["Wed 14:00 lecture"],
        }
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
        profile = ai_consultant.build_fallback_profile(None)

        self.assertTrue(profile["is_fallback"])


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

    def test_follow_up_ids_match_documented_keys(self):
        self.assertEqual(ai_consultant.FOLLOW_UP_IDS, ("q1", "q2"))


if __name__ == "__main__":
    unittest.main()
