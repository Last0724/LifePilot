"""Chat processing layer for LifePilot (Phase 2, UI-independent).

Turns free-form chat messages into structured scheduling data without ever
touching Streamlit, the frontend, or the scheduler directly.

Public API
----------
``handle_chat_message(message, state=None, *, client=None) -> dict``
    Process one user message against the current consultation state and
    return ``{"reply", "state", "extracted_fields", "missing_fields",
    "ready_for_confirmation", "provider"}``. ``state`` is a JSON-friendly
    dict; pass the previous ``state`` back on every turn to accumulate.

``build_confirmed_schedule(state, confirmed_fields=None, *, now=None) -> dict``
    Turn the accumulated facts into a real schedule via
    ``ui.integration.plan_week`` (which calls ``core.scheduler.build_schedule``).
    Returns ``{"schedule": [...], "unscheduled": [...], "warnings": [...]}``.

Design notes
------------
* DeepSeek only extracts facts and (optionally) phrases follow-up questions.
  Python validates every extracted value against the shared models, merges
  by stable id, and owns all field state (resolved / unknown / unresolved).
* Multi-round state is preserved through ``ConsultationController.to_state``
  / ``from_state`` (the controller snapshot is stored in ``state``), so no
  per-turn rebuild can lose question sequencing or re-ask answered fields.
* Task identity is a stable ``chat_id`` (``task_1``, ``task_2``, ...).
  Updates reuse the id; removals reference the id or an unambiguous title.
  Ambiguous references are never guessed: the user is asked instead.
* On API failure the raw message is always kept under ``unrecognized`` and
  the deterministic parsers of ``core.ai_consultant`` still run; nothing that
  could not be verified is ever marked resolved.
"""

from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta
from typing import Any, Mapping

from core.ai_client import AIError, DeepSeekClient
from core.ai_consultant import (
    REQUIRED_FIELDS,
    ConsultationController,
    _parse_energy_peak,
    _parse_predictable_routine,
    _parse_rest_period,
    _parse_weekdays,
    _validate_predictable_routine,
    _validate_rest_period,
    _WEEKDAY_NAME_PATTERN,
    _WEEKDAY_NAME_RANGE_PATTERN,
    _WEEKDAY_NUMBER_RANGE_PATTERN,
)
from core.models import (
    DurationType,
    FixedCommitment,
    ModelError,
    PredictableRoutine,
    Priority,
    QuestionnaireData,
    RestPeriod,
    TaskInput,
)
from core.prompts import FIELD_DESCRIPTIONS
from ui.integration import DEFAULT_UNCERTAIN_MINUTES, plan_week

__all__ = ["handle_chat_message", "build_confirmed_schedule", "DEFAULT_TASK_MINUTES"]

# Matches the C1 bridge convention: tasks without a duration become
# UNCERTAIN 45-minute estimates (the scheduler applies the 20% buffer).
DEFAULT_TASK_MINUTES = DEFAULT_UNCERTAIN_MINUTES

_STATE_VERSION = 1

_LIST_FIELDS = (
    "tasks",
    "fixed_commitments",
    "rest_periods",
    "predictable_routines",
)
_SCALAR_FIELDS = (
    "preferred_work_start",
    "preferred_work_end",
    "work_days",
    "energy_peak",
)
_TEXT_LIST_FIELDS = ("goals", "habits", "challenges")

# Only these facts are needed to generate a schedule. Goals, routines,
# work_days and energy_peak are useful context but optional: an unanswered
# optional field must never block the structured-confirmation step.
_CHAT_REQUIRED_FIELDS = (
    "tasks",
    "fixed_commitments",
    "preferred_work_start",
    "preferred_work_end",
)


_PRIORITY_MAP = {
    "high": Priority.HIGH,
    "medium": Priority.MEDIUM,
    "low": Priority.LOW,
}

_CHAT_ID_PREFIXES = {
    "tasks": "task",
    "fixed_commitments": "fix",
    "rest_periods": "rest",
    "predictable_routines": "routine",
}

_EXTRACT_SYSTEM_PROMPT = (
    "You are the extraction engine of LifePilot, a personal productivity "
    "planner. You extract structured scheduling facts from one free-form "
    "chat message. You never invent facts, times, dates or durations the "
    "user did not state. You always reply with exactly one JSON object and "
    "nothing else."
)

