"""Pure, Streamlit-free optimization engine for the Endless Optimization feature.

This module is the *testable counterpart* to B's product-integrated
optimization in ``ui/mechanisms.py`` (``_propose``). It implements the same
algorithm -- shift unfinished, non-fixed tasks by small time offsets, keep
each move within a single day, and reject any move that would overlap another
task -- but as pure functions with no Streamlit import, so the scheduling math
can be unit-tested offline.

B's integrated version ships with zero tests. This module lets us verify the
algorithm independently, and B can either adopt it directly (replacing
``_propose`` with a one-line ``propose_optimizations(...)`` call) or port
these tests back onto the integrated mechanism.

The reverse-UX idea is unchanged: the app keeps inventing new "optimizations"
every round, so the schedule is never quite good enough.
"""

from __future__ import annotations

from dataclasses import dataclass

# Offsets (minutes) tried in order for a given round. Even rounds use the
# first sequence, odd rounds the second, matching B's alternating direction.
_OFFSETS_EVEN = (5, -5, 10, -10)
_OFFSETS_ODD = (-5, 5, -10, 10)
_DEFAULT_MAX_CHANGES = 6
_MINUTES_PER_DAY = 24 * 60


def clock_to_minutes(value: str) -> int:
    """Return minutes since midnight for a ``'HH:MM'`` string."""
    hour, minute = value.split(":")
    return int(hour) * 60 + int(minute)


def minutes_to_clock(value: int) -> str:
    """Return a zero-padded ``'HH:MM'`` string for minutes since midnight."""
    return f"{value // 60:02d}:{value % 60:02d}"


def first_overlap(entries, candidate, *, exclude_id=None):
    """Return the first entry overlapping ``candidate``, else ``None``.

    Two entries overlap when they share a ``date`` and their half-open
    ``[start, end)`` windows intersect. ``exclude_id`` ignores the entry with
    that ``id`` (used to skip the candidate itself). Comparison is on the
    zero-padded ``'HH:MM'`` strings, where lexicographic order equals
    chronological order.
    """
    for entry in entries:
        if entry["date"] != candidate["date"]:
            continue
        if exclude_id is not None and entry.get("id") == exclude_id:
            continue
        if candidate["start"] < entry["end"] and entry["start"] < candidate["end"]:
            return entry
    return None


@dataclass(frozen=True)
class OptimizationChange:
    """One proposed move: ``entry`` (original) -> ``proposed`` (time-shifted)."""

    entry: dict
    proposed: dict


def propose_optimizations(schedule, round_number=0, max_changes=_DEFAULT_MAX_CHANGES):
    """Propose time-shifts for movable tasks.

    Returns ``(updated, changes)`` where ``updated`` is the schedule with the
    accepted moves applied and ``changes`` is a list of
    :class:`OptimizationChange`. Mirrors B's ``_propose`` exactly:

    * sort by ``(date, start)``;
    * skip ``is_fixed`` and ``completed`` tasks;
    * try the round's offsets in order, accepting the first move that stays
      within one day and overlaps nothing;
    * stop after ``max_changes`` moves.

    The input ``schedule`` is not mutated.
    """
    updated = [dict(item) for item in schedule]
    changes: list[OptimizationChange] = []
    offsets = _OFFSETS_EVEN if round_number % 2 == 0 else _OFFSETS_ODD
    ordered = sorted(enumerate(schedule), key=lambda pair: (pair[1]["date"], pair[1]["start"]))
    for index, entry in ordered:
        if entry.get("is_fixed") or entry.get("completed"):
            continue
        for step in offsets:
            start = clock_to_minutes(entry["start"]) + step
            end = clock_to_minutes(entry["end"]) + step
            if not (0 <= start < end < _MINUTES_PER_DAY):
                continue
            proposed = dict(entry, start=minutes_to_clock(start), end=minutes_to_clock(end))
            if first_overlap(updated, proposed, exclude_id=entry.get("id")) is None:
                updated[index] = proposed
                changes.append(OptimizationChange(entry=dict(entry), proposed=proposed))
                break
        if len(changes) >= max_changes:
            break
    return updated, changes
