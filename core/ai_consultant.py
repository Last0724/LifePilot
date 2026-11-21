"""AI consultation logic for LifePilot (Core Models V1.1).

Three public functions, matching the contract agreed with the Technical Lead::

    start_consultation(questionnaire)                  -> ConsultationDraft (dict)
    finalize_profile(confirmed_questionnaire, answers)  -> UserProfile (dict)
    build_fallback_profile(questionnaire)               -> UserProfile (dict)

ConsultationDraft::

    {
        "follow_up_questions": [
            {"id": "q1", "question": "..."},
        ],
        "activity_suggestions": [
            {
                "activity_name": "Physics class",
                "suggested_category": "hard_commitment",
                "reason": "...",
                "source_task_id": "...",   # optional
            },
        ],
    }

UserProfile carries the seven content fields plus ``is_fallback``. The
fallback flag exists only on the profile, never on the draft.

Two invariants drive the validation in this module:

* **Suggestions are not facts.** ``activity_suggestions`` never reaches
  ``finalize_profile``'s prompt. Anything that looks like draft output is
  stripped from the questionnaire before it is sent, so the model can only
  reason about what the user confirmed.
* **Order matters.** Follow-up questions are sorted P0 -> P3 before the
  two-question cap is applied, so a lower-priority question can never
  displace a higher-priority one.

``core/models.py`` (owned by the Technical Lead) has not been pushed yet, so
questionnaire and profile values are plain dictionaries here. Three details
keep that temporary shape from leaking into the rest of the app:

* ``_as_mapping`` accepts dicts, dataclasses and pydantic models, so the real
  ``QuestionnaireData`` can be swapped in without touching this module.
* ``_jsonable`` recurses into nested ``TaskInput`` instances and enum values,
  so ``estimated_minutes`` / ``duration_type`` / ``ActivityCategory`` arrive
  in the prompt as data rather than as ``repr`` noise.
* ``_normalise_profile`` guarantees every documented key exists with the
  right type, so the scheduler can rely on the contract even when the model
  returns something sloppy.

An API failure never propagates. Every public function degrades to a
deterministic fallback.
"""

from __future__ import annotations

import dataclasses
import json
import re
from enum import Enum
from typing import Any, Mapping

from core.ai_client import AIError, DeepSeekClient
from core.prompts import (
    ACTIVITY_CATEGORIES,
    MAX_ACTIVITY_SUGGESTIONS,
    MAX_FOLLOW_UP_QUESTIONS,
    MAX_WORK_BLOCK_MINUTES,
    MIN_WORK_BLOCK_MINUTES,
    PROFILE_PROMPT,
    QUESTION_PRIORITIES,
    SYSTEM_PROMPT,
    render_analysis_prompt,
)