_EXTRACT_PROMPT_TEMPLATE = """Extract scheduling facts from the user's latest chat message.

Target week: the week starting {week_start} (Monday).
Weekday table (0 = Monday, 6 = Sunday):
  0 = {mon}, 1 = {tue}, 2 = {wed}, 3 = {thu}, 4 = {fri}, 5 = {sat}, 6 = {sun}

Facts already confirmed so far (JSON). Every item carries a stable "chat_id".
Use these ids when the user updates or removes an existing item. If the user
mentions something new with the same title as an existing item but clearly
means a different one, treat it as a NEW item (no id):
{facts}

Conversation so far (oldest first):
{history}

Latest user message:
{message}

Reply with exactly this JSON shape:
{{
  "add_or_update": {{
    "tasks": [
      {{"id": "task_1 or null", "operation": "add|update or null",
        "title": "...", "estimated_minutes": 45 or null,
        "deadline": "YYYY-MM-DD or null", "day_of_week": 0-6 or null,
        "preferred_days": [0-6] or null,
        "preferred_start": "HH:MM or null", "preferred_end": "HH:MM or null",
        "priority": "high|medium|low or null", "importance_rank": 1-999 or null,
        "category": "study|work|health|... or null", "notes": "..."}}
    ],
    "fixed_commitments": [
      {{"id": "fix_1 or null", "operation": "add|update or null",
        "title": "...", "day_of_week": 0-6,
        "start": "HH:MM", "end": "HH:MM", "location": ""}}
    ],
    "rest_periods": [
      {{"id": "rest_1 or null", "operation": "add|update or null",
        "title": "...", "days": [0-6],
        "start_time": "HH:MM", "end_time": "HH:MM"}}
    ],
    "predictable_routines": [
      {{"id": "routine_1 or null", "operation": "add|update or null",
        "title": "...", "weekdays": [0-6],
        "estimated_minutes": N, "preferred_start": "HH:MM or null",
        "preferred_end": "HH:MM or null"}}
    ],
    "goals": ["..."], "habits": ["..."], "challenges": ["..."], "notes": "...",
    "preferred_work_start": "HH:MM or null",
    "preferred_work_end": "HH:MM or null",
    "work_days": [0-6] or null,
    "energy_peak": "morning|afternoon|evening|flexible or null"
  }},
  "remove": {{
    "tasks": ["task_1 or title..."], "fixed_commitments": [],
    "rest_periods": [], "predictable_routines": []
  }},
  "explicitly_none": ["fixed_commitments", "rest_periods", "..."],
  "unknown": ["energy_peak", "..."],
  "ambiguous": null
}}

Rules:
- Only include a field when this message actually provides information about
  it. Leave every other field absent or null.
- Corrections must reuse the existing chat_id from the facts above and set
  "operation": "update". Never set operation="update" (and never reuse an id)
  for a brand-new item, even one whose title already exists: a same-title but
  different item is always added as a NEW item with no id.
- A fixed_commitment needs a concrete start and end time. If the user gave a
  day but no times, do NOT invent them: leave the commitment out so Python
  can ask for the missing times.
- Map "周一至周五" / "Monday to Friday" / "1-5" to weekdays [0,1,2,3,4].
- Dates: only the target week exists; convert day_of_week to a date via the
  table above, and never output dates outside the target week.
- explicitly_none: use when the user clearly states they have none of that
  field ("no classes", "no fixed commitments", "没有固定安排").
- unknown: use when the user says they do not know / it does not matter.
- ambiguous: when you cannot tell which existing item the user means by an
  update or removal, leave that item out of add_or_update/remove and write
  one short clarifying question here instead.
- Return raw JSON. No markdown fences, no commentary."""


def _next_monday(today: date | None = None) -> date:
    today = today or date.today()
    return today + timedelta(days=(7 - today.weekday()) % 7)


def _default_state(week_start: date) -> dict[str, Any]:
    return {
        "version": _STATE_VERSION,
        "week_start": week_start.isoformat(),
        "facts": {
            "tasks": [],
            "fixed_commitments": [],
            "rest_periods": [],
            "predictable_routines": [],
            "goals": [],
            "habits": [],
            "challenges": [],
            "notes": "",
        },
        "field_states": {
            "resolved": [],
            "unknown": [],
            "unresolved": list(REQUIRED_FIELDS),
        },
        "seq": {"task": 0, "fix": 0, "rest": 0, "routine": 0},
        "controller_state": {},
        "history": [],
        "unrecognized": [],
        "ambiguous": [],
        "provider_history": [],
        "optional_asked": [],
        "last_input": "",
        "last_reply": "",
    }


# ---------------------------------------------------------------------------
# Interface A
# ---------------------------------------------------------------------------


def handle_chat_message(
    message: str,
    state: Mapping[str, Any] | None = None,
    *,
    client: DeepSeekClient | None = None,
) -> dict[str, Any]:
    """Process one chat message and return the updated conversation state."""
    state = _normalize_state(state)
    message = (message or "").strip()

    if not message:
        return _respond("请告诉我你这周的计划，或者继续补充信息。", state, provider="fallback")

    # A rerun of the same message (Streamlit double-submit) must not merge twice.
    if state["last_input"] == message and state.get("last_reply"):
        return _respond(
            state["last_reply"],
            state,
            provider=state["provider_history"][-1]
            if state["provider_history"]
            else "fallback",
        )

    state["history"].append({"role": "user", "content": message})
    state["ambiguous"] = []

    effective_client = client or DeepSeekClient()
    extraction, provider = _extract(message, state, effective_client)

    if provider == "fallback":
        state["provider_history"].append("fallback")
        state["unrecognized"].append(message)
    else:
        state["provider_history"].append("deepseek")

    ambiguous: list[str] = []
    if (extraction or {}).get("ambiguous"):
        ambiguous.append(str((extraction or {})["ambiguous"]))
    applied: list[str] = []
    if ambiguous:
        # Never guess which item the user meant: apply nothing, ask instead.
        state["_last_extracted"] = {}
    else:
        applied = _merge(state, extraction or {})
    ambiguous.extend(state["ambiguous"])

    # The LLM extraction is probabilistic; an explicit working week in the
    # user's own words is deterministic and always wins (latest statement).
    explicit_work_days = _explicit_work_days(message)
    if explicit_work_days is not None:
        state["facts"]["work_days"] = explicit_work_days
        _update_field_states(state, {"work_days"}, set())
        snapshot = dict(state.get("_last_extracted") or {})
        snapshot["work_days"] = explicit_work_days
        state["_last_extracted"] = snapshot
        if "work_days" not in applied:
            applied.append("work_days")

    goal_applied = _apply_goal_answer(state, message)
    if goal_applied and goal_applied not in applied:
        applied.append(goal_applied)

    state["controller_state"] = _sync_controller_state(state, effective_client)

    missing = [f for f in _CHAT_REQUIRED_FIELDS if f in state["field_states"]["unresolved"]]
    ready = not missing

    questions = _next_questions(state, effective_client) if not ready else []

    optional_note = None
    if ready and "goals" in state["field_states"]["unresolved"]:
        asked = state.setdefault("optional_asked", [])
        if "goals" not in asked:
            asked.append("goals")
            optional_note = (
                "如果有想长期坚持的目标（可选），可以告诉我；"
                "没有的话直接确认即可。"
            )

    reply = _compose_reply(
        message, provider, applied, extraction or {}, missing, questions, ambiguous
    )
    if optional_note:
        reply = f"{reply}\n\n{optional_note}"
    state["last_input"] = message
    state["last_reply"] = reply

    return _respond(reply, state, provider=provider)


