"""Tests for ``ux.optimization`` (pure logic, no Streamlit required)."""

from __future__ import annotations

import unittest

from ux.optimization import (
    OptimizationEngine,
    Suggestion,
    build_mock_schedule,
    build_mock_suggestions,
)


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


if __name__ == "__main__":
    unittest.main()