__all__ = [
    "ACTIVITY_CATEGORIES",
    "DURATION_TYPES",
    "DRAFT_KEYS",
    "FOLLOW_UP_IDS",
    "MEDICATION_KEYWORDS",
    "PROFILE_KEYS",
    "QUESTION_PRIORITIES",
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

# The keys every ConsultationDraft must carry.
DRAFT_KEYS = ("follow_up_questions", "activity_suggestions")

# Answer keys must match the ids emitted by start_consultation, in order.
FOLLOW_UP_IDS = ("q1", "q2")

# The two values TaskInput.duration_type may take. Only used to read a
# questionnaire that already carries them; never written back.
DURATION_TYPES = ("predictable", "uncertain")

# Keys that only ever belong to a draft. If a caller accidentally forwards a
# draft (or a contaminated dict) into profile generation, these are dropped so
# that unconfirmed suggestions can never be treated as user facts.
DRAFT_ARTEFACT_KEYS = ("follow_up_questions", "activity_suggestions", "is_fallback")

# Questionnaire fields whose presence means a question targeting them would
# be repeating information the user already supplied.
QUESTIONNAIRE_FIELDS = (
    "goals",
    "tasks",
    "fixed_commitments",
    "preferred_work_hours",
    "work_style",
    "preferences",
)

DEFAULT_WORK_BLOCK_MINUTES = 25

# Categories the model may abbreviate. Keys are normalised (lowercase,
# underscores); anything not listed and not an exact category is rejected
# rather than mapped onto a nearest guess, because a wrong classification
# would become a wrong schedule.
CATEGORY_ALIASES = {
    "hard": "hard_commitment",
    "commitment": "hard_commitment",
    "rest": "rest_period",
    "break": "rest_period",
    "routine": "predictable_routine",
    "predictable": "predictable_routine",
    "task": "uncertain_task",
    "uncertain": "uncertain_task",
}

MEDICATION_KEYWORDS = (
    "medication",
    "medicine",
    "medicines",
    "pill",
    "pills",
    "prescription",
    "dose",
    "dosage",
    "药",
)

# Clock times, in the two shapes a model actually produces: 08:00 / 8:00 and
# "8am" / "8 pm".
_TIME_PATTERN = re.compile(
    r"\b\d{1,2}[:：]\d{2}\b|\b\d{1,2}\s*(?:am|pm)\b",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def start_consultation(
    questionnaire: Any,
    client: DeepSeekClient | None = None,
    api_key: str | None = None,
) -> dict[str, Any]:
    """Stage one: propose 0-2 follow-ups and classify known activities.

    Returns ``{"follow_up_questions": [...], "activity_suggestions": [...]}``.

    Question ids are reassigned here (``q1``, ``q2``) rather than trusted from
    the model, so they always match the answer keys ``finalize_profile``
    expects. The same applies to ordering and duplicates: the model's list is
    sorted by priority, de-duplicated and truncated before it is returned.

    When the API is unavailable both lists are empty, which tells the caller
    to skip the follow-up screen and go straight to ``finalize_profile``.
    """
    data = _as_mapping(questionnaire)
    active_client = client or DeepSeekClient(api_key=api_key)

    try:
        payload = active_client.chat_json(
            [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": render_analysis_prompt(_as_json(data))},
            ]
        )
    except AIError:
        return _empty_draft()

    source = payload if isinstance(payload, Mapping) else {}

    return {
        "follow_up_questions": _normalise_questions(
            source.get("follow_up_questions"), data
        ),
        "activity_suggestions": _normalise_activities(
            source.get("activity_suggestions"), data
        ),
    }


def finalize_profile(
    questionnaire: Any = None,
    follow_up_answers: Mapping[str, Any] | None = None,
    client: DeepSeekClient | None = None,
    api_key: str | None = None,
    *,
    confirmed_questionnaire: Any = None,
) -> dict[str, Any]:
    """Stage two: turn the confirmed questionnaire plus answers into a profile.

    ``follow_up_answers`` is keyed by question id (``q1``/``q2``) and may be
    empty when stage one produced no question. Every returned profile carries
    ``is_fallback``; callers should surface a notice to the user when it is
    ``True``.

    ``questionnaire`` and ``confirmed_questionnaire`` are the same argument
    under two names, so the caller can use whichever reads better. Anything
    that looks like draft output (suggestions, questions, a fallback flag) is
    stripped before the prompt is built: only confirmed user information may
    reach the model here.
    """
    source = questionnaire if questionnaire is not None else confirmed_questionnaire
    data = _strip_draft_artefacts(_as_mapping(source))
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
    always succeeds. Draft artefacts are stripped first, so an unconfirmed
    suggestion can never be promoted to a stated preference by falling back.
    """
    data = _strip_draft_artefacts(_as_mapping(questionnaire))

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
# Draft normalisation
# ---------------------------------------------------------------------------


def _empty_draft() -> dict[str, list]:
    """A valid draft with nothing in it, used when the API is unavailable."""
    return {"follow_up_questions": [], "activity_suggestions": []}


def _normalise_questions(
    raw: Any,
    questionnaire: Mapping[str, Any],
) -> list[dict[str, str]]:
    """Coerce a model reply into the agreed question shape.

    Accepts ``{"id", "question", "priority", "target_field"}`` objects, or
    bare strings for sloppy replies. Four steps, in this order:

    1. drop questions that would re-ask a questionnaire field already filled,
    2. drop duplicate wording,
    3. sort by priority so P0 comes first,
    4. cap at two and reassign ids ``q1``/``q2``.

    The returned objects carry only ``id`` and ``question``: priority is an
    internal ordering device, not part of the UI contract.
    """
    if not isinstance(raw, (list, tuple)):
        return []

    answered = _answered_fields(questionnaire)
    candidates: list[dict[str, Any]] = []

    for index, item in enumerate(raw):
        if isinstance(item, Mapping):
            text = _as_text(item.get("question")) or _as_text(item.get("text"))
            priority = _normalise_priority(item.get("priority"))
            target = _as_text(item.get("target_field")) or _as_text(item.get("target"))
        else:
            text = _as_text(item)
            priority = QUESTION_PRIORITIES[-1]
            target = ""

        if not text:
            continue

        # A question that names a field the user already filled is, by
        # definition, a repeat. Drop it rather than trusting the model to
        # have noticed.
        if target and target in answered:
            continue

        key = _dedupe_key(text)
        if not key or any(key == candidate["key"] for candidate in candidates):
            continue

        candidates.append(
            {"text": text, "priority": priority, "key": key, "index": index}
        )

    candidates.sort(
        key=lambda candidate: (
            QUESTION_PRIORITIES.index(candidate["priority"]),
            candidate["index"],
        )
    )

    return [
        {"id": FOLLOW_UP_IDS[position], "question": candidate["text"]}
        for position, candidate in enumerate(candidates[:MAX_FOLLOW_UP_QUESTIONS])
    ]


def _normalise_activities(
    raw: Any,
    questionnaire: Mapping[str, Any],
) -> list[dict[str, str]]:
    """Coerce classified activities into the agreed suggestion shape.

    Only the four documented categories survive; an unrecognised category is
    discarded rather than mapped onto a nearest guess. Suggestions are capped,
    de-duplicated by name and category, and medication timings the user never
    supplied are scrubbed.
    """
    if not isinstance(raw, (list, tuple)):
        return []

    # Everything the user actually wrote, lowercased, used to decide whether
    # a time in a reason was quoted from the questionnaire or invented.
    user_text = _as_json(questionnaire).lower()
    suggestions: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()

    for item in raw:
        if len(suggestions) >= MAX_ACTIVITY_SUGGESTIONS:
            break
        if not isinstance(item, Mapping):
            continue

        name = _as_text(
            item.get("activity_name") or item.get("name") or item.get("activity")
        )
        if not name:
            continue

        category = _normalise_category(
            item.get("suggested_category") or item.get("category")
        )
        if category is None:
            continue

        reason = _guard_medication_timing(
            name, _as_text(item.get("reason")), user_text
        )
        key = (_dedupe_key(name), category)
        if key in seen:
            continue
        seen.add(key)

        suggestion: dict[str, str] = {
            "activity_name": name,
            "suggested_category": category,
            "reason": reason,
        }
        source_id = _as_text(item.get("source_task_id")) or _as_text(
            item.get("task_id")
        )
        if source_id:
            suggestion["source_task_id"] = source_id

        suggestions.append(suggestion)

    return suggestions


def _normalise_priority(value: Any) -> str:
    """Map a model-supplied priority onto ``P0``-``P3``.

    Unknown or missing values fall to the lowest tier, which means they lose
    every tie against a real priority once the list is sorted and capped.
    """
    text = _as_text(value).upper().replace(" ", "")
    if text.startswith("PRIORITY"):
        text = text[len("PRIORITY") :]
    text = text.lstrip("P").lstrip("_:-")

    for index in range(len(QUESTION_PRIORITIES)):
        if text.startswith(str(index)):
            return QUESTION_PRIORITIES[index]

    return QUESTION_PRIORITIES[-1]


def _normalise_category(value: Any) -> str | None:
    """Return one of the four category values, or ``None`` when unrecognisable.

    Accepts the enum itself (``ActivityCategory.hard_commitment``), the plain
    string (``"hard_commitment"``), and the shouty or spaced variants a model
    sometimes emits (``"HARD_COMMITMENT"``, ``"hard-commitment"``).
    """
    if isinstance(value, Enum):
        value = value.value

    text = _as_text(value).lower().replace("-", "_").replace(" ", "_")
    text = "_".join(part for part in text.split("_") if part)

    if text in ACTIVITY_CATEGORIES:
        return text
    return CATEGORY_ALIASES.get(text)


def _guard_medication_timing(name: str, reason: str, user_text: str) -> str:
    """Remove clock times the user never gave, for medication-like activities.

    The AI must never decide when someone takes their medicine. Any time in a
    medication reason that does not appear verbatim in the questionnaire is
    replaced with a placeholder the user has to fill in.
    """
    if not reason:
        return reason
    if not any(word in name.lower() for word in MEDICATION_KEYWORDS):
        return reason

    def replace(match: re.Match[str]) -> str:
        found = match.group(0)
        return found if found.lower() in user_text else "a time you confirm"

    return _TIME_PATTERN.sub(replace, reason)


# ---------------------------------------------------------------------------
# Profile normalisation
# ---------------------------------------------------------------------------


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
        profile["summary"] = _fallback_summary(profile["goals"], profile["work_style"])

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


def _strip_draft_artefacts(questionnaire: Mapping[str, Any]) -> dict[str, Any]:
    """Remove draft-only keys so suggestions cannot pose as user facts."""
    return {
        key: value
        for key, value in questionnaire.items()
        if key not in DRAFT_ARTEFACT_KEYS
    }


def _answered_fields(questionnaire: Mapping[str, Any]) -> set[str]:
    """Return the questionnaire fields the user has already filled in."""
    return {
        field
        for field in QUESTIONNAIRE_FIELDS
        if _has_content(questionnaire.get(field))
    }


def _has_content(value: Any) -> bool:
    """True when a value carries information, not just an empty container."""
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, Mapping):
        return bool(value)
    if isinstance(value, (list, tuple, set)):
        return any(_has_content(item) for item in value)
    return bool(value)


def _dedupe_key(text: str) -> str:
    """Reduce a string to its comparable core, keeping letters and digits."""
    return "".join(ch for ch in text.lower() if ch.isalnum())


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


def _jsonable(value: Any) -> Any:
    """Convert a questionnaire into something ``json.dumps`` renders readably.

    ``_as_mapping`` only converts the top level. A ``QuestionnaireData`` holds
    ``list[TaskInput]``, and ``TaskInput`` holds ``estimated_minutes`` and a
    ``duration_type`` enum, so the recursion below is what keeps those fields
    visible to the model instead of collapsing into ``repr`` strings.
    """
    if isinstance(value, Enum):
        return value.value
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: _jsonable(getattr(value, field.name))
            for field in dataclasses.fields(value)
        }
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    if hasattr(value, "model_dump") and callable(value.model_dump):
        try:
            return _jsonable(value.model_dump())
        except Exception:
            return str(value)
    return value


def _as_json(value: Any) -> str:
    """Serialise a mapping for inclusion in a prompt."""
    return json.dumps(_jsonable(_as_mapping(value)), ensure_ascii=False, indent=2, default=str)


def _as_text(value: Any) -> str:
    """Return a trimmed string, treating ``None`` and blanks as empty."""
    if value is None:
        return ""
    if isinstance(value, Enum):
        return str(value.value).strip()
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def _clean_list(value: Any) -> list[str]:
    """Return a list of non-empty trimmed strings.

    A bare string is treated as a single-item list, because models sometimes
    collapse a one-element array into a scalar. Dicts are rendered as their
    ``name``/``title``/``label`` value when present, so a questionnaire that
    supplies tasks as objects still yields readable goal text.
    """
    if value is None:
        return []
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple, set)):
        return []

    cleaned: list[str] = []
    for item in value:
        text = _display_text(item)
        if text:
            cleaned.append(text)
    return cleaned


def _display_text(item: Any) -> str:
    """Render one list entry as readable text.

    Once ``core.models`` lands, questionnaire lists may hold model instances
    rather than strings. Falling back to ``repr`` would put
    ``TaskInput(name='Read', estimated_minutes=60)`` into a user-facing
    summary, so the obvious label fields are tried first.
    """
    if isinstance(item, Mapping):
        for key in ("name", "title", "label", "text", "description", "goal"):
            text = _as_text(item.get(key))
            if text:
                return text
        return ""

    if dataclasses.is_dataclass(item) and not isinstance(item, type):
        for key in ("name", "title", "label", "text", "description", "goal"):
            text = _as_text(getattr(item, key, None))
            if text:
                return text
        return ""

    return _as_text(item)
