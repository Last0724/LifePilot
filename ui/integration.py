"""ui/integration.py — bridge between B's frontend dicts and the V1.2 core.

This module only *converts* data. It never modifies ``core/`` and never
renders UI. Its public surface:

* :func:`build_questionnaire` — turn B's questionnaire payload into a
  :class:`~core.models.QuestionnaireData`, without guessing fields the user
  did not provide (``work_days`` / ``energy_peak`` are only set when the
  payload actually contains them).
* :func:`schedule_to_dicts` — turn a :class:`~core.models.ScheduleResult`
  into the dicts B's planner expects, re-adding fixed commitments as
  ``is_fixed=True`` entries so they stay visible on the weekly calendar.
* :func:`unscheduled_to_dicts` — keep unscheduled tasks together with their
  reasons.
* :func:`plan_week` — one stable entrypoint: schedule with the deterministic
  core scheduler and convert the result in a single call.

Design notes
------------
* A task that arrives as a plain string (B's current payload) has no
  user-confirmed duration. It is created as ``duration_type=UNCERTAIN`` with
  ``DEFAULT_UNCERTAIN_MINUTES`` — the UNCERTAIN type *is* the explicit marker
  that this duration is an estimate, so the scheduler applies the 20% buffer
  and nothing pretends to be a user confirmation. Original titles are kept
  verbatim.
* Task ids are assigned deterministically (``t1..tn``) by this adapter, so
  re-planning with the same payload produces the same ids.
* Fixed commitments are deduplicated on ``(title, start, end)``. They never
  appear in ``ScheduleResult.items`` (the scheduler keeps them as protected
  blockers), so ``schedule_to_dicts`` re-adds each of them exactly once with
  ``is_fixed=True``. Rest periods are *not* re-added as entries: their
  protection lives in the scheduler, and the converted dicts never contain
  anything scheduled inside a rest period.
* ``completed`` state is preserved across replans: when a ``previous``
  schedule is supplied, tasks with the same id keep their ``completed`` flag.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time
from typing import Any, Iterable, Mapping

from core.models import (
    DurationType,
    FixedCommitment,
    PredictableRoutine,
    Priority,
    QuestionnaireData,
    RestPeriod,
    ScheduleResult,
    TaskInput,
)
from core.scheduler import build_schedule

__all__ = [
    "DEFAULT_UNCERTAIN_MINUTES",
    "FIXED_ID_PREFIX",
    "QuestionnaireBuild",
    "WeekPlan",
    "build_questionnaire",
    "plan_week",
    "schedule_to_dicts",
    "unscheduled_to_dicts",
]

#: Duration used for tasks whose duration the user did not provide. Combined
#: with ``DurationType.UNCERTAIN`` this is an explicit estimate, never a
#: user-confirmed value.
DEFAULT_UNCERTAIN_MINUTES = 45

#: Prefix for the synthetic ids of fixed-commitment entries in B's schedule.
FIXED_ID_PREFIX = "fixed"

#: The seven keys every schedule dict passed to B's planner must carry.
SCHEDULE_FIELDS = (
    "id",
    "title",
    "date",
    "start",
    "end",
    "category",
    "completed",
    "is_fixed",
)


@dataclass(frozen=True)
class QuestionnaireBuild:
    """Result of :func:`build_questionnaire`.

    Attributes:
        questionnaire: The validated V1.2 questionnaire.
        confirmed_fields: Fields that came from the payload (or were passed
            in explicitly) — i.e. user-confirmed information.
        estimated_task_ids: Task ids whose minutes were defaulted by the
            adapter (``DEFAULT_UNCERTAIN_MINUTES``, ``UNCERTAIN``), so the
            integrator can tell estimates from confirmed durations.
    """

    questionnaire: QuestionnaireData
    confirmed_fields: frozenset[str] = frozenset()
    estimated_task_ids: frozenset[str] = frozenset()


@dataclass(frozen=True)
class WeekPlan:
    """Full plan for one week in B's dict shape, plus the raw core result."""

    result: ScheduleResult
    schedule: list[dict]
    unscheduled: list[dict]
    warnings: list[str] = field(default_factory=list)


def _mapping(value: Any, what: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{what} 必须是字典，收到 {type(value).__name__}")
    return value


def _clock(value: str, field_name: str) -> time:
    try:
        return time.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} 必须是 HH:MM，收到 {value!r}") from exc


