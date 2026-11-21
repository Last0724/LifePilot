"""Prompt templates for the LifePilot AI consultation (Core Models V1.1).

Two calls are made per user:

1. ANALYSIS - read the questionnaire, propose at most two follow-ups in
   priority order, and classify the activities the user already mentioned.
2. PROFILE  - turn the *confirmed* questionnaire plus the follow-up answers
   into a structured profile.

Both prompts demand a single JSON object. The reply is always validated by
``core.ai_consultant`` before it reaches the scheduler, so the model is
treated as an unreliable narrator rather than an authority.

Category vocabulary
-------------------
``ActivityCategory`` belongs to ``core.models`` (owned by the Technical
Lead). This module never redefines it: it imports the enum when it exists and
otherwise falls back to the same four literal values agreed in the V1.1
contract. Prompt text and validator therefore share one vocabulary, and
``core.ai_consultant`` imports it from here rather than keeping a second copy.
"""

from __future__ import annotations

MAX_FOLLOW_UP_QUESTIONS = 2
MAX_ACTIVITY_SUGGESTIONS = 12
MIN_WORK_BLOCK_MINUTES = 15
MAX_WORK_BLOCK_MINUTES = 120

# Literal values from the V1.1 contract, used only while core.models has not
# landed. Once it does, the enum is the source of truth.
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

# P0 is the most important tier. Questions are sorted by this order before the
# two-question cap is applied.
QUESTION_PRIORITIES = ("P0", "P1", "P2", "P3")

SYSTEM_PROMPT = (
    "You are the consultation engine of LifePilot, a personal productivity "
    "planner. You turn a user's stated goals, tasks and constraints into a "
    "compact, honest profile. You never invent facts the user did not state. "
    "You always reply with exactly one JSON object and nothing else."
)

ANALYSIS_PROMPT = """Analyse the questionnaire below.

Questionnaire (JSON):
{questionnaire}

Understand this person's real week before trying to optimise it. Ask about
missing information in this priority order, highest tier first:

  P0  Hard commitments: classes, meetings, appointments - exact times and
      weekdays.
  P1  Rest and recovery: sleep, protected rest, regular breaks.
  P2  Predictable routines: meals, laundry, other recurring daily activities,
      and the time window they usually happen in.
  P3  Uncertain tasks: studying, programming, reports, goals, deadlines, work
      preferences.

Question rules:
- Never ask a lower-priority question while an important higher-priority gap
  is still open. If P0 information is missing, only ask P0 questions.
- Never ask about anything the questionnaire already answers.
- Never ask two questions that would collect the same information.
- At most {max_questions} questions. Fewer is better.
- Each question must be answerable in one short sentence.
- Never ask about medication timing. That may only come from the user.

Task fields you may receive:
- estimated_minutes is the user's own estimate. Treat it as a starting point,
  never as a scheduling decision.
- duration_type is either "predictable" or "uncertain". Respect it when
  classifying: "predictable" maps to {predictable}, "uncertain" maps to
  {uncertain}.

Activity classification:
- Classify the activities the user already mentioned into exactly one of
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
  "follow_up_questions": [
    {{"id": "q1", "question": "...", "priority": "P0",
      "target_field": "fixed_commitments"}}
  ],
  "activity_suggestions": [
    {{"activity_name": "...", "suggested_category": "{hard_commitment}",
      "reason": "...", "source_task_id": ""}}
  ]
}}

JSON rules:
- follow_up_questions: at most {max_questions}, ordered by priority.
- priority must be one of {priorities}.
- target_field names the questionnaire field the question fills in.
- Return an empty list when nothing needs asking.
- activity_suggestions: only activities the user actually mentioned.
- suggested_category must be one of {categories}.
- Omit "source_task_id" when the activity cannot be mapped to a task.
- Return empty lists rather than omitting either key.
- Return raw JSON. No markdown fences, no commentary.
"""

PROFILE_PROMPT = """Build the final user profile from confirmed information.

Confirmed questionnaire (JSON). The user has already accepted or corrected
every entry here, so treat it as fact:
{questionnaire}

Follow-up answers (JSON; keys match the question ids, empty when no question
was asked):
{follow_up_answers}

Reply with exactly this JSON shape:
{{
  "summary": "two or three sentences",
  "goals": ["..."],
  "work_style": "short description",
  "preferences": ["..."],
  "recommended_work_block_minutes": 25,
  "break_preferences": ["..."],
  "scheduling_notes": "practical notes for the scheduler"
}}

Rules:
- Use only the confirmed questionnaire and the answers above. Do not
  reintroduce activities that were suggested earlier but not confirmed.
- recommended_work_block_minutes must be an integer between
  {min_block} and {max_block}.
- scheduling_notes may refer to fixed commitments as constraints, but must
  never restate them as a structured field.
- Never output fixed_commitments. The scheduler reads those from the
  questionnaire, and the model must not restate or alter them.
- Return raw JSON. No markdown fences, no commentary.
"""


def render_analysis_prompt(questionnaire: str) -> str:
    """Fill the analysis prompt with the category vocabulary of the moment.

    A helper rather than ``str.format`` at the call site, because the same
    four values appear in five places (ladder examples, JSON example, and the
    allowed-values list) and they must never disagree.
    """
    categories = _categories()

    return ANALYSIS_PROMPT.format(
        questionnaire=questionnaire,
        max_questions=MAX_FOLLOW_UP_QUESTIONS,
        max_suggestions=MAX_ACTIVITY_SUGGESTIONS,
        categories=", ".join(categories),
        priorities=", ".join(QUESTION_PRIORITIES),
        hard_commitment=categories[0],
        rest_period=categories[1],
        predictable_routine=categories[2],
        uncertain_task=categories[3],
        predictable=categories[2],
        # "uncertain" is both a duration_type and the prefix of a category,
        # so it gets its own placeholder name.
        uncertain=categories[3],
    )


def _categories() -> tuple[str, ...]:
    """Return exactly four category values, padding a short enum if needed."""
    values = tuple(ACTIVITY_CATEGORIES)
    if len(values) >= 4:
        return values[:4]
    return values + _FALLBACK_CATEGORIES[len(values) :]