def _respond(
    reply: str, state: dict[str, Any], *, provider: str
) -> dict[str, Any]:
    return {
        "reply": reply,
        "state": state,
        "extracted_fields": state.get("_last_extracted", {}),
        "missing_fields": [
            f for f in _CHAT_REQUIRED_FIELDS if f in state["field_states"]["unresolved"]
        ],
        "ready_for_confirmation": not any(
            f in state["field_states"]["unresolved"] for f in _CHAT_REQUIRED_FIELDS
        ),
        "provider": provider,
    }


def _normalize_state(state: Mapping[str, Any] | None) -> dict[str, Any]:
    if state is None or not isinstance(state, Mapping):
        return _default_state(_next_monday())
    if state.get("version") != _STATE_VERSION:
        return _default_state(_next_monday())
    result: dict[str, Any] = {
        "version": _STATE_VERSION,
        "week_start": str(state.get("week_start") or _next_monday().isoformat()),
        "facts": dict(state.get("facts") or {}),
        "field_states": {
            "resolved": list(state.get("field_states", {}).get("resolved", [])),
            "unknown": list(state.get("field_states", {}).get("unknown", [])),
            "unresolved": list(
                state.get("field_states", {}).get("unresolved", REQUIRED_FIELDS)
            ),
        },
        "seq": dict(state.get("seq") or {}),
        "controller_state": dict(state.get("controller_state") or {}),
        "history": list(state.get("history") or []),
        "unrecognized": list(state.get("unrecognized") or []),
        "ambiguous": list(state.get("ambiguous") or []),
        "provider_history": list(state.get("provider_history") or []),
        "optional_asked": list(state.get("optional_asked") or []),
        "last_input": str(state.get("last_input") or ""),
        "last_reply": str(state.get("last_reply") or ""),
    }
    for field in _LIST_FIELDS:
        result["facts"].setdefault(field, [])
    for field in _TEXT_LIST_FIELDS:
        result["facts"].setdefault(field, [])
    result["facts"].setdefault("notes", "")
    for key in ("task", "fix", "rest", "routine"):
        result["seq"].setdefault(key, 0)
    return result


# ---------------------------------------------------------------------------
# Extraction (DeepSeek, with deterministic fallback)
# ---------------------------------------------------------------------------