def _fixed_commitment(item: Mapping[str, Any]) -> FixedCommitment:
    title = str(item.get("title", "")).strip()
    if not title:
        raise ValueError("fixed_commitments 条目缺少 title")
    raw_date = item.get("date")
    raw_start = item.get("start")
    raw_end = item.get("end")
    try:
        day = date.fromisoformat(str(raw_date))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"固定承诺 {title!r} 的 date 必须是 YYYY-MM-DD，收到 {raw_date!r}") from exc
    start_clock = _clock(str(raw_start), f"固定承诺 {title!r} 的 start")
    end_clock = _clock(str(raw_end), f"固定承诺 {title!r} 的 end")
    if end_clock <= start_clock:
        raise ValueError(
            f"固定承诺 {title!r} 的 end 必须晚于 start"
            "（B 前端不允许跨夜固定承诺，V1 不做猜测）"
        )
    start = datetime.combine(day, start_clock)
    end = datetime.combine(day, end_clock)
    return FixedCommitment(title=title, start=start, end=end, location="")


def _task_from_entry(entry: Any, index: int, assigned_id: str) -> TaskInput:
    if isinstance(entry, str):
        title = entry.strip()
        if not title:
            raise ValueError(f"tasks[{index}] 标题不能为空")
        return TaskInput(
            title=title,
            estimated_minutes=DEFAULT_UNCERTAIN_MINUTES,
            id=assigned_id,
            duration_type=DurationType.UNCERTAIN,
        )
    item = _mapping(entry, f"tasks[{index}]")
    title = str(item.get("title", "")).strip()
    if not title:
        raise ValueError(f"tasks[{index}] 缺少 title")
    raw_minutes = item.get("estimated_minutes")
    has_minutes = raw_minutes is not None
    if not has_minutes:
        minutes = DEFAULT_UNCERTAIN_MINUTES
        duration_type = DurationType.UNCERTAIN
    else:
        if isinstance(raw_minutes, bool):
            raise ValueError(f"tasks[{index}].estimated_minutes 必须是整数")
        minutes = int(raw_minutes)
        raw_type = item.get("duration_type", "predictable")
        try:
            duration_type = DurationType(raw_type)
        except ValueError as exc:
            raise ValueError(
                f"tasks[{index}].duration_type 必须是 predictable/uncertain，收到 {raw_type!r}"
            ) from exc
    kwargs: dict[str, Any] = dict(
        title=title,
        estimated_minutes=minutes,
        id=str(item.get("id") or assigned_id),
        duration_type=duration_type,
        category=str(item.get("category") or ""),
        notes=str(item.get("notes") or ""),
    )
    raw_priority = item.get("priority")
    if raw_priority is not None:
        try:
            kwargs["priority"] = Priority(raw_priority)
        except ValueError as exc:
            raise ValueError(
                f"tasks[{index}].priority 必须是 high/medium/low，收到 {raw_priority!r}"
            ) from exc
    raw_deadline = item.get("deadline")
    if raw_deadline is not None:
        if isinstance(raw_deadline, datetime):
            kwargs["deadline"] = raw_deadline
        else:
            try:
                kwargs["deadline"] = datetime.fromisoformat(str(raw_deadline))
            except ValueError as exc:
                raise ValueError(
                    f"tasks[{index}].deadline 必须是 ISO datetime，收到 {raw_deadline!r}"
                ) from exc
    raw_start = item.get("preferred_start")
    raw_end = item.get("preferred_end")
    if raw_start is not None or raw_end is not None:
        kwargs["preferred_start"] = (
            _clock(str(raw_start), f"tasks[{index}].preferred_start") if raw_start is not None else None
        )
        kwargs["preferred_end"] = (
            _clock(str(raw_end), f"tasks[{index}].preferred_end") if raw_end is not None else None
        )
    raw_days = item.get("preferred_days")
    if raw_days is not None:
        kwargs["preferred_days"] = list(raw_days)
    return TaskInput(**kwargs)


