"""AI consultation logic for LifePilot.

Three public functions, matching the contract agreed with the Technical Lead::

    start_consultation(questionnaire)          -> ConsultationDraft (dict)
    finalize_profile(questionnaire, answers)   -> UserProfile (dict)
    build_fallback_profile(questionnaire)      -> UserProfile (dict)

ConsultationDraft::

    {
        "follow_up_questions": [
            {"id": "q1", "question": "..."},
            {"id": "q2", "question": "..."},
        ]
    }

UserProfile carries the seven content fields plus ``is_fallback``. The
fallback flag exists only on the profile, never on the draft.

``core/models.py`` has not landed yet, so questionnaire and profile values
are plain dictionaries here. Two details keep that temporary shape from
leaking into the rest of the app:

* ``_as_mapping`` accepts dicts, dataclasses and pydantic-style objects, so
  the real models can be swapped in without touching this module.
* ``_normalise_profile`` guarantees every documented key exists with the
  right type, so the scheduler can rely on the contract even when the model
  returns something sloppy.

An API failure never propagates. Every public function degrades to a
deterministic fallback.
"""

from __future__ import annotations

import dataclasses
import json
from typing import Any, Mapping

from core.ai_client import AIError, DeepSeekClient
from core.prompts import (
    ANALYSIS_PROMPT,
    MAX_FOLLOW_UP_QUESTIONS,
    MAX_WORK_BLOCK_MINUTES,
    MIN_WORK_BLOCK_MINUTES,
    PROFILE_PROMPT,
    SYSTEM_PROMPT,
)

__all__ = [
    "PROFILE_KEYS",
    "FOLLOW_UP_IDS",
    "build_fallback_profile",
    "finalize_profile",
    "start_consultation",
]

# The keys every UserProfile must carry, including the fallback marker.
# fixed_commitments is deliberately absent: the scheduler reads it straight
# from the questionnaire and the AI must never restate or alter it.
PROFILE_KEYS = (
    "summary",
    "goals",
    "work_style",
    "preferences",
    "recommended_work_block_minutes",
    "break_preferences",
    "scheduling_notes",
    "is_fallback",
)

# Answer keys must match the ids emitted by start_consultation, in order.
FOLLOW_UP_IDS = ("q1", "q2")

DEFAULT_WORK_BLOCK_MINUTES = 25


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def start_consultation(
    questionnaire: Any,
    client: DeepSeekClient | None = None,
    api_key: str | None = None,
) -> dict[str, Any]:
    """Stage one: analyse the questionnaire and propose 0-2 follow-ups.

    Returns ``{"follow_up_questions": [...]}`` where every question is an
    object with a stable id (``q1``, ``q2``). Ids are reassigned here rather
    than trusted from the model, so they always match the answer keys that
    ``finalize_profile`` expects.

    When the API is unavailable the question list is empty, which tells the
    caller to skip the follow-up screen and go straight to
    ``finalize_profile``.
    """
    data = _as_mapping(questionnaire)
    active_client = client or DeepSeekClient(api_key=api_key)

    prompt = ANALYSIS_PROMPT.format(
        questionnaire=_as_json(data),
        max_questions=MAX_FOLLOW_UP_QUESTIONS,
    )

    try:
        payload = active_client.chat_json(
            [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ]
        )
    except AIError:
        return {"follow_up_questions": []}

    return {"follow_up_questions": _normalise_questions(payload.get("follow_up_questions"))}


def finalize_profile(
    questionnaire: Any,
    follow_up_answers: Mapping[str, Any] | None = None,
    client: DeepSeekClient | None = None,
    api_key: str | None = None,
) -> dict[str, Any]:
    """Stage two: turn the questionnaire plus answers into a full profile.

    ``follow_up_answers`` is keyed by question id (``q1``/``q2``) and may be
    empty when stage one produced no question. Every returned profile carries
    ``is_fallback``; callers should surface a notice to the user when it is
    ``True``.
    """
    data = _as_mapping(questionnaire)
    answers = _clean_answers(follow_up_answers)
    active_client = client or DeepSeekClient(api_key=api_key)

    prompt = PROFILE_PROMPT.format(
        questionnaire=_as_json(data),
        follow_up_answers=_as_json(answers),
        min_block=MIN_WORK_BLOCK_MINUTES,
        max_block=MAX_WORK_BLOCK_MINUTES,
    )

    try:
        payload = active_client.chat_json(
            [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ]
        )
    except AIError:
        return build_fallback_profile(data)

    return _normalise_profile(payload, data)


def build_fallback_profile(questionnaire: Any) -> dict[str, Any]:
    """Deterministic profile built only from what the user explicitly said.

    Nothing here is generated: goals, preferences and work style are copied
    from the questionnaire, and the work block length is the documented
    default, labelled as such. This function makes no network call, so it
    always succeeds.
    """
    data = _as_mapping(questionnaire)

    goals = _clean_list(data.get("goals"))
    preferences = _clean_list(data.get("preferences"))
    work_style = _as_text(data.get("work_style"))
    break_preferences = _clean_list(data.get("break_preferences"))

    # The questionnaire has no field for a block length, so any number derived
    # from free text would be an invented preference. Use the documented
    # default and label it as such instead.
    block_minutes = DEFAULT_WORK_BLOCK_MINUTES

    notes = [
        "Generated without AI because the consultation service was unavailable.",
        "Only information supplied in the questionnaire was used.",
        f"The {block_minutes}-minute work block is a system default, "
        "not a user preference.",
    ]
    if _clean_list(data.get("fixed_commitments")):
        notes.append(
            "Fixed commitments come from the questionnaire and were not modified."
        )

    return {
        "summary": _fallback_summary(goals, work_style),
        "goals": goals,
        "work_style": work_style,
        "preferences": preferences,
        "recommended_work_block_minutes": block_minutes,
        "break_preferences": break_preferences,
        "scheduling_notes": " ".join(notes),
        "is_fallback": True,
    }


