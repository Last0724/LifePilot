"""Prompt templates for the LifePilot AI consultation (Core Models V1.2).

Three LLM responsibilities, three prompts. Python owns every decision; the
model is treated as an unreliable narrator that only does three things:

1. PHRASE   - turn the fields Python selected into natural questions.
2. CLASSIFY - classify the activities the user already mentioned.
3. PROFILE  - turn *confirmed* information into a structured profile.

Neither the phrase nor the classify step decides priority, which fields to
ask, or how many questions appear. Those are owned by
``core.ai_consultant.ConsultationController``.

Category vocabulary
-------------------
``ActivityCategory`` belongs to ``core.models`` (owned by DSH). This module
never redefines it: it imports the enum when it exists and otherwise falls
back to the same four literal values. Prompt text and validator therefore
share one vocabulary, and ``core.ai_consultant`` imports it from here rather
than keeping a second copy.
"""

from __future__ import annotations

MAX_FOLLOW_UP_QUESTIONS = 2
MAX_ACTIVITY_SUGGESTIONS = 12
MIN_WORK_BLOCK_MINUTES = 15
MAX_WORK_BLOCK_MINUTES = 180
DEFAULT_WORK_BLOCK_MINUTES = 50

# Literal values used only while core.models has not landed. Once it does,
# the enum is the source of truth.
_FALLBACK_CATEGORIES = (
    "hard_commitment",
    "rest_period",
    "predictable_routine",
    "uncertain_task",
)

try:  # pragma: no cover - depends on whether core/models.py exists yet
    from core.models import ActivityCategory as _ActivityCategory
except Exception:  # ImportError today, a circular import is possible later
    _ActivityCategory = None

if _ActivityCategory is None:
    ACTIVITY_CATEGORIES = _FALLBACK_CATEGORIES
else:
    ACTIVITY_CATEGORIES = tuple(
        str(getattr(member, "value", member)) for member in _ActivityCategory
    )

# P0 is the most important tier. The controller maps missing fields onto these
# five tiers and selects questions in this order; the prompt only echoes it so
# the model phrases in the order it is handed.
QUESTION_PRIORITIES = ("P0", "P1", "P2", "P3", "P4")

# Human-facing meaning of each questionnaire field the consultation may ask
# about. Used only to give the phrasing model enough context to write a good
# question; it is not a decision surface.
FIELD_DESCRIPTIONS = {
    "fixed_commitments": "hard commitments (classes, meetings, appointments) "
    "with exact times and days",
    "rest_periods": "protected rest and recovery (sleep, breaks)",
    "predictable_routines": "recurring daily activities (meals, laundry) and "
    "when they usually happen",
    "tasks": "specific tasks to schedule (study, work, errands) and deadlines",
    "preferred_work_start": "the time the user's workday starts",
    "preferred_work_end": "the time the user's workday ends",
    "work_days": "which days of the week the user works",
    "energy_peak": "when the user has the most energy (morning, afternoon, evening)",
    "goals": "long-term goals the week should make progress on",
    "habits": "existing habits or routines to preserve",
    "challenges": "challenges or obstacles to plan around",
    "notes": "anything else the user wants the planner to know",
}

SYSTEM_PROMPT = (
    "You are the consultation engine of LifePilot, a personal productivity "
    "planner. You turn a user's stated goals, tasks and constraints into a "
    "compact, honest profile. You never invent facts the user did not state. "
    "You always reply with exactly one JSON object and nothing else."
)

CLASSIFY_PROMPT = """Classify the activities this user already mentioned.

Questionnaire (JSON):
{questionnaire}

Classify only the activities the user actually mentioned, into exactly one of
these categories: {categories}.
- Examples: Physics class -> {hard_commitment}; sleep -> {rest_period};
  lunch -> {predictable_routine}; studying calculus -> {uncertain_task}.
- These are suggestions for the user to confirm, never confirmed facts.
- Never invent a time or a day for any activity. If the user gave no time,
  do not supply one.
- Never invent a medication schedule. If the user mentioned medication but no
  timing, say so in the reason instead of choosing a time.
- At most {max_suggestions} activities.

Reply with exactly this JSON shape:
{{
  "activity_suggestions": [
    {{"activity_name": "...", "suggested_category": "{hard_commitment}",
      "reason": "...", "source_task_id": ""}}
  ]
}}

JSON rules:
- activity_suggestions: only activities the user actually mentioned.
- suggested_category must be one of {categories}.
- reason is required and must be one short sentence.
- Omit "source_task_id" when the activity cannot be mapped to a task.
- Return an empty list when there is nothing to classify.
- Return raw JSON. No markdown fences, no commentary.
"""

