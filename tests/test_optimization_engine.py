"""Offline tests for ``ux.optimization_engine``.

These exercise the scheduling math that B's ``ui/mechanisms.py`` optimization
relies on, with no Streamlit dependency, so they run in plain ``unittest``.
"""

from __future__ import annotations

import unittest

from ux.optimization_engine import (
    OptimizationChange,
    clock_to_minutes,
    first_overlap,
    minutes_to_clock,
    propose_optimizations,
)


def task(task_id, start, end, *, date="2026-11-23", fixed=False, completed=False, title=None):
    """Build a schedule entry matching B's real dictionary contract."""
    return {
        "id": task_id,
        "title": title or f"Task {task_id}",
        "date": date,
        "start": start,
        "end": end,
        "category": "Study",
        "completed": completed,
        "is_fixed": fixed,
    }


class ClockConversionTests(unittest.TestCase):
    def test_minutes_from_clock(self):
        self.assertEqual(clock_to_minutes("00:00"), 0)
        self.assertEqual(clock_to_minutes("09:30"), 570)
        self.assertEqual(clock_to_minutes("23:59"), 1439)

    def test_clock_from_minutes(self):
        self.assertEqual(minutes_to_clock(0), "00:00")
        self.assertEqual(minutes_to_clock(570), "09:30")
        self.assertEqual(minutes_to_clock(1439), "23:59")

    def test_round_trip(self):
        for value in ("00:00", "06:05", "09:30", "12:00", "23:59"):
            self.assertEqual(minutes_to_clock(clock_to_minutes(value)), value)


class FirstOverlapTests(unittest.TestCase):
    def test_same_day_overlap(self):
        a = task("a", "09:00", "10:30")
        b = task("b", "10:00", "11:00")
        self.assertEqual(first_overlap([b], a)["id"], "b")

    def test_same_day_no_overlap(self):
        a = task("a", "09:00", "10:00")
        b = task("b", "10:30", "11:00")
        self.assertIsNone(first_overlap([b], a))

    def test_touching_edges_do_not_overlap(self):
        # a ends exactly when b starts: half-open interval -> no overlap.
        a = task("a", "09:00", "10:00")
        b = task("b", "10:00", "11:00")
        self.assertIsNone(first_overlap([b], a))

    def test_different_day_no_overlap(self):
        a = task("a", "09:00", "10:00", date="2026-11-23")
        b = task("b", "09:00", "10:00", date="2026-11-24")
        self.assertIsNone(first_overlap([b], a))

    def test_exclude_id_ignores_self(self):
        a = task("a", "09:00", "10:00")
        self.assertIsNone(first_overlap([a], a, exclude_id="a"))


class ProposeOptimizationsTests(unittest.TestCase):
    def test_empty_schedule(self):
        updated, changes = propose_optimizations([])
        self.assertEqual(updated, [])
        self.assertEqual(changes, [])

    def test_skips_fixed_and_completed(self):
        schedule = [
            task("f", "09:00", "10:00", fixed=True),
            task("c", "11:00", "12:00", completed=True),
        ]
        updated, changes = propose_optimizations(schedule)
        self.assertEqual(changes, [])
        self.assertEqual(updated, schedule)

    def test_moves_movable_task_forward_on_even_round(self):
        schedule = [task("a", "09:00", "10:00")]
        updated, changes = propose_optimizations(schedule, round_number=0)
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0].proposed["start"], "09:05")
        self.assertEqual(changes[0].proposed["end"], "10:05")

    def test_moves_movable_task_backward_on_odd_round(self):
        schedule = [task("a", "09:00", "10:00")]
        updated, changes = propose_optimizations(schedule, round_number=1)
        self.assertEqual(changes[0].proposed["start"], "08:55")
        self.assertEqual(changes[0].proposed["end"], "09:55")

    def test_does_not_cross_midnight(self):
        # 23:50-23:59: +5/+10 would push past 23:59, so it falls back to -5.
        schedule = [task("late", "23:50", "23:59")]
        updated, changes = propose_optimizations(schedule, round_number=0)
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0].proposed["start"], "23:45")
        self.assertEqual(changes[0].proposed["end"], "23:54")

    def test_only_changes_times(self):
        schedule = [task("a", "09:00", "10:00", title="Study calculus")]
        updated, changes = propose_optimizations(schedule, round_number=0)
        proposed = changes[0].proposed
        self.assertEqual(proposed["id"], "a")
        self.assertEqual(proposed["title"], "Study calculus")
        self.assertEqual(proposed["date"], "2026-11-23")
        self.assertEqual(proposed["category"], "Study")
        self.assertIs(proposed["completed"], False)
        self.assertIs(proposed["is_fixed"], False)

    def test_original_entry_is_preserved_in_change(self):
        schedule = [task("a", "09:00", "10:00")]
        updated, changes = propose_optimizations(schedule, round_number=0)
        self.assertEqual(changes[0].entry["start"], "09:00")
        self.assertEqual(changes[0].entry["end"], "10:00")

    def test_input_schedule_is_not_mutated(self):
        schedule = [task("a", "09:00", "10:00")]
        propose_optimizations(schedule, round_number=0)
        self.assertEqual(schedule[0]["start"], "09:00")

    def test_avoids_overlap_by_trying_next_offset(self):
        # Two adjacent tasks: moving 'a' forward (+5) would overlap 'b', so the
        # engine must fall back to a later offset (here, -5).
        a = task("a", "09:00", "10:00")
        b = task("b", "10:00", "11:00")
        updated, changes = propose_optimizations([a, b], round_number=0)
        by_id = {change.entry["id"]: change for change in changes}
        a_proposed = by_id["a"].proposed
        self.assertIsNone(first_overlap([b], a_proposed))
        self.assertEqual(a_proposed["start"], "08:55")

    def test_result_has_no_overlaps(self):
        schedule = [
            task("a", "08:00", "09:00"),
            task("b", "09:00", "10:00"),
            task("c", "10:00", "11:00"),
            task("d", "11:00", "12:00"),
        ]
        updated, changes = propose_optimizations(schedule, round_number=0)
        for item in updated:
            self.assertIsNone(first_overlap(updated, item, exclude_id=item["id"]))

    def test_stops_after_max_changes(self):
        schedule = [
            task(f"t{i}", "09:00", "10:00", date=f"2026-12-{i + 1:02d}")
            for i in range(10)
        ]
        updated, changes = propose_optimizations(schedule, round_number=0, max_changes=3)
        self.assertEqual(len(changes), 3)

    def test_changes_are_structured(self):
        schedule = [task("a", "09:00", "10:00")]
        updated, changes = propose_optimizations(schedule, round_number=0)
        self.assertIsInstance(changes[0], OptimizationChange)
        self.assertEqual(set(changes[0].entry), set(changes[0].proposed))


if __name__ == "__main__":
    unittest.main()