def build_questionnaire(
    payload: Mapping[str, Any],
    *,
    week_start: date | None = None,
    confirmed_fields: Iterable[str] = (),
) -> QuestionnaireBuild:
    """Convert B's questionnaire payload into a validated QuestionnaireData.

    Only fields actually present in ``payload`` are treated as confirmed.
    Missing scheduling constraints (``work_days``, ``energy_peak``, rest
    periods, routines) are left to the model defaults and are *not* guessed:
    they simply stay out of ``confirmed_fields`` so the consultation
    controller can still ask about them.
    """
    payload = _mapping(payload, "payload")
    confirmed: set[str] = set(confirmed_fields)

    goals = [str(goal).strip() for goal in payload.get("goals", []) if str(goal).strip()]
    if payload.get("goals") is not None:
        confirmed.add("goals")

    # ---- tasks -----------------------------------------------------------
    raw_tasks = payload.get("tasks", [])
    if raw_tasks is None:
        raw_tasks = []
    if not isinstance(raw_tasks, (list, tuple)):
        raise TypeError(f"tasks 必须是列表，收到 {type(raw_tasks).__name__}")

    used_ids: set[str] = set()
    for entry in raw_tasks:
        if isinstance(entry, Mapping) and entry.get("id"):
            task_id = str(entry["id"]).strip()
            if task_id:
                used_ids.add(task_id)
    counter = 1
    tasks: list[TaskInput] = []
    estimated_ids: set[str] = set()
    for index, entry in enumerate(raw_tasks):
        while f"t{counter}" in used_ids:
            counter += 1
        task = _task_from_entry(entry, index, f"t{counter}")
        tasks.append(task)
        used_ids.add(task.id)
        counter += 1
        if isinstance(entry, str) or (
            isinstance(entry, Mapping) and entry.get("estimated_minutes") is None
        ):
            estimated_ids.add(task.id)
    if raw_tasks:
        confirmed.add("tasks")

    # ---- fixed commitments (deduplicated) --------------------------------
    raw_fixed = payload.get("fixed_commitments", [])
    if raw_fixed is None:
        raw_fixed = []
    if not isinstance(raw_fixed, (list, tuple)):
        raise TypeError(f"fixed_commitments 必须是列表，收到 {type(raw_fixed).__name__}")
    fixed: list[FixedCommitment] = []
    seen_fixed: set[tuple[str, datetime, datetime]] = set()
    for index, entry in enumerate(raw_fixed):
        commitment = _fixed_commitment(_mapping(entry, f"fixed_commitments[{index}]"))
        key = (commitment.title, commitment.start, commitment.end)
        if key in seen_fixed:
            continue
        seen_fixed.add(key)
        fixed.append(commitment)
    if raw_fixed:
        confirmed.add("fixed_commitments")

    # ---- rest periods ----------------------------------------------------
    raw_rest = payload.get("rest_periods", [])
    if raw_rest is None:
        raw_rest = []
    if not isinstance(raw_rest, (list, tuple)):
        raise TypeError(f"rest_periods 必须是列表，收到 {type(raw_rest).__name__}")
    rests: list[RestPeriod] = []
    for index, entry in enumerate(raw_rest):
        item = _mapping(entry, f"rest_periods[{index}]")
        rests.append(
            RestPeriod(
                title=str(item.get("title", "")),
                days=list(item.get("days", [])),
                start_time=str(item.get("start", "")),
                end_time=str(item.get("end", "")),
            )
        )
    if raw_rest:
        confirmed.add("rest_periods")

    # ---- predictable routines -------------------------------------------
    raw_routines = payload.get("predictable_routines", [])
    if raw_routines is None:
        raw_routines = []
    if not isinstance(raw_routines, (list, tuple)):
        raise TypeError(f"predictable_routines 必须是列表，收到 {type(raw_routines).__name__}")
    routines: list[PredictableRoutine] = []
    for index, entry in enumerate(raw_routines):
        item = _mapping(entry, f"predictable_routines[{index}]")
        routines.append(
            PredictableRoutine(
                title=str(item.get("title", "")),
                weekdays=list(item.get("weekdays", [])),
                estimated_minutes=int(item.get("estimated_minutes", 0)),
                preferred_start=(
                    str(item["preferred_start"]) if item.get("preferred_start") is not None else None
                ),
                preferred_end=(
                    str(item["preferred_end"]) if item.get("preferred_end") is not None else None
                ),
            )
        )
    if raw_routines:
        confirmed.add("predictable_routines")

    # ---- work window -----------------------------------------------------
    kwargs: dict[str, Any] = {}
    hours = payload.get("preferred_work_hours")
    if hours is not None:
        hours = _mapping(hours, "preferred_work_hours")
        kwargs["preferred_work_start"] = str(hours.get("start", ""))
        kwargs["preferred_work_end"] = str(hours.get("end", ""))
        confirmed.update({"preferred_work_start", "preferred_work_end"})
    else:
        if payload.get("preferred_work_start") is not None:
            kwargs["preferred_work_start"] = str(payload["preferred_work_start"])
            confirmed.add("preferred_work_start")
        if payload.get("preferred_work_end") is not None:
            kwargs["preferred_work_end"] = str(payload["preferred_work_end"])
            confirmed.add("preferred_work_end")

    # Only confirmed values are passed on; everything else keeps its default.
    if payload.get("work_days") is not None:
        kwargs["work_days"] = list(payload["work_days"])
        confirmed.add("work_days")
    if payload.get("energy_peak") not in (None, ""):
        kwargs["energy_peak"] = str(payload["energy_peak"])
        confirmed.add("energy_peak")
    if payload.get("habits") is not None:
        kwargs["habits"] = [str(habit) for habit in payload["habits"]]
        confirmed.add("habits")
    if payload.get("challenges") is not None:
        kwargs["challenges"] = [str(item) for item in payload["challenges"]]
        confirmed.add("challenges")
    if payload.get("notes") is not None:
        kwargs["notes"] = str(payload["notes"])
        confirmed.add("notes")
    if payload.get("name") is not None:
        kwargs["name"] = str(payload["name"])
        confirmed.add("name")

    raw_week_start = payload.get("week_start")
    if week_start is None and raw_week_start is not None:
        week_start = date.fromisoformat(str(raw_week_start))
    if week_start is None:
        week_start = date.today()

    questionnaire = QuestionnaireData(
        goals=goals,
        tasks=tasks,
        fixed_commitments=fixed,
        rest_periods=rests,
        predictable_routines=routines,
        week_start=week_start,
        **kwargs,
    )
    return QuestionnaireBuild(
        questionnaire=questionnaire,
        confirmed_fields=frozenset(confirmed),
        estimated_task_ids=frozenset(estimated_ids),
    )