def _extract(
    message: str, state: dict[str, Any], client: DeepSeekClient
) -> tuple[dict[str, Any] | None, str]:
    """Extract facts from one message: LLM first, deterministic parsers on error."""
    prompt = _build_extract_prompt(message, state)
    try:
        payload = client.chat_json(
            [
                {"role": "system", "content": _EXTRACT_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ]
        )
    except AIError:
        payload = None
    if isinstance(payload, Mapping):
        normalized = _normalize_extraction(payload, state)
        if normalized is None:  # unusable payload counts as an API failure
            return _fallback_extract(message, state), "fallback"
        return normalized, "deepseek"
    return _fallback_extract(message, state), "fallback"


def _fallback_extract(
    message: str, state: dict[str, Any],
) -> dict[str, Any]:
    """Deterministic best-effort extraction (no LLM, never guesses)."""
    result: dict[str, Any] = {}
    rest = _parse_rest_period(message)
    if rest:
        validated = _validate_rest_period(rest)
        if validated:
            result["rest_periods"] = [validated]
    routine = _parse_predictable_routine(message)
    if routine:
        validated = _validate_predictable_routine(routine)
        if validated:
            result["predictable_routines"] = [validated]
    weekdays = _parse_weekdays(message)
    if weekdays:
        result["work_days"] = list(weekdays)
    energy = _parse_energy_peak(message)
    if energy:
        result["energy_peak"] = energy
    return result


def _build_extract_prompt(message: str, state: dict[str, Any]) -> str:
    week_start = date.fromisoformat(state["week_start"])
    days = [week_start + timedelta(days=i) for i in range(7)]
    facts = {
        "week_start": state["week_start"],
        "tasks": state["facts"]["tasks"],
        "fixed_commitments": state["facts"]["fixed_commitments"],
        "rest_periods": state["facts"]["rest_periods"],
        "predictable_routines": state["facts"]["predictable_routines"],
        "goals": state["facts"]["goals"],
        "preferred_work_start": state["facts"].get("preferred_work_start"),
        "preferred_work_end": state["facts"].get("preferred_work_end"),
        "work_days": state["facts"].get("work_days"),
        "energy_peak": state["facts"].get("energy_peak"),
    }
    history = "\n".join(
        f"{item['role']}: {item['content']}"
        for item in state["history"][-8:]
    )
    return _EXTRACT_PROMPT_TEMPLATE.format(
        week_start=week_start.isoformat(),
        mon=days[0].isoformat(),
        tue=days[1].isoformat(),
        wed=days[2].isoformat(),
        thu=days[3].isoformat(),
        fri=days[4].isoformat(),
        sat=days[5].isoformat(),
        sun=days[6].isoformat(),
        facts=_as_json(facts),
        history=history or "(none)",
        message=message,
    )


def _as_json(value: Any) -> str:
    import json

    return json.dumps(value, ensure_ascii=False, indent=2, default=str)


# ---------------------------------------------------------------------------
# Normalization (LLM output -> validated fact dicts, Python-owned)
# ---------------------------------------------------------------------------


def _normalize_extraction(
    payload: Mapping[str, Any], state: dict[str, Any]
) -> dict[str, Any] | None:
    """Validate the model payload; return a safe normalized dict or None."""
    if not isinstance(payload, Mapping):
        return None
    week_start = date.fromisoformat(state["week_start"])
    add = payload.get("add_or_update") or {}
    remove = payload.get("remove") or {}
    if not isinstance(add, Mapping) or not isinstance(remove, Mapping):
        return None

    normalized: dict[str, Any] = {
        "tasks": _normalize_task_entries(add.get("tasks"), week_start),
        "fixed_commitments": _normalize_fixed_entries(add.get("fixed_commitments")),
        "rest_periods": _normalize_rest_entries(add.get("rest_periods")),
        "predictable_routines": _normalize_routine_entries(
            add.get("predictable_routines")
        ),
        "goals": _clean_text_list(add.get("goals")),
        "habits": _clean_text_list(add.get("habits")),
        "challenges": _clean_text_list(add.get("challenges")),
        "notes": _clean_text(add.get("notes")),
        "preferred_work_start": _clean_hhmm(add.get("preferred_work_start")),
        "preferred_work_end": _clean_hhmm(add.get("preferred_work_end")),
        "work_days": _clean_weekday_list(add.get("work_days")),
        "energy_peak": _clean_energy(add.get("energy_peak")),
        "remove": {
            "tasks": _clean_text_list(remove.get("tasks")),
            "fixed_commitments": _clean_text_list(remove.get("fixed_commitments")),
            "rest_periods": _clean_text_list(remove.get("rest_periods")),
            "predictable_routines": _clean_text_list(
                remove.get("predictable_routines")
            ),
        },
        "explicitly_none": [
            f for f in _clean_text_list(payload.get("explicitly_none"))
            if f in REQUIRED_FIELDS
        ],
        "unknown": [
            f for f in _clean_text_list(payload.get("unknown"))
            if f in REQUIRED_FIELDS
        ],
        "ambiguous": _clean_text(payload.get("ambiguous")),
    }
    return normalized


def _normalize_task_entries(raw: Any, week_start: date) -> list[dict[str, Any]]:
    if not isinstance(raw, (list, tuple)):
        return []
    entries: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        title = _clean_text(item.get("title"))
        if not title:
            continue
        minutes = _clean_int(item.get("estimated_minutes"))
        deadline = _clean_deadline(item.get("deadline"))
        preferred_start = _clean_hhmm(item.get("preferred_start"))
        preferred_end = _clean_hhmm(item.get("preferred_end"))
        if (preferred_start is None) != (preferred_end is None):
            preferred_start = preferred_end = None
        preferred_days = _clean_weekday_list(item.get("preferred_days"))
        if preferred_days is None and isinstance(item.get("day_of_week"), int):
            day = _clean_weekday_list([item.get("day_of_week")])
            preferred_days = day
        # Validate a constructed TaskInput so invalid combos never enter facts.
        try:
            TaskInput(
                title=title,
                estimated_minutes=minutes if minutes is not None else DEFAULT_TASK_MINUTES,
                priority=_PRIORITY_MAP.get(_clean_text(item.get("priority")) or "", Priority.MEDIUM),
                deadline=deadline,
                category=_clean_text(item.get("category")) or "",
                preferred_period=_clean_text(item.get("preferred_period")) or "",
                notes=_clean_text(item.get("notes")) or "",
                duration_type=(
                    DurationType.PREDICTABLE
                    if _clean_text(item.get("duration_type")) == "predictable"
                    else DurationType.UNCERTAIN
                ),
                preferred_start=preferred_start,
                preferred_end=preferred_end,
                preferred_days=preferred_days,
                importance_rank=_clean_int(item.get("importance_rank")),
            )
        except (ModelError, TypeError, ValueError):
            continue
        entries.append(
            {
                "id": _clean_text(item.get("id")),
                "operation": _clean_text(item.get("operation")),
                "title": title,
                "estimated_minutes": minutes,
                "deadline": deadline.isoformat() if deadline else None,
                "priority": _clean_text(item.get("priority")),
                "category": _clean_text(item.get("category")),
                "preferred_period": _clean_text(item.get("preferred_period")),
                "notes": _clean_text(item.get("notes")),
                "duration_type": _clean_text(item.get("duration_type")),
                "preferred_start": preferred_start,
                "preferred_end": preferred_end,
                "preferred_days": preferred_days,
                "importance_rank": _clean_int(item.get("importance_rank")),
            }
        )
    return entries


def _normalize_fixed_entries(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, (list, tuple)):
        return []
    entries: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        title = _clean_text(item.get("title"))
        start = _clean_hhmm(item.get("start"))
        end = _clean_hhmm(item.get("end"))
        if not title or not start or not end:
            continue
        if start >= end:
            continue
        day_of_week = item.get("day_of_week")
        if not isinstance(day_of_week, int) or not 0 <= day_of_week <= 6:
            continue
        entries.append(
            {
                "id": _clean_text(item.get("id")),
                "operation": _clean_text(item.get("operation")),
                "title": title,
                "day_of_week": day_of_week,
                "start": start,
                "end": end,
                "location": _clean_text(item.get("location")) or "",
            }
        )
    return entries


def _normalize_rest_entries(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, (list, tuple)):
        return []
    entries: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        validated = _validate_rest_period(item)
        if validated:
            entries.append(
                {
                    "id": _clean_text(item.get("id")),
                    "operation": _clean_text(item.get("operation")),
                    **validated,
                }
            )
    return entries


def _normalize_routine_entries(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, (list, tuple)):
        return []
    entries: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        validated = _validate_predictable_routine(item)
        if validated:
            entries.append(
                {
                    "id": _clean_text(item.get("id")),
                    "operation": _clean_text(item.get("operation")),
                    **validated,
                }
            )
    return entries


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _clean_text_list(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    return [text for item in value if (text := _clean_text(item))]


def _clean_int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if 1 <= value <= 999 else None


def _clean_hhmm(value: Any) -> str | None:
    text = _clean_text(value)
    if not text:
        return None
    if not re.fullmatch(r"(?:[01]?\d|2[0-3]):[0-5]\d", text):
        return None
    hour, minute = text.split(":")
    return f"{int(hour):02d}:{minute}"


def _clean_weekday_list(value: Any) -> list[int] | None:
    if not isinstance(value, (list, tuple)):
        return None
    days: set[int] = set()
    for item in value:
        if isinstance(item, bool) or not isinstance(item, int):
            return None
        if not 0 <= item <= 6:
            return None
        days.add(item)
    return sorted(days) if days else None


def _clean_energy(value: Any) -> str | None:
    text = (_clean_text(value) or "").lower()
    return text if text in ("morning", "afternoon", "evening", "flexible") else None


def _clean_deadline(value: Any) -> datetime | None:
    text = _clean_text(value)
    if not text:
        return None
    text = text.strip()
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M"):
        try:
            parsed = datetime.strptime(text, fmt)
            return parsed.replace(hour=23, minute=59) if fmt == "%Y-%m-%d" else parsed
        except ValueError:
            continue
    return None


# ---------------------------------------------------------------------------
# Deterministic work-day supplement
# ---------------------------------------------------------------------------

# A weekday phrase only means "these are my work days" when it is tied to a
# work/school context in the same clause. This keeps "周一、周三跑步" (an
# ordinary repeating activity) from silently narrowing the working week.
_WORK_CONTEXT_RE = re.compile(
    r"(工作|上班|办公|工作日|有课|上课|在校|课表|"
    r"work(?:ing)?|office|job|class(?:es)?)",
    re.IGNORECASE,
)
_CLAUSE_SEPARATOR_RE = re.compile(r"[。；;，,\n]")


def _clause_containing(text: str, position: int) -> str:
    """Return the comma/sentence clause that contains ``position``."""
    start = 0
    for match in _CLAUSE_SEPARATOR_RE.finditer(text):
        if match.start() <= position < match.end():
            return ""
        if match.start() > position:
            return text[start : match.start()]
        start = match.end()
    return text[start:]


def _explicit_work_days(message: str) -> list[int] | None:
    """Extract an explicitly stated working week, or return ``None``.

    Reuses ``core.ai_consultant._parse_weekdays`` (the single source of truth
    for weekday ranges such as ``1-5`` / ``Mon-Fri`` / ``周一至周五``); this
    helper only decides *whether* a phrase is about work days:

    * the whole message is a bare range ("Mon-Fri", "1-5"), or
    * the phrase shares a clause with a work/school keyword
      ("周一到周五工作", "Monday to Friday working").

    Clock times ("11:00-12:30") are excluded by the shared number-range
    pattern, and ordinary activity lists ("周一、周三跑步") are excluded by the
    missing work context.
    """
    text = message.strip()
    if not text:
        return None
    stripped = text.strip(" \t\r\n。.!！?？,，;；：:")

    spans: list[tuple[int, int, str, bool]] = []
    for match in _WEEKDAY_NAME_RANGE_PATTERN.finditer(text):
        spans.append((match.start(), match.end(), match.group(0), True))
    for match in _WEEKDAY_NUMBER_RANGE_PATTERN.finditer(text):
        spans.append((match.start(), match.end(), match.group(0), True))
    for match in _WEEKDAY_NAME_PATTERN.finditer(text):
        spans.append((match.start(), match.end(), match.group(0), False))

    days: set[int] = set()
    for start, _end, chunk, is_range in spans:
        clause = _clause_containing(text, start)
        bare_range = is_range and chunk.strip() == stripped
        if not bare_range and not _WORK_CONTEXT_RE.search(clause):
            continue
        parsed = _parse_weekdays(chunk)
        if parsed:
            days.update(parsed)
    return sorted(days) if days else None


# ---------------------------------------------------------------------------
# Long-term goals (optional, never blocking)
# ---------------------------------------------------------------------------

_GOAL_NONE_RE = re.compile(
    r"^(?:没有了?|没了|暂时没有|没有目标|没目标|无|none|nothing|no goals?|nope)"
    r"[。.!！~～\s]*$",
    re.IGNORECASE,
)
_GOAL_UNKNOWN_RE = re.compile(
    r"^(?:不知道|不清楚|不确定|跳过|不想说|随便|skip|don'?t know|not sure|no idea)"
    r"[。.!！~～\s]*$",
    re.IGNORECASE,
)
_GENERATE_INTENT_RE = re.compile(
    r"(?:生成|出个?日程|排个?日程|安排日程|就这些|就这样|完成了|可以了|确认|结束|"
    r"generate|confirm|that'?s it|that is all|go ahead)",
    re.IGNORECASE,
)


def _drop_pending_field(state: dict[str, Any], field: str) -> None:
    """Remove any pending question that targets ``field``."""
    controller_state = state.get("controller_state") or {}
    pending = controller_state.get("pending")
    if isinstance(pending, list):
        controller_state["pending"] = [
            question
            for question in pending
            if question.get("target_field") != field
        ]
    state["controller_state"] = controller_state


def _apply_goal_answer(state: dict[str, Any], message: str) -> str | None:
    """Resolve an asked long-term-goal question deterministically.

    The LLM sometimes files a bare answer such as "健身" under ``habits`` and
    leaves ``goals`` unresolved, which used to make the same question repeat
    forever. Once the goal question is the one that was asked, the answer is
    unambiguous: content, an explicit "none", or "I don't know".

    Returns ``"goals"`` when the field was updated, otherwise ``None``.
    """
    if "goals" not in state["field_states"]["unresolved"]:
        return None
    pending = list((state.get("controller_state") or {}).get("pending") or [])
    asked = any(
        question.get("target_field") == "goals" for question in pending
    ) or "goals" in (state.get("optional_asked") or [])
    if not asked:
        return None

    text = (message or "").strip()
    if not text or _GENERATE_INTENT_RE.search(text):
        # The user wants to move on: goals stay optional, never invented.
        return None

    snapshot = dict(state.get("_last_extracted") or {})
    if _GOAL_NONE_RE.match(text):
        state["facts"]["goals"] = []
        _update_field_states(state, {"goals"}, set())
        snapshot["goals"] = []
        state["_last_extracted"] = snapshot
        _drop_pending_field(state, "goals")
        return "goals"
    if _GOAL_UNKNOWN_RE.match(text):
        _update_field_states(state, set(), {"goals"})
        _drop_pending_field(state, "goals")
        return None

    if len(text) > 60:
        return None
    values = [part.strip(" 。.!！~～") for part in re.split(r"[、，,;/]", text)]
    values = [value for value in values if value]
    if not values:
        return None
    goals = list(state["facts"]["goals"])
    for value in values:
        if value not in goals:
            goals.append(value)
    state["facts"]["goals"] = goals
    _update_field_states(state, {"goals"}, set())
    snapshot["goals"] = goals
    state["_last_extracted"] = snapshot
    _drop_pending_field(state, "goals")
    return "goals"


# ---------------------------------------------------------------------------
# Merge (stable ids, Python-owned)
# ---------------------------------------------------------------------------


def _merge(state: dict[str, Any], extraction: dict[str, Any]) -> list[str]:
    """Merge one extraction into the facts; return the fields that changed."""
    facts = state["facts"]
    applied: set[str] = set()
    unknown_fields: set[str] = {
        field
        for field in extraction.get("unknown", [])
        if field
        in (
            *_LIST_FIELDS,
            *_SCALAR_FIELDS,
            *_TEXT_LIST_FIELDS,
            "notes",
        )
    }

    for field in extraction.get("explicitly_none", []):
        if field in _LIST_FIELDS or field in _TEXT_LIST_FIELDS:
            facts[field] = []
        elif field in _SCALAR_FIELDS:
            facts.pop(field, None)
        elif field == "notes":
            facts["notes"] = ""
        else:
            continue
        applied.add(field)

    for field in _LIST_FIELDS:
        entries = extraction.get(field, [])
        removes = extraction.get("remove", {}).get(field, [])
        if _merge_list(state, field, entries, removes):
            applied.add(field)

    for field in _TEXT_LIST_FIELDS:
        entries = extraction.get(field, [])
        if entries:
            existing = list(facts[field])
            for entry in entries:
                if entry not in existing:
                    existing.append(entry)
            facts[field] = existing
            applied.add(field)

    notes = extraction.get("notes")
    if notes is not None:
        facts["notes"] = notes
        applied.add("notes")

    for field in _SCALAR_FIELDS:
        value = extraction.get(field)
        if value is not None:
            facts[field] = value
            applied.add(field)

    _update_field_states(state, applied, unknown_fields)
    if applied or unknown_fields:
        snapshot: dict[str, Any] = {}
        for field in sorted(applied | unknown_fields):
            snapshot[field] = facts.get(field)
        state["_last_extracted"] = snapshot
    else:
        state["_last_extracted"] = {}
    return sorted(applied)


def _merge_list(
    state: dict[str, Any],
    field: str,
    entries: list[dict[str, Any]],
    removes: list[str],
) -> bool:
    """Merge validated entries into one list field; True when anything changed."""
    facts = state["facts"]
    prefix = _CHAT_ID_PREFIXES[field]
    current: list[dict[str, Any]] = list(facts[field])
    by_id: dict[str, dict[str, Any]] = {}
    by_title: dict[str, list[dict[str, Any]]] = {}
    for item in current:
        by_id[item["chat_id"]] = item
        key = _title_key(item.get("title"))
        by_title.setdefault(key, []).append(item)

    changed = False

    for entry in entries:
        op = entry.get("operation")
        entry_id = entry.get("id")
        title = entry.get("title")
        # Facts never carry the transient "id"/"operation" keys: id is only
        # a reference hint from the model, chat_id is the stable identity.
        clean = {
            k: v
            for k, v in entry.items()
            if v is not None and k not in ("id", "operation")
        }

        if entry_id and entry_id in by_id:
            updated = {**by_id[entry_id], **clean}
            updated["chat_id"] = entry_id
            by_id[entry_id] = updated
            changed = True
            continue

        if op == "update":
            # The model says this message modifies an existing item but did
            # not give a matching id: fall back to an unambiguous title match
            # and never guess when several items share the title.
            matches = by_title.get(_title_key(title or ""), []) if title else []
            if len(matches) == 1:
                existing = matches[0]
                updated = {**existing, **clean}
                updated["chat_id"] = existing["chat_id"]
                by_id[existing["chat_id"]] = updated
                changed = True
                continue
            if len(matches) > 1:
                state["ambiguous"].append(
                    f"有多个「{title}」，请告诉我要修改哪一个。"
                )
            else:
                state["ambiguous"].append(
                    f"没有找到「{title or entry_id}」，请告诉我要修改哪一个。"
                )
            continue

        # Add intent (or no reference at all): always a NEW item, even when
        # the title coincides with an existing one — the model is instructed
        # to use operation="update" when the user means the existing item.
        state["seq"][prefix] += 1
        new_id = f"{prefix}_{state['seq'][prefix]}"
        new_item = {**clean}
        new_item["chat_id"] = new_id
        by_id[new_id] = new_item
        changed = True

    for token in removes:
        if token in by_id:
            del by_id[token]
            changed = True
            continue
        matches = by_title.get(_title_key(token), [])
        if len(matches) == 1:
            del by_id[matches[0]["chat_id"]]
            changed = True
        elif len(matches) > 1:
            state["ambiguous"].append(f"有多个「{token}」，请告诉我要取消哪一个。")

    if changed:
        facts[field] = list(by_id.values())
    return changed


def _title_key(title: Any) -> str:
    return re.sub(r"\s+", " ", str(title or "")).strip().casefold()


def _update_field_states(
    state: dict[str, Any], applied: set[str], unknown_fields: set[str]
) -> None:
    """Move fields between resolved / unknown / unresolved based on this turn.

    ``applied`` fields were answered with real content (including an explicit
    "none": the content is an empty list). ``unknown_fields`` were answered
    with "I don't know" and must never be marked resolved nor asked again.
    """
    resolved = set(state["field_states"]["resolved"])
    unknown = set(state["field_states"]["unknown"])
    unresolved = set(state["field_states"]["unresolved"])
    for field in applied:
        resolved.add(field)
        unknown.discard(field)
        unresolved.discard(field)
    for field in unknown_fields:
        unknown.add(field)
        resolved.discard(field)
        unresolved.discard(field)
    state["field_states"] = {
        "resolved": sorted(resolved),
        "unknown": sorted(unknown),
        "unresolved": sorted(unresolved),
    }


# ---------------------------------------------------------------------------
# Controller snapshot (to_state / from_state, never rebuilt from scratch)
# ---------------------------------------------------------------------------


def _facts_to_questionnaire_mapping(state: dict[str, Any]) -> dict[str, Any]:
    facts = state["facts"]
    week_start = date.fromisoformat(state["week_start"])
    return {
        "goals": list(facts["goals"]),
        "tasks": [{"title": item["title"]} for item in facts["tasks"]],
        "fixed_commitments": [
            {
                "title": item["title"],
                "date": (week_start + timedelta(days=item["day_of_week"])).isoformat(),
                "start": item["start"],
                "end": item["end"],
            }
            for item in facts["fixed_commitments"]
        ],
        "rest_periods": [
            {k: v for k, v in item.items() if k != "chat_id"}
            for item in facts["rest_periods"]
        ],
        "predictable_routines": [
            {k: v for k, v in item.items() if k != "chat_id"}
            for item in facts["predictable_routines"]
        ],
        "preferred_work_start": facts.get("preferred_work_start"),
        "preferred_work_end": facts.get("preferred_work_end"),
        "work_days": facts.get("work_days"),
        "energy_peak": facts.get("energy_peak"),
        "habits": list(facts["habits"]),
        "challenges": list(facts["challenges"]),
        "notes": facts.get("notes") or "",
    }


def _sync_controller_state(
    state: dict[str, Any], client: DeepSeekClient
) -> dict[str, Any]:
    """Persist the controller snapshot through its public to_state/from_state API."""
    mapping = _facts_to_questionnaire_mapping(state)
    confirmed = set(state["field_states"]["resolved"])
    previous = state.get("controller_state") or {}
    if previous:
        controller = ConsultationController.from_state(
            previous, mapping, client=client, confirmed_fields=confirmed
        )
    else:
        controller = ConsultationController(
            mapping, client=client, confirmed_fields=confirmed
        )
    # Chat-level truth wins: explicit "none" answers are resolved-empty fields
    # which content inspection alone cannot detect.
    controller.resolved = sorted(state["field_states"]["resolved"])
    controller.unknown = sorted(state["field_states"]["unknown"])
    controller.unresolved = sorted(state["field_states"]["unresolved"])
    # Drop stale pending questions whose field was just resolved.
    controller._pending = [
        q for q in controller._pending if q.target_field in controller.unresolved
    ]
    return controller.to_state()


def _restore_controller(
    state: dict[str, Any], client: DeepSeekClient
) -> ConsultationController:
    mapping = _facts_to_questionnaire_mapping(state)
    controller = ConsultationController.from_state(
        state["controller_state"],
        mapping,
        client=client,
        confirmed_fields=set(state["field_states"]["resolved"]),
    )
    controller.resolved = sorted(state["field_states"]["resolved"])
    controller.unknown = sorted(state["field_states"]["unknown"])
    controller.unresolved = sorted(state["field_states"]["unresolved"])
    return controller


# ---------------------------------------------------------------------------
# Follow-up questions (controller phrasing, deterministic fallback)
# ---------------------------------------------------------------------------


def _next_questions(
    state: dict[str, Any], client: DeepSeekClient
) -> list[dict[str, Any]]:
    controller = _restore_controller(state, client)
    missing = [
        f for f in _CHAT_REQUIRED_FIELDS if f in state["field_states"]["unresolved"]
    ]
    if not missing:
        return []
    controller.unresolved = list(missing)
    draft = controller.next_round()
    questions = [
        {
            "id": q.id,
            "question": q.question,
            "target_field": q.target_field,
        }
        for q in draft.follow_up_questions
    ]
    if not questions:
        # Offline phrasing: deterministic questions from FIELD_DESCRIPTIONS.
        seq = controller._question_seq
        questions = []
        for offset, field in enumerate(missing[:2]):
            seq += 1
            questions.append(
                {
                    "id": f"q{seq}",
                    "question": _question_text(field),
                    "target_field": field,
                }
            )
        snapshot = controller.to_state()
        snapshot["question_seq"] = seq
        snapshot["question_targets"] = {
            **snapshot.get("question_targets", {}),
            **{q["id"]: q["target_field"] for q in questions},
        }
        snapshot["pending"] = questions
        state["controller_state"] = snapshot
    else:
        state["controller_state"] = controller.to_state()
    return questions[:2]


def _question_text(field: str) -> str:
    return FIELD_DESCRIPTIONS.get(field, f"Could you tell me about {field}?")


# ---------------------------------------------------------------------------
# Reply composition
# ---------------------------------------------------------------------------


def _compose_reply(
    message: str,
    provider: str,
    applied: list[str],
    extraction: dict[str, Any],
    missing: list[str],
    questions: list[dict[str, Any]],
    ambiguous: list[str],
) -> str:
    parts: list[str] = []

    if provider == "fallback":
        parts.append(
            "（DeepSeek API 暂时不可用，我改用内置规则尽力理解你的消息；"
            "原文已保留，未识别的部分不会假装理解。）"
        )
        if applied:
            parts.append("我记录到了：" + "、".join(applied) + "。")
        else:
            parts.append("抱歉，这条消息我暂时无法可靠解析，请换一种说法。")

    if ambiguous:
        parts.extend(ambiguous)
        return "\n\n".join(parts)

    if applied and provider == "deepseek":
        parts.append("明白了，我已经把这条信息更新到你的计划里。")

    if missing and questions:
        lines = ["还有几个信息想确认："]
        for index, question in enumerate(questions, start=1):
            lines.append(f"{index}. {question['question']}")
        parts.append("\n".join(lines))
    elif missing:
        parts.append("还有几项信息需要确认，请再补充一下。")
    elif not missing and not ambiguous:
        parts.append(
            "信息已经齐了，你可以回复“确认”，我马上为你生成这一周的计划。"
        )

    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Interface B
# ---------------------------------------------------------------------------


def build_confirmed_schedule(
    state: Mapping[str, Any],
    confirmed_fields: Any = None,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Build the real schedule from the accumulated facts (no demo data)."""
    state = _normalize_state(state)
    facts = state["facts"]
    week_start = date.fromisoformat(state["week_start"])

    tasks: list[TaskInput] = []
    for item in facts["tasks"]:
        minutes = item.get("estimated_minutes") or DEFAULT_TASK_MINUTES
        deadline = None
        if item.get("deadline"):
            try:
                deadline = datetime.fromisoformat(item["deadline"])
            except ValueError:
                deadline = None
        tasks.append(
            TaskInput(
                title=item["title"],
                estimated_minutes=minutes,
                priority=_PRIORITY_MAP.get(
                    (item.get("priority") or "").lower(), Priority.MEDIUM
                ),
                deadline=deadline,
                category=item.get("category") or "",
                preferred_period=item.get("preferred_period") or "",
                notes=item.get("notes") or "",
                duration_type=(
                    DurationType.PREDICTABLE
                    if item.get("duration_type") == "predictable"
                    else DurationType.UNCERTAIN
                ),
                preferred_start=item.get("preferred_start"),
                preferred_end=item.get("preferred_end"),
                preferred_days=item.get("preferred_days"),
                importance_rank=item.get("importance_rank"),
            )
        )

    fixed: list[FixedCommitment] = []
    for item in facts["fixed_commitments"]:
        day = week_start + timedelta(days=item["day_of_week"])
        fixed.append(
            FixedCommitment(
                title=item["title"],
                start=datetime.combine(day, time.fromisoformat(item["start"])),
                end=datetime.combine(day, time.fromisoformat(item["end"])),
                location=item.get("location") or "",
            )
        )

    rests = [
        RestPeriod(
            **{k: v for k, v in item.items() if k not in ("id", "chat_id", "operation")}
        )
        for item in facts["rest_periods"]
    ]
    routines = [
        PredictableRoutine(
            **{k: v for k, v in item.items() if k not in ("id", "chat_id", "operation")}
        )
        for item in facts["predictable_routines"]
    ]

    questionnaire = QuestionnaireData(
        name="",
        goals=list(facts["goals"]),
        tasks=tasks,
        fixed_commitments=fixed,
        preferred_work_start=facts.get("preferred_work_start") or "09:00",
        preferred_work_end=facts.get("preferred_work_end") or "22:00",
        work_days=facts.get("work_days") or [0, 1, 2, 3, 4, 5, 6],
        habits=list(facts["habits"]),
        challenges=list(facts["challenges"]),
        energy_peak=facts.get("energy_peak") or "unknown",
        notes=facts.get("notes") or "",
        week_start=week_start,
        rest_periods=rests,
        predictable_routines=routines,
    )

    plan = plan_week(questionnaire, now=now)
    return {
        "schedule": plan.schedule,
        "unscheduled": plan.unscheduled,
        "warnings": list(plan.result.warnings),
    }
