"""Prompt templates for the LifePilot AI consultation.

Two calls are made per user:

1. ANALYSIS - read the questionnaire and propose at most two follow-ups,
   each carrying a stable id (``q1``, ``q2``) so the UI can round-trip the
   answers under the same keys.
2. PROFILE  - turn the questionnaire plus those answers into a structured
   profile.

Both prompts demand a single JSON object. The reply is always validated by
``core.ai_consultant`` before it reaches the scheduler, so the model is
treated as an unreliable narrator rather than an authority.
"""

from __future__ import annotations

MAX_FOLLOW_UP_QUESTIONS = 2
MIN_WORK_BLOCK_MINUTES = 15
MAX_WORK_BLOCK_MINUTES = 120

SYSTEM_PROMPT = (
    "You are the consultation engine of LifePilot, a personal productivity "
    "planner. You turn a user's stated goals, tasks and constraints into a "
    "compact, honest profile. You never invent facts the user did not state. "
    "You always reply with exactly one JSON object and nothing else."
)

ANALYSIS_PROMPT = """Analyse the questionnaire below.

Questionnaire (JSON):
{questionnaire}

Decide whether you have enough information to plan this person's week.
If something essential is missing, ask at most {max_questions} questions.
Only ask about goals, available time, or work preferences that are genuinely
absent. Never ask about something the user already answered.

Reply with exactly this JSON shape:
{{
  "follow_up_questions": [
    {{"id": "q1", "question": "..."}},
    {{"id": "q2", "question": "..."}}
  ]
}}

Rules:
- At most {max_questions} questions, in the order they should be asked.
- Use the ids "q1" and "q2", in that order.
- Return an empty list when the questionnaire is already sufficient.
- Each question must be answerable in one short sentence.
- Return raw JSON. No markdown fences, no commentary.
"""

PROFILE_PROMPT = """Build the final user profile.

Questionnaire (JSON):
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
- Use only information the user provided, directly or by reasonable
  inference from what they said.
- recommended_work_block_minutes must be an integer between
  {min_block} and {max_block}.
- Never output fixed_commitments. The scheduler reads those from the
  questionnaire, and the model must not restate or alter them.
- Return raw JSON. No markdown fences, no commentary.
"""
