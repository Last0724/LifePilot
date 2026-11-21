"""AI consultation logic for LifePilot (Core Models V1.2).

The canonical interface is :class:`ConsultationController`, a stateful,
multi-round controller. Python owns every decision; the LLM only phrases
questions, classifies activities and writes the final profile.

Field states
------------
Every *required* questionnaire field belongs to exactly one of three states:

* ``resolved_fields``   - the field has confirmed information (a value, or an
  explicitly confirmed empty answer such as "none").
* ``unknown_fields``    - the user explicitly said they do not know / it does
  not apply. This field must never be asked again; ``is_complete`` still
  becomes ``True`` because consultation is over, but the frontend is expected
  to surface the gap for manual completion.
* ``unresolved_fields`` - no confirmed value yet; still eligible to be asked.

``is_complete`` is derived from ``unresolved_fields`` (empty -> complete).

Required vs optional fields
---------------------------
Required fields, in P0 -> P4 priority order (ask order, not importance):

    P0  fixed_commitments
    P1  rest_periods
    P2  predictable_routines
    P3  tasks, preferred_work_start, preferred_work_end, work_days, energy_peak
    P4  goals

Optional contextual fields (``habits`` / ``challenges`` / ``notes``) are never
asked about and never block completion.

Answer classification
---------------------
Each answer to a follow-up question is classified as:

* "resolved"  - any substantive answer, including an explicit "none"/"nothing"
  (which counts as a confirmed empty value).
* "unknown"   - an explicit "I don't know" / "not sure" / "doesn't apply".
* "unresolved" - no answer given (empty / skipped); the field stays open.

Rounds
------
At most two questions per round, deduplicated by ``target_field``. The total
consultation is not limited to two questions; ``MAX_ROUNDS`` (12) is a safety
ceiling after which no further questions are produced.

Backward compatibility
----------------------
``start_consultation`` / ``finalize_profile`` / ``build_fallback_profile`` keep
their V1.1 signatures and dictionary output shapes, so B's frontend keeps
working unchanged. The typed models are used internally and surfaced through
:class:`ConsultationController`.
"""

from __future__ import annotations

import dataclasses
import json
import re
from enum import Enum
from typing import Any, Mapping

from core.ai_client import AIError, DeepSeekClient
from core.models import (
    ActivityCategory,
    ActivitySuggestion,
    ConsultationDraft,
    FollowUpQuestion,
    ModelError,
    PredictableRoutine,
    QuestionnaireData,
    RestPeriod,
    UserProfile,
)
from core.prompts import (
    ACTIVITY_CATEGORIES,
    DEFAULT_WORK_BLOCK_MINUTES,
    FIELD_DESCRIPTIONS,
    MAX_ACTIVITY_SUGGESTIONS,
    MAX_FOLLOW_UP_QUESTIONS,
    MAX_WORK_BLOCK_MINUTES,
    MIN_WORK_BLOCK_MINUTES,
    PROFILE_PROMPT,
    QUESTION_PRIORITIES,
    SYSTEM_PROMPT,
    render_classify_prompt,
    render_extract_prompt,
    render_phrase_prompt,
)

__all__ = [
    "ACTIVITY_CATEGORIES",
    "DEFAULTED_FIELDS",
    "DRAFT_KEYS",
    "DURATION_TYPES",
    "MAX_ROUNDS",
    "MEDICATION_KEYWORDS",
    "OPTIONAL_FIELDS",
    "PROFILE_KEYS",
    "QUESTION_PRIORITIES",
    "REQUIRED_FIELDS",
    "STRUCTURED_FIELDS",
    "ConsultationController",
    "build_fallback_profile",
    "finalize_profile",
    "map_answers_to_fields",
    "start_consultation",
]

MAX_ROUNDS = 12

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

# The keys every ConsultationDraft carries (V1.2 field-state model).
DRAFT_KEYS = (
    "follow_up_questions",
    "activity_suggestions",
    "resolved_fields",
    "unknown_fields",
    "unresolved_fields",
)

# Required questionnaire fields, ordered by ask priority P0 -> P4.
REQUIRED_FIELDS = (
    "fixed_commitments",       # P0
    "rest_periods",            # P1
    "predictable_routines",    # P2
    "tasks",                   # P3
    "preferred_work_start",    # P3
    "preferred_work_end",      # P3
    "work_days",               # P3
    "energy_peak",             # P3
    "goals",                   # P4
)

# Optional contextual fields: never asked about, never block completion.
OPTIONAL_FIELDS = ("habits", "challenges", "notes")

# Field -> priority tier (0 = P0 ... 4 = P4). Lower asks first.
FIELD_PRIORITY = {
    "fixed_commitments": 0,
    "rest_periods": 1,
    "predictable_routines": 2,
    "tasks": 3,
    "preferred_work_start": 3,
    "preferred_work_end": 3,
    "work_days": 3,
    "energy_peak": 3,
    "goals": 4,
}

# The two values TaskInput.duration_type may take. Only used to read a
# questionnaire that already carries them; never written back.
DURATION_TYPES = ("predictable", "uncertain")

# Keys that only ever belong to a draft. If a caller accidentally forwards a
# draft (or a contaminated dict) into profile generation, these are dropped so
# that unconfirmed suggestions can never be treated as user facts.
DRAFT_ARTEFACT_KEYS = (
    "follow_up_questions",
    "activity_suggestions",
    "resolved_fields",
    "unknown_fields",
    "unresolved_fields",
    "is_fallback",
)

# Categories the model may abbreviate. Keys are normalised (lowercase,
# underscores); anything not listed and not an exact category is rejected
# rather than mapped onto a nearest guess.
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

