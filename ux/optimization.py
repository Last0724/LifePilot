"""Pure logic for the Endless Optimization reverse-UX feature.

This module deliberately imports neither Streamlit nor ``core.models``, so it
can be unit-tested offline and swapped into the app independent of the
still-evolving scheduler contract. The UI layer lives in
``ux/endless_optimization.py``.

The reverse-UX idea, in one sentence: an app whose job is to *save* you time
instead keeps inventing reasons for you to spend more of it. Every action the
user takes - optimise, keep, or remind-later - advances to a fresh
suggestion, so the schedule is never quite good enough.

A real AI optimizer can be plugged in later by replacing
:func:`build_mock_suggestions`; until then the engine returns deterministic,
clearly-marked simulated suggestions (``simulated=True``), which is exactly
the distinction the acceptance criteria require.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

# Human-readable labels for the three suggestion categories the feature must
# demonstrate: time allocation, task ordering, and AI-recommended adjustment.
CATEGORY_LABELS = {
    "time_allocation": "Time allocation",
    "task_ordering": "Task ordering",
    "ai_adjustment": "AI-recommended adjustment",
}


@dataclass(frozen=True)
class ScheduleEntry:
    """One object-shaped schedule entry (title + HH:MM window).

    Kept as the object-shaped fixture for :func:`entry_fields`, which must
    accept both this dataclass and B's real dictionary contract.
    """

    title: str
    start: str
    end: str


def entry_fields(item) -> tuple[str, str, str]:
    """Return ``(title, start, end)`` from a dict- or object-shaped entry.

    B's real schedule contract is a ``dict`` with ``title`` / ``start`` /
    ``end`` keys (plus ``id`` / ``date`` / ``category`` / ``completed`` /
    ``is_fixed``). Python's :func:`getattr` cannot read dictionary keys, so
    the dict branch must use ``item.get(...)``. The object branch keeps
    supporting :class:`ScheduleEntry` and future dataclass-based schedules.
    """
    if isinstance(item, dict):
        return (
            item.get("title", "?"),
            item.get("start", ""),
            item.get("end", ""),
        )
    return (
        getattr(item, "title", "?"),
        getattr(item, "start", ""),
        getattr(item, "end", ""),
    )


@dataclass(frozen=True)
class Suggestion:
    """A single optimization nudge.

    ``simulated`` marks mock/demo suggestions so the UI can visually separate
    them from real AI output, per the acceptance criteria.
    """

    id: str
    headline: str
    category: str
    detail: str
    change: str
    simulated: bool = True


def build_mock_schedule() -> list[dict]:
    """Return a small deterministic schedule using B's real dictionary contract.

    Each item carries the exact keys produced by B's frontend schedule
    (``id`` / ``title`` / ``date`` / ``start`` / ``end`` / ``category`` /
    ``completed`` / ``is_fixed``) so the standalone preview exercises the same
    data shape the integrated Dashboard will pass in.
    """
    return [
        {
            "id": "mock_1",
            "title": "Study calculus",
            "date": "2026-11-23",
            "start": "09:00",
            "end": "10:30",
            "category": "Study",
            "completed": False,
            "is_fixed": False,
        },
        {
            "id": "mock_2",
            "title": "Read papers",
            "date": "2026-11-23",
            "start": "14:00",
            "end": "15:00",
            "category": "Study",
            "completed": False,
            "is_fixed": False,
        },
        {
            "id": "mock_3",
            "title": "Write report",
            "date": "2026-11-23",
            "start": "15:00",
            "end": "16:30",
            "category": "Work",
            "completed": False,
            "is_fixed": False,
        },
        {
            "id": "mock_4",
            "title": "Review flashcards",
            "date": "2026-11-23",
            "start": "16:30",
            "end": "17:00",
            "category": "Study",
            "completed": False,
            "is_fixed": False,
        },
        {
            "id": "mock_5",
            "title": "Gym",
            "date": "2026-11-23",
            "start": "17:30",
            "end": "18:30",
            "category": "Personal",
            "completed": False,
            "is_fixed": True,
        },
    ]


def build_mock_suggestions() -> list[Suggestion]:
    """Return the deterministic suggestion queue (five states, three types)."""
    return [
        Suggestion(
            id="opt-1",
            headline="Your schedule could be 3% more efficient.",
            category="time_allocation",
            detail="Our analysis found slack in your morning focus block.",
            change="Move 'Read papers' from 14:00 to 07:30.",
        ),
        Suggestion(
            id="opt-2",
            headline="Potential time-allocation problem detected.",
            category="time_allocation",
            detail="One block is longer than your reported focus tolerance.",
            change="Shorten 'Study calculus' from 90 to 60 minutes.",
        ),
        Suggestion(
            id="opt-3",
            headline="A better task ordering is available.",
            category="task_ordering",
            detail="Reordering reduces context switching between similar tasks.",
            change="Swap 'Write report' and 'Review flashcards'.",
        ),
        Suggestion(
            id="opt-4",
            headline="AI recommends a schedule adjustment.",
            category="ai_adjustment",
            detail="Recovery timing would be improved by moving your workout.",
            change="Shift 'Gym' from 17:30 to 18:00.",
        ),
        Suggestion(
            id="opt-5",
            headline="Your schedule could be 2% more efficient.",
            category="time_allocation",
            detail="Consolidating breaks frees one contiguous focus window.",
            change="Merge two 15-minute breaks into one 30-minute block.",
        ),
    ]


class OptimizationEngine:
    """State machine driving the endless suggestion loop.

    Every action - :meth:`apply`, :meth:`keep`, or :meth:`remind_later` -
    advances to the next suggestion, so the user is never "done". The queue
    wraps around, which is the whole joke: the app never considers a schedule
    good enough.

    The schedule is only ever mutated on :meth:`apply` (an explicit user
    confirmation), and the result is recorded in :attr:`applied_changes`
    rather than destructively overwritten, so "keep" always leaves the
    original schedule intact.
    """

    def __init__(self, suggestions: Sequence[Suggestion] | None = None) -> None:
        self._suggestions = list(
            suggestions if suggestions is not None else build_mock_suggestions()
        )
        self._index = 0
        self._applied: list[str] = []
        self._remind_count = 0

    # -- read-only state ----------------------------------------------------

    @property
    def current(self) -> Suggestion | None:
        """The suggestion on screen right now, or ``None`` when empty."""
        if not self._suggestions:
            return None
        return self._suggestions[self._index % len(self._suggestions)]

    @property
    def applied_changes(self) -> list[str]:
        """Changes the user has explicitly confirmed via :meth:`apply`."""
        return list(self._applied)

    @property
    def remind_count(self) -> int:
        """How many times the user hit "remind me later"."""
        return self._remind_count

    @property
    def step(self) -> int:
        """1-based suggestion number; keeps counting across wraps."""
        return self._index + 1

    @property
    def total(self) -> int:
        """Number of distinct suggestions in the queue."""
        return len(self._suggestions)

    # -- actions ------------------------------------------------------------

    def apply(self) -> Suggestion | None:
        """Confirm the current change, record it, and advance."""
        suggestion = self.current
        if suggestion is None:
            return None
        self._applied.append(suggestion.change)
        self._advance()
        return suggestion

    def keep(self) -> Suggestion | None:
        """Reject the current change (schedule untouched) and advance."""
        suggestion = self.current
        self._advance()
        return suggestion

    def remind_later(self) -> Suggestion | None:
        """Dismiss with a reminder, and advance to the next suggestion."""
        suggestion = self.current
        self._remind_count += 1
        self._advance()
        return suggestion

    def preview(self) -> str:
        """The current change text, without applying anything."""
        suggestion = self.current
        return suggestion.change if suggestion else ""

    # -- internals ----------------------------------------------------------

    def _advance(self) -> None:
        self._index += 1
