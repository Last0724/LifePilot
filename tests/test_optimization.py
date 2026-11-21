"""Tests for ``ux.optimization`` (pure logic, no Streamlit required)."""

from __future__ import annotations

import unittest

from ux.optimization import (
    OptimizationEngine,
    ScheduleEntry,
    Suggestion,
    build_mock_schedule,
    build_mock_suggestions,
    entry_fields,
)

# A faithful sample of B's real schedule contract (see ui/dashboard.py and
# ui/planner.py): the entries are plain dictionaries, not objects, so getattr()
# cannot read them. These fixtures exercise the exact shape the Dashboard will
# pass into the Reverse-UX module.
B_SCHEDULE_DICT = {
    "id": "demo_0",
    "title": "Outline research proposal",
    "date": "2026-11-23",
    "start": "09:00",
    "end": "10:30",
    "category": "Study",
    "completed": False,
    "is_fixed": False,
}


class MockSuggestionsTests(unittest.TestCase):
    def test_suggestions_are_deterministic(self):
        self.assertEqual(build_mock_suggestions(), build_mock_suggestions())

    def test_at_least_three_suggestions(self):
        self.assertGreaterEqual(len(build_mock_suggestions()), 3)

    def test_suggestion_ids_are_unique(self):
        suggestions = build_mock_suggestions()
        self.assertEqual(len({s.id for s in suggestions}), len(suggestions))

    def test_all_suggestions_are_marked_simulated(self):
        self.assertTrue(all(s.simulated for s in build_mock_suggestions()))

    def test_all_three_categories_are_covered(self):
        categories = {s.category for s in build_mock_suggestions()}
        self.assertEqual(
            categories, {"time_allocation", "task_ordering", "ai_adjustment"}
        )

    def test_mock_schedule_is_non_empty(self):
        self.assertGreaterEqual(len(build_mock_schedule()), 1)


class OptimizationEngineTests(unittest.TestCase):
    def _engine(self) -> OptimizationEngine:
        return OptimizationEngine(
            [
                Suggestion("a", "3% more efficient", "time_allocation", "d", "Change A"),
                Suggestion("b", "better ordering", "task_ordering", "d", "Change B"),
                Suggestion("c", "AI adjustment", "ai_adjustment", "d", "Change C"),
            ]
        )

    def test_current_starts_at_first(self):
        self.assertEqual(self._engine().current.id, "a")

    def test_apply_records_change_and_advances(self):
        engine = self._engine()
        applied = engine.apply()
        self.assertEqual(applied.id, "a")
        self.assertEqual(engine.applied_changes, ["Change A"])
        self.assertEqual(engine.current.id, "b")

    def test_keep_does_not_apply(self):
        engine = self._engine()
        engine.keep()
        self.assertEqual(engine.applied_changes, [])
        self.assertEqual(engine.current.id, "b")

    def test_remind_later_advances_and_counts(self):
        engine = self._engine()
        engine.remind_later()
        self.assertEqual(engine.remind_count, 1)
        self.assertEqual(engine.current.id, "b")

    def test_three_successive_states(self):
        engine = self._engine()
        seen = []
        for _ in range(3):
            seen.append(engine.current.id)
            engine.keep()
        self.assertEqual(seen, ["a", "b", "c"])

    def test_wraps_around_after_last(self):
        engine = self._engine()
        for _ in range(3):
            engine.keep()
        self.assertEqual(engine.current.id, "a")
        self.assertEqual(engine.step, 4)

    def test_schedule_intact_unless_apply(self):
        engine = self._engine()
        engine.keep()
        engine.remind_later()
        self.assertEqual(engine.applied_changes, [])
        engine.apply()
        self.assertEqual(engine.applied_changes, ["Change C"])

    def test_preview_returns_change_without_applying(self):
        engine = self._engine()
        self.assertEqual(engine.preview(), "Change A")
        self.assertEqual(engine.applied_changes, [])

    def test_empty_engine_has_no_current(self):
        engine = OptimizationEngine([])
        self.assertIsNone(engine.current)
        self.assertIsNone(engine.apply())
        self.assertEqual(engine.preview(), "")


class ScheduleCompatibilityTests(unittest.TestCase):
    """Feature 01 must read B's real dictionary schedule, not just objects."""

    def test_entry_fields_reads_real_dict(self):
        self.assertEqual(
            entry_fields(B_SCHEDULE_DICT),
            ("Outline research proposal", "09:00", "10:30"),
        )

    def test_entry_fields_reads_object_shape(self):
        entry = ScheduleEntry("Study calculus", "09:00", "10:30")
        self.assertEqual(entry_fields(entry), ("Study calculus", "09:00", "10:30"))

    def test_entry_fields_dict_missing_keys_fall_back(self):
        self.assertEqual(entry_fields({}), ("?", "", ""))
        self.assertEqual(entry_fields({"title": "Only a title"}), ("Only a title", "", ""))

    def test_entry_fields_ignores_extra_contract_keys(self):
        # id/date/category/completed/is_fixed must not interfere with the
        # three display fields.
        self.assertEqual(entry_fields(B_SCHEDULE_DICT)[0], "Outline research proposal")

    def test_mock_schedule_uses_dict_contract(self):
        for item in build_mock_schedule():
            self.assertIsInstance(item, dict)
            self.assertEqual(
                set(item),
                {"id", "title", "date", "start", "end", "category", "completed", "is_fixed"},
            )

    def test_mock_schedule_reads_correctly_via_entry_fields(self):
        for item in build_mock_schedule():
            title, start, end = entry_fields(item)
            self.assertNotEqual(title, "?")
            self.assertTrue(start and end)

    def test_full_contract_list_passes_through(self):
        schedule = [B_SCHEDULE_DICT, build_mock_schedule()[0]]
        titles = [entry_fields(item)[0] for item in schedule]
        self.assertEqual(titles, ["Outline research proposal", "Study calculus"])


if __name__ == "__main__":
    unittest.main()