# Explicit "I don't know" signals. A matching answer moves the field to the
# unknown state and guarantees it is never asked again.
UNKNOWN_ANSWER_MARKERS = (
    "dont know",
    "don't know",
    "do not know",
    "not sure",
    "unsure",
    "no idea",
    "dont remember",
    "don't remember",
    "does not apply",
    "doesn't apply",
    "not applicable",
    "unknown",
    "idk",
    "不知道",
    "不清楚",
    "不确定",
    "没想好",
    "不适用",
    "忘了",
)

# Clock times, in the two shapes a model actually produces: 08:00 / 8:00 and
# "8am" / "8 pm".
_TIME_PATTERN = re.compile(
    r"\b\d{1,2}[:：]\d{2}\b|\b\d{1,2}\s*(?:am|pm)\b",
    re.IGNORECASE,
)

# A follow-up answer id is "q" followed by a positive integer, with no limit.
_ANSWER_ID_PATTERN = re.compile(r"q[1-9]\d*")

# QuestionnaireData fields that carry a dataclass default. A default value is
# NOT user confirmation: unless the frontend reports the field in
# ``confirmed_fields``, a default is treated as still-unresolved so the
# controller asks about it rather than silently trusting a placeholder.
DEFAULTED_FIELDS = {
    "preferred_work_start": "09:00",
    "preferred_work_end": "22:00",
    "work_days": [0, 1, 2, 3, 4, 5, 6],
}

# Fields whose follow-up answers can be turned into structured scheduling
# inputs (see ``build_questionnaire_inputs``). ``tasks`` and
# ``fixed_commitments`` are deliberately absent: turning a free-text answer
# into a TaskInput (with estimated_minutes/duration_type) or a FixedCommitment
# (with concrete datetimes) cannot be done reliably by deterministic parsing,
# so those answers are kept verbatim and flagged ``needs_confirmation``.
STRUCTURED_FIELDS = (
    "rest_periods",
    "predictable_routines",
    "preferred_work_start",
    "preferred_work_end",
    "work_days",
    "energy_peak",
)

# Human time-of-day in the two shapes users actually type: "9:00" / "09:00"
# and "9am" / "9 pm".
_HHMM_PATTERN = re.compile(r"\b(?:[01]?\d|2[0-3]):[0-5]\d\b")
_HHMM_AMPM_PATTERN = re.compile(
    r"\b(\d{1,2})(?::([0-5]\d))?\s*(a\.?m\.?|p\.?m\.?)\b", re.IGNORECASE
)
# A time range like "23:00-07:00", "09:00–17:00", "9:00 to 5pm".
_TIME_RANGE_PATTERN = re.compile(
    r"(?P<start>\d{1,2}:\d{2})\s*(?:-|–|—|to|until|到|至)\s*(?P<end>\d{1,2}:\d{2})",
    re.IGNORECASE,
)
# A duration like "30 minutes", "45 mins", "1 hour", "2 hours".
_MINUTES_PATTERN = re.compile(
    r"(?P<num>\d{1,3})\s*(?:min(?:ute)?s?|分(?:钟)?)|"
    r"(?P<hours>\d{1,2})\s*(?:hours?|hrs?|小时)|"
    r"(?P<half>half an hour|半小时)",
    re.IGNORECASE,
)

# Weekday names mapped to QuestionnaireData's 0-6 convention (0 = Monday).
_WEEKDAY_NAMES = {
    "monday": 0, "mon": 0,
    "tuesday": 1, "tue": 1, "tues": 1,
    "wednesday": 2, "wed": 2,
    "thursday": 3, "thu": 3, "thur": 3, "thurs": 3,
    "friday": 4, "fri": 4,
    "saturday": 5, "sat": 5,
    "sunday": 6, "sun": 6,
    "周一": 0, "星期一": 0, "礼拜一": 0,
    "周二": 1, "星期二": 1, "礼拜二": 1,
    "周三": 2, "星期三": 2, "礼拜三": 2,
    "周四": 3, "星期四": 3, "礼拜四": 3,
    "周五": 4, "星期五": 4, "礼拜五": 4,
    "周六": 5, "星期六": 5, "礼拜六": 5,
    "周日": 6, "星期天": 6, "礼拜天": 6, "周天": 6, "星期日": 6,
}

# energy_peak aliases, matched case-insensitively against the answer text.
_ENERGY_PEAK_ALIASES = {
    "morning": ("morning", "早上", "上午", "早晨", "早起"),
    "afternoon": ("afternoon", "下午", "午后"),
    "evening": ("evening", "晚上", "傍晚", "夜里", "夜晚"),
    "flexible": ("flexible", "anytime", "any time", "不定", "随时", "灵活"),
}

# A fallback title for a rest period whose answer only carried a time range.
_DEFAULT_REST_TITLE = "Rest"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


