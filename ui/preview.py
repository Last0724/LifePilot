"""Run with: python -m streamlit run ui/preview.py --theme.base light"""

from datetime import date, timedelta

import streamlit as st

from ui.components import apply_theme, render_brand
from ui.dashboard import render_dashboard, render_profile
from ui.questionnaire import render_follow_up, render_questionnaire
from ui.welcome import render_welcome

DEMO_START = date(2026, 11, 23)
DEMO_EVENTS = (
    (0, "Outline research proposal", "09:00", "10:30", "Study", False, False),
    (0, "Team check-in", "11:00", "11:30", "Work", False, True),
    (0, "Review reading notes", "14:00", "14:45", "Study", True, False),
    (1, "Draft the first section", "09:00", "10:30", "Study", False, False),
    (1, "Design workshop", "13:00", "14:00", "Work", False, True),
    (2, "Library session", "10:00", "11:00", "Study", False, True),
    (2, "Organize references", "14:00", "15:00", "Study", False, False),
    (3, "Review the draft", "09:30", "10:30", "Study", False, False),
    (3, "Send feedback", "15:00", "15:30", "Work", False, False),
    (4, "Finalize the proposal", "09:00", "10:30", "Study", False, False),
    (4, "Weekly project sync", "11:00", "11:45", "Work", False, True),
    (5, "Plan next week", "10:30", "11:00", "Personal", False, False),
)


def _demo_schedule() -> list[dict]:
    return [
        {
            "id": f"demo_{index}",
            "title": title,
            "date": (DEMO_START + timedelta(days=offset)).isoformat(),
            "start": start,
            "end": end,
            "category": category,
            "completed": completed,
            "is_fixed": fixed,
        }
        for index, (offset, title, start, end, category, completed, fixed) in enumerate(DEMO_EVENTS)
    ]


def _restart() -> None:
    for key in list(st.session_state):
        if isinstance(key, str) and key.startswith("preview_"):
            del st.session_state[key]


def _show_plan(profile: dict) -> None:
    st.session_state.preview_profile = profile
    st.session_state.preview_schedule = _demo_schedule()
    st.session_state.preview_page = "planner"
    st.rerun()


def main() -> None:
    st.set_page_config(page_title="LifePilot", page_icon="✦", layout="wide")
    apply_theme()
    state = st.session_state
    page = state.setdefault("preview_page", "welcome")
    with st.container(key="lp_preview"):
        brand, navigation = st.columns([4, 1])
        with brand:
            render_brand()
        if page != "welcome":
            navigation.button("Back to welcome", on_click=_restart)

        if page == "welcome":
            action = render_welcome(key="preview_welcome", offer_demo=True)
            if action == "start":
                state.preview_page = "questionnaire"
                st.rerun()
            if action == "demo":
                _show_plan({
                    "summary": "You’re preparing a research proposal while keeping your project "
                    "commitments in place. Set aside focused mornings for writing and leave "
                    "lighter work for the afternoon.",
                })
        elif page == "questionnaire":
            questionnaire = render_questionnaire(key="preview_questionnaire", default_date=DEMO_START)
            if questionnaire is not None:
                state.preview_payload = questionnaire
                state.preview_page = "follow_up"
                st.rerun()
        elif page == "follow_up":
            st.caption("Preview · Sample analysis")
            questions = []
            if not state.preview_payload["preferences"]:
                questions = [{"id": "q1", "question": "When is it easiest for you to focus?"}]
            answers = render_follow_up(questions, key="preview_follow_up")
            if answers is not None:
                state.preview_answers = answers
                state.preview_page = "analysis"
                st.rerun()
        elif page == "analysis":
            st.title("Ready to plan")
            st.caption("Preview · The next screen uses an example schedule.")
            questionnaire = state.preview_payload
            priorities = questionnaire["goals"] or questionnaire["tasks"]
            summary = "\n".join(priorities)
            if focus := state.preview_answers.get("q1"):
                summary += f"\n\nYou said it’s easiest to focus {focus}."
            profile = {"summary": summary}
            render_profile(profile)
            if st.button("View weekly plan", type="primary"):
                _show_plan(profile)
        elif page == "planner":
            st.caption("Preview · Example schedule")
            updated = render_dashboard(
                state.preview_profile, state.preview_schedule, week_start=DEMO_START,
                key="preview_dashboard",
            )
            if updated is not None:
                state.preview_schedule = updated
                st.rerun()


if __name__ == "__main__":
    main()