PHRASE_PROMPT = """Write follow-up questions for the fields listed below.

Questionnaire (JSON):
{questionnaire}

The consultation controller has already decided which fields to ask about.
Do not add, remove, or reorder fields, and do not ask about anything else.
For each field, write exactly one short, natural question the user can answer
in a single sentence.

Fields to ask about, highest priority first:
{fields}

Rules:
- Keep each "target_field" exactly as listed (do not rename or paraphrase it).
- Ask about nothing else.
- Never ask about medication timing.
- One question per field.

Reply with exactly this JSON shape:
{{
  "follow_up_questions": [
    {{"question": "...", "target_field": "fixed_commitments"}}
  ]
}}

JSON rules:
- Return one object per field, in the same order.
- Return an empty list when no fields are listed.
- Return raw JSON. No markdown fences, no commentary.
"""

PROFILE_PROMPT = """Build the final user profile from confirmed information.

Confirmed questionnaire (JSON). The user has already accepted or corrected
every entry here, so treat it as fact:
{questionnaire}

Follow-up answers (JSON). Keys are the questionnaire field names each answer
belongs to, and values are the user's verbatim answers; it is empty when no
question was asked:
{follow_up_answers}

Reply with exactly this JSON shape:
{{
  "summary": "two or three sentences",
  "goals": ["..."],
  "work_style": "short description",
  "preferences": ["..."],
  "recommended_work_block_minutes": {default_block},
  "break_preferences": "a short note about breaks, or an empty string",
  "scheduling_notes": "practical notes for the scheduler"
}}

Rules:
- Use only the confirmed questionnaire and the answers above. Do not
  reintroduce activities that were suggested earlier but not confirmed.
- The follow-up answers are already grouped by field; read the field name
  from the JSON key, never guess a field from the wording of an answer.
- recommended_work_block_minutes must be an integer between
  {min_block} and {max_block}.
- break_preferences is a single short string, not a list.
- scheduling_notes may refer to fixed commitments as constraints, but must
  never restate them as a structured field.
- Never output fixed_commitments. The scheduler reads those from the
  questionnaire, and the model must not restate or alter them.
- Return raw JSON. No markdown fences, no commentary.
"""


EXTRACT_PROMPT = """Extract structured scheduling data from a user's answer.

The answer belongs to the questionnaire field "{field}".

Raw answer:
{raw_answer}

Return exactly one JSON object shaped for this field:

- "preferred_work_start" or "preferred_work_end":
  {{"time": "HH:MM"}}
- "work_days":
  {{"weekdays": [0,1,2,3,4,5,6]}}  (0 = Monday, 6 = Sunday)
- "energy_peak":
  {{"energy_peak": "morning"}}  (one of morning / afternoon / evening / flexible)
- "rest_periods":
  {{"rest_periods": [{{"title": "...", "days": [0..6],
    "start_time": "HH:MM", "end_time": "HH:MM"}}]}}
- "predictable_routines":
  {{"predictable_routines": [{{"title": "...", "weekdays": [0..6],
    "estimated_minutes": N, "preferred_start": "HH:MM",
    "preferred_end": "HH:MM"}}]}}

Rules:
- Use only information present in the raw answer. Never invent a time, day or
  duration that the user did not state.
- If the answer does not contain enough information to fill the required
  fields, return {{}}.
- Return raw JSON. No markdown fences, no commentary.
"""


def render_extract_prompt(field: str, raw_answer: str) -> str:
    """Fill the structured-extraction prompt for one field and one answer."""
    return EXTRACT_PROMPT.format(field=field, raw_answer=raw_answer)


def render_classify_prompt(questionnaire: str) -> str:
    """Fill the classification prompt with the category vocabulary of the moment."""
    categories = _categories()
    return CLASSIFY_PROMPT.format(
        questionnaire=questionnaire,
        max_suggestions=MAX_ACTIVITY_SUGGESTIONS,
        categories=", ".join(categories),
        hard_commitment=categories[0],
        rest_period=categories[1],
        predictable_routine=categories[2],
        uncertain_task=categories[3],
    )


def render_phrase_prompt(questionnaire: str, fields: list[dict]) -> str:
    """Fill the phrasing prompt with the fields Python selected.

    ``fields`` is a list of ``{"field": ..., "priority": "P0", "meaning": ...}``
    already ordered by priority. It is rendered verbatim so the model phrases
    in the same order and never invents extra fields.
    """
    lines = []
    for item in fields:
        meaning = item.get("meaning") or item.get("field")
        lines.append(f'- {item["field"]} ({item["priority"]}): {meaning}')
    return PHRASE_PROMPT.format(
        questionnaire=questionnaire,
        fields="\n".join(lines) if lines else "(none)",
    )


def _categories() -> tuple[str, ...]:
    """Return exactly four category values, padding a short enum if needed."""
    values = tuple(ACTIVITY_CATEGORIES)
    if len(values) >= 4:
        return values[:4]
    return values + _FALLBACK_CATEGORIES[len(values):]