class ConsultationController:
    """Stateful multi-round consultation (canonical V1.2 interface).

    Construct with the questionnaire, call :meth:`next_round` to get a
    :class:`ConsultationDraft`, collect answers, then :meth:`apply_answers`.
    Repeat until :attr:`is_complete`. The state is explicitly serializable via
    :meth:`to_state` / :meth:`from_state` for storage in Streamlit session
    state; no module-level global state is used.

    The questionnaire is stored stripped of draft artefacts. The client is
    resolved eagerly from ``client`` or ``api_key``, but the underlying SDK
    client stays lazy.
    """

    def __init__(
        self,
        questionnaire: Any,
        client: DeepSeekClient | None = None,
        api_key: str | None = None,
        max_rounds: int = MAX_ROUNDS,
        confirmed_fields: set[str] | None = None,
    ) -> None:
        # Detect a QuestionnaireData instance before it is flattened: only it
        # carries dataclass defaults that must not be mistaken for user facts.
        self._has_defaulted_fields = isinstance(questionnaire, QuestionnaireData)
        self.questionnaire = _strip_draft_artefacts(_as_mapping(questionnaire))
        self.client = client or DeepSeekClient(api_key=api_key)
        self.max_rounds = max_rounds

        self.round_count = 0
        self.resolved, self.unknown, self.unresolved = _initial_field_states(
            self.questionnaire,
            confirmed_fields=confirmed_fields,
            has_defaulted_fields=self._has_defaulted_fields,
        )
        self._suggestions: list[ActivitySuggestion] | None = None
        self._question_targets: dict[str, str] = {}
        self._answers: dict[str, str] = {}
        self._question_seq = 0
        self._pending: list[FollowUpQuestion] = []

    # -- read-only state ----------------------------------------------------

    @property
    def is_complete(self) -> bool:
        """True when no required field is still unresolved."""
        return len(self.unresolved) == 0

    # -- driving the consultation ------------------------------------------

    def next_round(self) -> ConsultationDraft:
        """Return the draft for the next round, asking <= 2 new questions.

        If questions were already asked this round and not yet answered, the
        same questions are returned (idempotent for Streamlit reruns).
        """
        suggestions = self._ensure_suggestions()
        if self._pending:
            questions = list(self._pending)
        elif self.is_complete or self.round_count >= self.max_rounds:
            questions = []
        else:
            fields = self._select_fields()
            questions = self._phrase(fields)
            self._pending = list(questions)
        return self._build_draft(questions, suggestions)

    def apply_answers(self, answers: Any) -> None:
        """Apply this round's answers and advance the round counter."""
        mapping = _as_mapping(answers)
        self.round_count += 1
        for question in self._pending:
            if question.id not in mapping:
                continue  # skipped -> field stays unresolved
            text = _as_text(mapping[question.id])
            self._answers[question.id] = text
            self._transition(question.target_field, _classify_answer(text))
        self._pending = []

    # -- structured output (V1.2) ------------------------------------------

    def build_questionnaire_inputs(self, use_llm: bool = True) -> dict[str, Any]:
        """Return a validated partial field patch for ``QuestionnaireData``.

        The return value is *not* a ``QuestionnaireData`` instance: it is a
        dictionary of structured fields that the integrator merges into one.
        Scheduling constraints (``rest_periods``, ``predictable_routines``,
        ``work_days``, ``energy_peak``, ``preferred_work_start/end``) are
        parsed deterministically from the confirmed follow-up answers and
        validated against the shared models. When ``use_llm`` is true and
        deterministic parsing fails, the LLM is asked to extract the field and
        its output is schema-validated. Anything that still cannot be parsed
        reliably is returned verbatim under ``needs_confirmation`` — never
        guessed.

        Returns ``{"fields": {field: value, ...},
        "needs_confirmation": {field: [raw_text, ...], ...}}``.
        """
        field_map = map_answers_to_fields(self._question_targets, self._answers)
        # Exclude fields the user explicitly marked unknown: they are not
        # scheduling constraints and must never reach the patch (nor be
        # surfaced as "needs confirmation", since they were already answered).
        for field in self.unknown:
            field_map.pop(field, None)
        patch, needs_confirmation = _build_structured_patch(field_map)
        if use_llm and needs_confirmation:
            patch, needs_confirmation = _resolve_with_llm(
                patch, needs_confirmation, self.client
            )
        return {
            "fields": patch,
            "needs_confirmation": needs_confirmation,
        }

    def finalize(self) -> UserProfile:
        """Build the final profile from confirmed information (canonical V1.2).

        Maps answers onto fields (so the LLM never guesses a field from the
        question wording), then delegates to the LLM. On API failure it falls
        back deterministically, preserving the confirmed follow-up answers.
        """
        field_map = map_answers_to_fields(self._question_targets, self._answers)
        prompt = PROFILE_PROMPT.format(
            questionnaire=_as_json(self.questionnaire),
            follow_up_answers=_as_json(field_map),
            min_block=MIN_WORK_BLOCK_MINUTES,
            max_block=MAX_WORK_BLOCK_MINUTES,
            default_block=DEFAULT_WORK_BLOCK_MINUTES,
        )
        try:
            payload = self.client.chat_json(
                [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ]
            )
        except AIError:
            return _build_fallback_profile(self.questionnaire, field_map)
        return _normalise_profile(payload, self.questionnaire)

    # -- serialization ------------------------------------------------------

    def to_state(self) -> dict:
        """Return a JSON-friendly snapshot for Streamlit session state."""
        return {
            "round_count": self.round_count,
            "resolved_fields": self._sorted(self.resolved),
            "unknown_fields": self._sorted(self.unknown),
            "unresolved_fields": self._sorted(self.unresolved),
            "question_targets": dict(self._question_targets),
            "answers": dict(self._answers),
            "question_seq": self._question_seq,
            "pending": [self._question_to_dict(q) for q in self._pending],
        }

    @classmethod
    def from_state(
        cls,
        state: Mapping[str, Any],
        questionnaire: Any,
        client: DeepSeekClient | None = None,
        api_key: str | None = None,
        confirmed_fields: set[str] | None = None,
    ) -> "ConsultationController":
        """Reconstruct a controller from :meth:`to_state` output.

        ``confirmed_fields`` is re-supplied by the caller (it is an input, not
        runtime state, so it is not part of :meth:`to_state`).
        """
        controller = cls(
            questionnaire,
            client=client,
            api_key=api_key,
            confirmed_fields=confirmed_fields,
        )
        controller.round_count = int(state.get("round_count", 0))
        controller.resolved = list(state.get("resolved_fields", []))
        controller.unknown = list(state.get("unknown_fields", []))
        controller.unresolved = list(state.get("unresolved_fields", []))
        controller._question_targets = dict(state.get("question_targets", {}))
        controller._answers = dict(state.get("answers", {}))
        controller._question_seq = int(state.get("question_seq", 0))
        controller._pending = [
            FollowUpQuestion(**item) for item in state.get("pending", [])
        ]
        return controller

    # -- internals ----------------------------------------------------------

    def _select_fields(self) -> list[str]:
        fields = sorted(
            self.unresolved, key=lambda field: (FIELD_PRIORITY.get(field, 9), field)
        )
        return fields[:MAX_FOLLOW_UP_QUESTIONS]

    def _ensure_suggestions(self) -> list[ActivitySuggestion]:
        if self._suggestions is None:
            self._suggestions = _classify_activities(self.questionnaire, self.client)
        return list(self._suggestions)

    def _phrase(self, fields: list[str]) -> list[FollowUpQuestion]:
        selected = [
            {
                "field": field,
                "priority": QUESTION_PRIORITIES[FIELD_PRIORITY.get(field, 4)],
                "meaning": FIELD_DESCRIPTIONS.get(field, field),
            }
            for field in fields
        ]
        prompt = render_phrase_prompt(_as_json(self.questionnaire), selected)
        try:
            payload = self.client.chat_json(
                [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ]
            )
        except AIError:
            return []

        source = payload if isinstance(payload, Mapping) else {}
        texts = _extract_question_texts(source.get("follow_up_questions"))

        questions: list[FollowUpQuestion] = []
        for field in fields:
            text = texts.get(field)
            if not text:
                continue
            self._question_seq += 1
            question_id = f"q{self._question_seq}"
            self._question_targets[question_id] = field
            questions.append(
                FollowUpQuestion(
                    id=question_id,
                    question=text,
                    target_field=field,
                    priority=FIELD_PRIORITY.get(field, 2),
                )
            )
        return questions

    def _transition(self, field: str, label: str) -> None:
        if label == "unresolved":
            return
        if field in self.unresolved:
            self.unresolved.remove(field)
        target = self.unknown if label == "unknown" else self.resolved
        if field not in target:
            target.append(field)

    def _build_draft(
        self,
        questions: list[FollowUpQuestion],
        suggestions: list[ActivitySuggestion],
    ) -> ConsultationDraft:
        return ConsultationDraft(
            follow_up_questions=questions,
            activity_suggestions=suggestions,
            resolved_fields=self._sorted(self.resolved),
            unknown_fields=self._sorted(self.unknown),
            unresolved_fields=self._sorted(self.unresolved),
        )

    @staticmethod
    def _sorted(fields: list[str]) -> list[str]:
        return sorted(fields, key=lambda field: (FIELD_PRIORITY.get(field, 9), field))

    @staticmethod
    def _question_to_dict(question: FollowUpQuestion) -> dict[str, Any]:
        return {
            "id": question.id,
            "question": question.question,
            "target_field": question.target_field,
            "priority": question.priority,
        }