def _previous_completed(previous: Iterable[dict] | None) -> dict[str, bool]:
    completed: dict[str, bool] = {}
    if previous is None:
        return completed
    for entry in previous:
        task_id = entry.get("id")
        if task_id and entry.get("completed") is True:
            completed[str(task_id)] = True
    return completed


def schedule_to_dicts(
    result: ScheduleResult,
    questionnaire: QuestionnaireData,
    *,
    previous: Iterable[dict] | None = None,
) -> list[dict]:
    """Convert a ScheduleResult into the dicts B's planner renders.

    Fixed commitments are re-added from ``questionnaire`` (once each) with
    ``is_fixed=True``. Rest periods stay out of the output entirely; their
    protection is enforced by the scheduler, and nothing in ``result.items``
    can overlap them. ``completed`` is carried over from ``previous`` by id.
    """
    completed = _previous_completed(previous)

    entries: list[dict] = []
    for item in result.items:
        entries.append(
            {
                "id": item.task_id,
                "title": item.task.title,
                "date": item.start.date().isoformat(),
                "start": item.start.strftime("%H:%M"),
                "end": item.end.strftime("%H:%M"),
                "category": item.task.category or "Task",
                "completed": completed.get(item.task_id, item.completed),
                "is_fixed": False,
            }
        )

    for index, commitment in enumerate(questionnaire.fixed_commitments):
        entries.append(
            {
                "id": f"{FIXED_ID_PREFIX}_{index}",
                "title": commitment.title,
                "date": commitment.start.date().isoformat(),
                "start": commitment.start.strftime("%H:%M"),
                "end": commitment.end.strftime("%H:%M"),
                "category": "Commitment",
                "completed": False,
                "is_fixed": True,
            }
        )

    entries.sort(
        key=lambda entry: (
            entry["date"],
            entry["start"],
            entry["end"],
            entry["title"],
        )
    )
    for entry in entries:
        for key in SCHEDULE_FIELDS:
            if key not in entry:
                raise RuntimeError(f"schedule dict 缺少字段 {key!r}")
    return entries


def unscheduled_to_dicts(result: ScheduleResult) -> list[dict]:
    """Keep unscheduled tasks with their reasons (B shows titles; we keep both)."""
    return [
        {"id": unscheduled.task.id, "title": unscheduled.task.title, "reason": unscheduled.reason}
        for unscheduled in result.unscheduled_tasks
    ]


def plan_week(
    questionnaire: QuestionnaireData,
    *,
    now: datetime | None = None,
    locked_items: Iterable[Any] | None = None,
    previous: Iterable[dict] | None = None,
) -> WeekPlan:
    """Schedule one week and convert everything in a single stable call."""
    result = build_schedule(questionnaire, now=now, locked_items=locked_items)
    schedule = schedule_to_dicts(result, questionnaire, previous=previous)
    unscheduled = unscheduled_to_dicts(result)
    return WeekPlan(
        result=result,
        schedule=schedule,
        unscheduled=unscheduled,
        warnings=list(result.warnings),
    )