# ---------------------------------------------------------------------------
# Normalisation and validation
# ---------------------------------------------------------------------------


def _normalise_questions(raw: Any) -> list[dict[str, str]]:
    """Coerce a model reply into the agreed question shape.

    Accepts either ``{"id": ..., "question": ...}`` objects or bare strings,
    then reassigns ids sequentially so the result always pairs with the
    ``q1``/``q2`` answer keys.
    """
    if not isinstance(raw, (list, tuple)):
        return []

    questions: list[dict[str, str]] = []
    for item in raw:
        if len(questions) >= MAX_FOLLOW_UP_QUESTIONS:
            break

        if isinstance(item, Mapping):
            text = _as_text(item.get("question")) or _as_text(item.get("text"))
        else:
            text = _as_text(item)

        if not text:
            continue

        questions.append({"id": FOLLOW_UP_IDS[len(questions)], "question": text})

    return questions


def _clean_answers(answers: Any) -> dict[str, str]:
    """Keep only recognised question ids with non-empty answers."""
    mapping = _as_mapping(answers)
    cleaned: dict[str, str] = {}
    for question_id in FOLLOW_UP_IDS:
        text = _as_text(mapping.get(question_id))
        if text:
            cleaned[question_id] = text
    return cleaned


def _normalise_profile(
    payload: Mapping[str, Any],
    questionnaire: Mapping[str, Any],
) -> dict[str, Any]:
    """Force a model reply into the documented profile shape.

    Anything the model returns outside ``PROFILE_KEYS`` is dropped, which is
    what keeps a stray ``fixed_commitments`` key from ever reaching the
    scheduler.
    """
    source = payload if isinstance(payload, Mapping) else {}

    block, _ = _coerce_minutes(source.get("recommended_work_block_minutes"))

    profile: dict[str, Any] = {
        "summary": _as_text(source.get("summary")),
        "goals": _clean_list(source.get("goals"))
        or _clean_list(questionnaire.get("goals")),
        "work_style": _as_text(source.get("work_style"))
        or _as_text(questionnaire.get("work_style")),
        "preferences": _clean_list(source.get("preferences"))
        or _clean_list(questionnaire.get("preferences")),
        "recommended_work_block_minutes": block,
        "break_preferences": _clean_list(source.get("break_preferences")),
        "scheduling_notes": _as_text(source.get("scheduling_notes")),
        "is_fallback": False,
    }

    if not profile["summary"]:
        profile["summary"] = _fallback_summary(
            profile["goals"], profile["work_style"]
        )

    return profile


def _fallback_summary(goals: list[str], work_style: str) -> str:
    """Compose a summary using only stated facts."""
    parts: list[str] = []
    if goals:
        parts.append("Stated goals: " + "; ".join(goals) + ".")
    if work_style:
        parts.append(f"Reported work style: {work_style}.")
    if not parts:
        parts.append("No goals or work style were provided.")
    return " ".join(parts)


def _coerce_minutes(value: Any) -> tuple[int, bool]:
    """Coerce a model value into a bounded integer work block length."""
    try:
        minutes = int(value)
    except (TypeError, ValueError):
        return DEFAULT_WORK_BLOCK_MINUTES, True

    if minutes < MIN_WORK_BLOCK_MINUTES or minutes > MAX_WORK_BLOCK_MINUTES:
        return DEFAULT_WORK_BLOCK_MINUTES, True

    return minutes, False


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _as_mapping(value: Any) -> dict[str, Any]:
    """Coerce questionnaire-like input into a plain dictionary.

    Accepts dicts today and dataclass / pydantic models once ``core.models``
    lands, so the interface does not have to change later.
    """
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)

    for method_name in ("model_dump", "to_dict", "dict"):
        method = getattr(value, method_name, None)
        if callable(method):
            try:
                result = method()
            except Exception:
                continue
            if isinstance(result, dict):
                return dict(result)

    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return dataclasses.asdict(value)

    if hasattr(value, "__dict__"):
        return dict(vars(value))

    return {}


def _as_json(value: Any) -> str:
    """Serialise a mapping for inclusion in a prompt."""
    return json.dumps(_as_mapping(value), ensure_ascii=False, indent=2, default=str)


def _as_text(value: Any) -> str:
    """Return a trimmed string, treating ``None`` and blanks as empty."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def _clean_list(value: Any) -> list[str]:
    """Return a list of non-empty trimmed strings.

    A bare string is treated as a single-item list, because models sometimes
    collapse a one-element array into a scalar.
    """
    if value is None:
        return []
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple, set)):
        return []

    cleaned: list[str] = []
    for item in value:
        text = _as_text(item)
        if text:
            cleaned.append(text)
    return cleaned