def start_consultation(
    questionnaire: Any,
    client: DeepSeekClient | None = None,
    api_key: str | None = None,
) -> dict[str, Any]:
    """Legacy stage one: propose the first round's follow-ups and classify.

    Backward-compatible wrapper. Returns the V1.1 dictionary shape::

        {"follow_up_questions": [{"id", "question"}, ...],
         "activity_suggestions": [...]}

    Internally it runs :class:`ConsultationController` once, so priority and
    field selection are owned by Python, not the model. When the API is
    unavailable both lists are empty.
    """
    controller = ConsultationController(questionnaire, client=client, api_key=api_key)
    draft = controller.next_round()
    return {
        "follow_up_questions": [
            {"id": question.id, "question": question.question}
            for question in draft.follow_up_questions
        ],
        "activity_suggestions": [
            _suggestion_to_dict(suggestion)
            for suggestion in draft.activity_suggestions
        ],
    }


def finalize_profile(
    questionnaire: Any = None,
    follow_up_answers: Mapping[str, Any] | None = None,
    client: DeepSeekClient | None = None,
    api_key: str | None = None,
    *,
    confirmed_questionnaire: Any = None,
    question_targets: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Legacy stage two: turn confirmed information into a profile dictionary.

    Backward-compatible wrapper returning the V1.1 eight-key dictionary shape
    (``break_preferences`` is now a string, matching the V1.2 model). Anything
    that looks like draft output is stripped first.

    When ``question_targets`` (the controller's ``q{n} -> field`` map) is
    provided, answers are mapped onto their fields before reaching the prompt,
    so the model never has to guess a field from question wording. Without it,
    the legacy ``q{n}`` answer dict is passed through unchanged for
    compatibility.
    """
    source = questionnaire if questionnaire is not None else confirmed_questionnaire
    data = _strip_draft_artefacts(_as_mapping(source))
    active_client = client or DeepSeekClient(api_key=api_key)

    if question_targets is not None:
        field_map = map_answers_to_fields(question_targets, follow_up_answers)
    else:
        field_map = _clean_answers(follow_up_answers)

    prompt = PROFILE_PROMPT.format(
        questionnaire=_as_json(data),
        follow_up_answers=_as_json(field_map),
        min_block=MIN_WORK_BLOCK_MINUTES,
        max_block=MAX_WORK_BLOCK_MINUTES,
        default_block=DEFAULT_WORK_BLOCK_MINUTES,
    )

    try:
        payload = active_client.chat_json(
            [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ]
        )
    except AIError:
        profile = _build_fallback_profile(data, field_map)
    else:
        profile = _normalise_profile(payload, data)

    return _profile_to_dict(profile)


def build_fallback_profile(
    questionnaire: Any,
    follow_up_answers: Mapping[str, Any] | None = None,
    question_targets: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Legacy deterministic profile, built only from explicit user input.

    Returns the V1.1 eight-key dictionary shape. No network call, so it always
    succeeds. Draft artefacts are stripped first.

    When ``question_targets`` is provided, the confirmed follow-up answers are
    preserved (mapped onto their fields) instead of being silently dropped.
    """
    data = _strip_draft_artefacts(_as_mapping(questionnaire))
    if question_targets is not None:
        field_map = map_answers_to_fields(question_targets, follow_up_answers)
    else:
        field_map = _clean_answers(follow_up_answers)
    return _profile_to_dict(_build_fallback_profile(data, field_map))


# ---------------------------------------------------------------------------
# Question extraction and phrasing (Python-owned)
# ---------------------------------------------------------------------------


def _extract_question_texts(raw: Any) -> dict[str, str]:
    """Map ``target_field -> question`` from a model reply, first one wins.

    Bare strings are ignored in V1.2: a question without a ``target_field``
    cannot be mapped to a field, so it is discarded rather than guessed.
    """
    result: dict[str, str] = {}
    if not isinstance(raw, (list, tuple)):
        return result
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        target = _as_text(item.get("target_field")) or _as_text(item.get("target"))
        text = _as_text(item.get("question")) or _as_text(item.get("text"))
        if target and text and target not in result:
            result[target] = text
    return result


def _classify_activities(
    questionnaire: Mapping[str, Any],
    client: DeepSeekClient,
) -> list[ActivitySuggestion]:
    """Classify the activities the user mentioned (LLM responsibility only)."""
    try:
        payload = client.chat_json(
            [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": render_classify_prompt(_as_json(questionnaire))},
            ]
        )
    except AIError:
        return []
    source = payload if isinstance(payload, Mapping) else {}
    return _normalise_activities(source.get("activity_suggestions"), questionnaire)


# ---------------------------------------------------------------------------
# Answer mapping and structured parsing (Python-owned)
# ---------------------------------------------------------------------------


def map_answers_to_fields(
    question_targets: Mapping[str, str], answers: Any
) -> dict[str, list[str]]:
    """Map follow-up answers (``q{n} -> text``) onto their target fields.

    ``question_targets`` is the controller's ``q{n} -> target_field`` mapping.
    Returns ``{target_field: [answer_text, ...]}``, preserving original text.

    Question ids without a target field are dropped, so the LLM never has to
    guess a field from the wording of a question. Answers without a recognised
    ``q{n}`` id are ignored.
    """
    targets = _as_mapping(question_targets)
    cleaned = _clean_answers(answers)
    result: dict[str, list[str]] = {}
    for question_id, text in cleaned.items():
        field = _as_text(targets.get(question_id))
        if not field:
            continue
        result.setdefault(field, []).append(text)
    return result


def _normalise_hhmm(value: str) -> str | None:
    """Normalise ``"9:00"`` / ``"09:00"`` to ``"09:00"``; ``None`` when invalid."""
    match = re.fullmatch(r"(\d{1,2}):(\d{2})", value)
    if not match:
        return None
    hour, minute = int(match.group(1)), int(match.group(2))
    if hour > 23 or minute > 59:
        return None
    return f"{hour:02d}:{minute:02d}"


def _parse_time(text: str) -> str | None:
    """Extract one HH:MM time-of-day from free text, or ``None``."""
    value = _as_text(text)
    if not value:
        return None
    match = _HHMM_PATTERN.search(value)
    if match:
        return _normalise_hhmm(match.group(0))
    match = _HHMM_AMPM_PATTERN.search(value)
    if match:
        hour = int(match.group(1))
        minute = int(match.group(2)) if match.group(2) else 0
        marker = match.group(3).lower()
        if marker.startswith("p") and hour < 12:
            hour += 12
        elif marker.startswith("a") and hour == 12:
            hour = 0
        return f"{hour:02d}:{minute:02d}"
    return None


def _parse_weekdays(text: str) -> list[int] | None:
    """Extract 0-6 weekday indices (0 = Monday), or ``None`` when none found."""
    value = _as_text(text)
    if not value:
        return None
    lowered = value.lower()
    days: set[int] = set()
    for name, index in _WEEKDAY_NAMES.items():
        if name.isascii():
            if re.search(rf"\b{re.escape(name)}\b", lowered):
                days.add(index)
        elif name in value:
            days.add(index)
    return sorted(days) if days else None


def _parse_energy_peak(text: str) -> str | None:
    """Map an answer to one of the four non-unknown energy peaks, or ``None``."""
    value = _as_text(text)
    if not value:
        return None
    lowered = value.lower()
    for peak, aliases in _ENERGY_PEAK_ALIASES.items():
        if any(alias in lowered for alias in aliases):
            return peak
    return None


def _parse_minutes(text: str) -> int | None:
    """Extract a duration in minutes, or ``None``."""
    value = _as_text(text)
    if not value:
        return None
    match = _MINUTES_PATTERN.search(value)
    if not match:
        return None
    if match.group("half"):
        return 30
    if match.group("hours"):
        return int(match.group("hours")) * 60
    if match.group("num"):
        return int(match.group("num"))
    return None


def _parse_rest_period(text: str) -> dict[str, Any] | None:
    """Deterministically parse one rest period from an answer, or ``None``.

    Recognises "Sleep 23:00-07:00" and "23:00 to 7:00" style answers. ``days``
    defaults to every day when no weekday is mentioned. The result is the
    constructor dict for :class:`RestPeriod`, validated by the caller.
    """
    value = _as_text(text)
    if not value:
        return None
    match = _TIME_RANGE_PATTERN.search(value)
    if not match:
        return None
    start = _normalise_hhmm(match.group("start"))
    end = _normalise_hhmm(match.group("end"))
    if start is None or end is None or start == end:
        return None
    days = _parse_weekdays(value) or [0, 1, 2, 3, 4, 5, 6]
    title = value[: match.start()].strip(" -–—,:;，。()（）")
    if not title:
        title = _DEFAULT_REST_TITLE
    return {"title": title, "days": days, "start_time": start, "end_time": end}


def _parse_predictable_routine(text: str) -> dict[str, Any] | None:
    """Deterministically parse one predictable routine, or ``None``.

    Requires a title and a duration. An optional non-overnight time window
    becomes ``preferred_start`` / ``preferred_end``. The result is the
    constructor dict for :class:`PredictableRoutine`, validated by the caller.
    """
    value = _as_text(text)
    if not value:
        return None
    minutes = _parse_minutes(value)
    if minutes is None or not 1 <= minutes <= 480:
        return None
    duration_match = _MINUTES_PATTERN.search(value)
    title = value[: duration_match.start()].strip(" -–—,:;，。()（）")
    if not title:
        return None
    weekdays = _parse_weekdays(value) or [0, 1, 2, 3, 4, 5, 6]
    result: dict[str, Any] = {
        "title": title,
        "weekdays": weekdays,
        "estimated_minutes": minutes,
    }
    rng = _TIME_RANGE_PATTERN.search(value)
    if rng:
        start = _normalise_hhmm(rng.group("start"))
        end = _normalise_hhmm(rng.group("end"))
        # PredictableRoutine rejects overnight windows (end <= start).
        if start and end and start < end:
            result["preferred_start"] = start
            result["preferred_end"] = end
    return result


def _validate_rest_period(item: Any) -> dict[str, Any] | None:
    """Validate a rest-period candidate against the shared model, or ``None``."""
    if not isinstance(item, Mapping):
        return None
    try:
        period = RestPeriod(
            title=item.get("title"),
            days=item.get("days"),
            start_time=item.get("start_time"),
            end_time=item.get("end_time"),
        )
    except (ModelError, TypeError, ValueError):
        return None
    return {
        "title": period.title,
        "days": list(period.days),
        "start_time": period.start_time,
        "end_time": period.end_time,
    }


def _validate_predictable_routine(item: Any) -> dict[str, Any] | None:
    """Validate a predictable-routine candidate against the shared model."""
    if not isinstance(item, Mapping):
        return None
    try:
        routine = PredictableRoutine(
            title=item.get("title"),
            weekdays=item.get("weekdays"),
            estimated_minutes=item.get("estimated_minutes"),
            preferred_start=item.get("preferred_start"),
            preferred_end=item.get("preferred_end"),
        )
    except (ModelError, TypeError, ValueError):
        return None
    result: dict[str, Any] = {
        "title": routine.title,
        "weekdays": list(routine.weekdays),
        "estimated_minutes": routine.estimated_minutes,
    }
    if routine.preferred_start:
        result["preferred_start"] = routine.preferred_start
        if routine.preferred_end:
            result["preferred_end"] = routine.preferred_end
    return result


def _parse_structured_field(field: str, text: str) -> Any:
    """Parse one field's answer into a validated structured value, or ``None``.

    ``rest_periods`` / ``predictable_routines`` return a list of validated
    constructor dicts (a single answer usually yields one item); scalar fields
    return a scalar. ``None`` means "cannot be parsed reliably".
    """
    if field in ("preferred_work_start", "preferred_work_end"):
        return _parse_time(text)
    if field == "work_days":
        return _parse_weekdays(text)
    if field == "energy_peak":
        return _parse_energy_peak(text)
    if field == "rest_periods":
        item = _parse_rest_period(text)
        if item is None:
            return None
        validated = _validate_rest_period(item)
        return [validated] if validated else None
    if field == "predictable_routines":
        item = _parse_predictable_routine(text)
        if item is None:
            return None
        validated = _validate_predictable_routine(item)
        return [validated] if validated else None
    return None


def _build_structured_patch(
    field_map: Mapping[str, list[str]],
) -> tuple[dict[str, Any], dict[str, list[str]]]:
    """Turn ``field -> answers`` into (patch, needs_confirmation).

    ``patch`` maps field names to validated structured values ready for the
    integrator to merge into ``QuestionnaireData``. ``needs_confirmation``
    maps field names to the raw answers that could not be parsed reliably and
    must be surfaced for manual confirmation rather than guessed.
    """
    patch: dict[str, Any] = {}
    needs_confirmation: dict[str, list[str]] = {}
    for field in STRUCTURED_FIELDS:
        answers = [_as_text(a) for a in field_map.get(field, []) if _as_text(a)]
        if not answers:
            continue
        if field in ("rest_periods", "predictable_routines"):
            items: list[dict[str, Any]] = []
            unresolved: list[str] = []
            for text in answers:
                parsed = _parse_structured_field(field, text)
                if parsed:
                    items.extend(parsed)
                else:
                    unresolved.append(text)
            if items:
                patch[field] = items
            if unresolved:
                needs_confirmation[field] = unresolved
        else:
            value = None
            for text in answers:
                value = _parse_structured_field(field, text)
                if value is not None:
                    break
            if value is None:
                needs_confirmation[field] = answers
            else:
                patch[field] = value

    if field_map.get("goals"):
        patch["goals"] = [
            _as_text(a) for a in field_map["goals"] if _as_text(a)
        ]
    return patch, needs_confirmation


def _validate_weekdays(value: Any) -> list[int] | None:
    """Validate a 0-6 weekday list (0 = Monday), or ``None`` when invalid."""
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


def _validate_energy_peak_value(value: Any) -> str | None:
    """Return a valid energy peak, or ``None`` (never the ``unknown`` placeholder)."""
    text = _as_text(value).lower()
    if text in ("morning", "afternoon", "evening", "flexible"):
        return text
    return None


def _llm_extract_field(field: str, raw_answer: str, client: DeepSeekClient) -> Any:
    """LLM-assisted structured extraction for one field, or ``None``.

    Used only after deterministic parsing failed. The LLM reply is passed
    through Python schema validation; anything invalid is rejected (returning
    ``None``) so the raw answer stays under ``needs_confirmation``.
    """
    try:
        payload = client.chat_json(
            [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": render_extract_prompt(field, raw_answer)},
            ]
        )
    except AIError:
        return None
    source = payload if isinstance(payload, Mapping) else {}

    if field in ("preferred_work_start", "preferred_work_end"):
        return _parse_time(_as_text(source.get("time")))
    if field == "work_days":
        return _validate_weekdays(source.get("weekdays"))
    if field == "energy_peak":
        return _validate_energy_peak_value(source.get("energy_peak"))
    if field == "rest_periods":
        items = source.get("rest_periods")
        if not isinstance(items, (list, tuple)):
            return None
        validated = [v for v in (_validate_rest_period(i) for i in items) if v]
        return validated if validated else None
    if field == "predictable_routines":
        items = source.get("predictable_routines")
        if not isinstance(items, (list, tuple)):
            return None
        validated = [
            v for v in (_validate_predictable_routine(i) for i in items) if v
        ]
        return validated if validated else None
    return None


def _resolve_with_llm(
    patch: dict[str, Any],
    needs_confirmation: dict[str, list[str]],
    client: DeepSeekClient,
) -> tuple[dict[str, Any], dict[str, list[str]]]:
    """Attempt LLM extraction for fields deterministic parsing could not handle."""
    still_unresolved: dict[str, list[str]] = {}
    for field, answers in needs_confirmation.items():
        raw = answers[0] if answers else ""
        value = _llm_extract_field(field, raw, client)
        if value is None:
            still_unresolved[field] = answers
        elif field in ("rest_periods", "predictable_routines"):
            patch.setdefault(field, [])
            patch[field].extend(value)
        else:
            patch[field] = value
    return patch, still_unresolved


# ---------------------------------------------------------------------------
# Field state (Python-owned)
# ---------------------------------------------------------------------------


def _initial_field_states(
    questionnaire: Mapping[str, Any],
    confirmed_fields: set[str] | None = None,
    has_defaulted_fields: bool = False,
) -> tuple[list[str], list[str], list[str]]:
    """Derive (resolved, unknown, unresolved) from the questionnaire.

    When ``confirmed_fields`` is provided (V1.2 canonical path), a required
    field is resolved only if the frontend reported it as explicitly confirmed
    *and* it carries content; defaults never count as confirmation. When it is
    ``None`` (legacy callers), ``_field_filled`` still applies, but
    ``has_defaulted_fields`` prevents dataclass defaults (``09:00`` / ``22:00``
    / a full week) from silently passing as user facts.

    Optional fields are ignored entirely.
    """
    resolved: list[str] = []
    unresolved: list[str] = []
    confirmed = set(confirmed_fields) if confirmed_fields is not None else None
    for field in REQUIRED_FIELDS:
        if confirmed is not None:
            filled = field in confirmed and _field_filled(questionnaire, field)
        else:
            filled = _field_filled(
                questionnaire, field, has_defaulted_fields=has_defaulted_fields
            )
        if filled:
            resolved.append(field)
        else:
            unresolved.append(field)
    return resolved, [], unresolved


def _field_filled(
    questionnaire: Mapping[str, Any],
    field: str,
    has_defaulted_fields: bool = False,
) -> bool:
    """Whether ``field`` carries confirmed content.

    ``energy_peak`` is only resolved for a real value (not ``"unknown"``).
    When ``has_defaulted_fields`` is true, a value equal to the dataclass
    default is NOT treated as confirmation.
    """
    value = questionnaire.get(field)
    if field == "energy_peak":
        return _has_content(value) and _as_text(value).lower() != "unknown"
    if has_defaulted_fields and field in DEFAULTED_FIELDS:
        return _has_content(value) and value != DEFAULTED_FIELDS[field]
    return _has_content(value)


def _classify_answer(text: str) -> str:
    """Classify an answer as "resolved", "unknown", or "unresolved".

    * blank -> "unresolved" (no answer given; field stays open).
    * explicit don't-know / doesn't-apply -> "unknown" (never ask again).
    * anything else -> "resolved", including "none"/"nothing" which count as a
      confirmed empty value.
    """
    value = _as_text(text)
    if not value:
        return "unresolved"
    lowered = value.lower()
    if lowered in ("?", "？？", "???", "n/a", "na"):
        return "unknown"
    for marker in UNKNOWN_ANSWER_MARKERS:
        if marker in lowered:
            return "unknown"
    return "resolved"


# ---------------------------------------------------------------------------
# Activity normalisation
# ---------------------------------------------------------------------------


def _normalise_activities(
    raw: Any,
    questionnaire: Mapping[str, Any],
) -> list[ActivitySuggestion]:
    """Coerce classified activities into typed :class:`ActivitySuggestion`.

    Only the four documented categories survive; an unrecognised category is
    discarded rather than mapped onto a nearest guess. Suggestions are capped,
    de-duplicated by name and category, and medication timings the user never
    supplied are scrubbed.
    """
    if not isinstance(raw, (list, tuple)):
        return []

    user_text = _as_json(questionnaire).lower()
    suggestions: list[ActivitySuggestion] = []
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

        category_value = _normalise_category(
            item.get("suggested_category") or item.get("category")
        )
        if category_value is None:
            continue

        reason = _guard_medication_timing(
            name, _as_text(item.get("reason")), user_text
        )
        if not reason:
            reason = "Mentioned in the questionnaire."

        key = (_dedupe_key(name), category_value)
        if key in seen:
            continue
        seen.add(key)

        source_id = _as_text(item.get("source_task_id")) or _as_text(
            item.get("task_id")
        )

        suggestions.append(
            ActivitySuggestion(
                activity_name=name,
                suggested_category=ActivityCategory(category_value),
                reason=reason,
                source_task_id=source_id or None,
            )
        )

    return suggestions


def _normalise_category(value: Any) -> str | None:
    """Return one of the four category values, or ``None`` when unrecognisable."""
    if isinstance(value, Enum):
        value = value.value

    text = _as_text(value).lower().replace("-", "_").replace(" ", "_")
    text = "_".join(part for part in text.split("_") if part)

    if text in ACTIVITY_CATEGORIES:
        return text
    return CATEGORY_ALIASES.get(text)


def _guard_medication_timing(name: str, reason: str, user_text: str) -> str:
    """Remove clock times the user never gave, for medication-like activities."""
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
    """Keep only recognised question ids (q1..qn) with non-empty answers."""
    mapping = _as_mapping(answers)
    cleaned: dict[str, str] = {}
    for question_id, value in mapping.items():
        if not _ANSWER_ID_PATTERN.fullmatch(str(question_id)):
            continue
        text = _as_text(value)
        if text:
            cleaned[question_id] = text
    return cleaned


def _normalise_profile(
    payload: Mapping[str, Any],
    questionnaire: Mapping[str, Any],
) -> UserProfile:
    """Force a model reply into a typed :class:`UserProfile`."""
    source = payload if isinstance(payload, Mapping) else {}

    goals = _clean_list(source.get("goals")) or _clean_list(questionnaire.get("goals"))
    work_style = _as_text(source.get("work_style")) or _as_text(
        questionnaire.get("work_style")
    )
    preferences = _clean_list(source.get("preferences")) or _clean_list(
        questionnaire.get("preferences")
    )
    summary = _as_text(source.get("summary"))
    if not summary:
        summary = _fallback_summary(goals, work_style)

    return UserProfile(
        summary=summary,
        goals=goals,
        work_style=work_style,
        preferences=preferences,
        recommended_work_block_minutes=_coerce_block_minutes(
            source.get("recommended_work_block_minutes")
        ),
        break_preferences=_coerce_break_preferences(source.get("break_preferences")),
        scheduling_notes=_as_text(source.get("scheduling_notes")),
        is_fallback=False,
    )


def _build_fallback_profile(
    questionnaire: Mapping[str, Any],
    field_map: Mapping[str, Any] | None = None,
) -> UserProfile:
    """Deterministic typed profile built only from explicit user input.

    When ``field_map`` (the ``target_field -> answers`` map produced by
    :func:`map_answers_to_fields`) is provided, confirmed follow-up answers are
    preserved verbatim instead of being silently dropped when the API is down.
    ``goals`` answers are merged into ``goals``; every other field is kept in
    ``scheduling_notes`` with an explicit "not AI-generated" marker so the
    integrator can surface it for manual completion.
    """
    goals = _clean_list(questionnaire.get("goals"))
    preferences = _clean_list(questionnaire.get("preferences"))
    work_style = _as_text(questionnaire.get("work_style"))
    break_preferences = _coerce_break_preferences(questionnaire.get("break_preferences"))
    block_minutes = DEFAULT_WORK_BLOCK_MINUTES

    field_answers = _as_mapping(field_map)
    if field_answers.get("goals"):
        goals = goals + [
            _as_text(g) for g in field_answers["goals"] if _as_text(g)
        ]

    notes = [
        "Generated without AI because the consultation service was unavailable.",
        "Only information supplied in the questionnaire was used.",
        f"The {block_minutes}-minute work block is a system default, "
        "not a user preference.",
    ]
    if _has_content(questionnaire.get("fixed_commitments")):
        notes.append(
            "Fixed commitments come from the questionnaire and were not modified."
        )

    non_goal_answers = {
        field: texts
        for field, texts in field_answers.items()
        if field != "goals" and texts
    }
    if non_goal_answers:
        rendered = "; ".join(
            f"{field}: {_as_text(texts)}"
            if not isinstance(texts, (list, tuple))
            else f"{field}: {' / '.join(_as_text(t) for t in texts if _as_text(t))}"
            for field, texts in non_goal_answers.items()
        )
        notes.append(
            "Confirmed follow-up answers (preserved verbatim, not AI-generated): "
            + rendered
        )

    return UserProfile(
        summary=_fallback_summary(goals, work_style),
        goals=goals,
        work_style=work_style,
        preferences=preferences,
        recommended_work_block_minutes=block_minutes,
        break_preferences=break_preferences,
        scheduling_notes=" ".join(notes),
        is_fallback=True,
    )


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


def _coerce_block_minutes(value: Any) -> int:
    """Coerce a model value into a bounded work block length (default 50)."""
    try:
        minutes = int(value)
    except (TypeError, ValueError):
        return DEFAULT_WORK_BLOCK_MINUTES

    if minutes < MIN_WORK_BLOCK_MINUTES or minutes > MAX_WORK_BLOCK_MINUTES:
        return DEFAULT_WORK_BLOCK_MINUTES
    return minutes


def _coerce_break_preferences(value: Any) -> str:
    """Coerce break preferences into the V1.2 string shape."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (list, tuple, set)):
        return ", ".join(_clean_list(value))
    return ""


# ---------------------------------------------------------------------------
# Dictionary shims for the legacy wrappers
# ---------------------------------------------------------------------------


def _suggestion_to_dict(suggestion: ActivitySuggestion) -> dict[str, str]:
    result: dict[str, str] = {
        "activity_name": suggestion.activity_name,
        "suggested_category": suggestion.suggested_category.value,
        "reason": suggestion.reason,
    }
    if suggestion.source_task_id:
        result["source_task_id"] = suggestion.source_task_id
    return result


def _profile_to_dict(profile: UserProfile) -> dict[str, Any]:
    return {
        "summary": profile.summary,
        "goals": list(profile.goals),
        "work_style": profile.work_style,
        "preferences": list(profile.preferences),
        "recommended_work_block_minutes": profile.recommended_work_block_minutes,
        "break_preferences": profile.break_preferences,
        "scheduling_notes": profile.scheduling_notes,
        "is_fallback": profile.is_fallback,
    }


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
    """Coerce questionnaire-like input into a plain dictionary."""
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
    """Convert a questionnaire into something ``json.dumps`` renders readably."""
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
    """Return a list of non-empty trimmed strings."""
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
    """Render one list entry as readable text."""
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
