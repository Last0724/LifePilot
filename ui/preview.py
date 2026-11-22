"""Run with: python -m streamlit run ui/preview.py --theme.base light"""

from datetime import date, timedelta

import streamlit as st

from ui.account import ACCOUNT_KEY, render_account_menu, render_sign_in
from ui.calendar_input import calendar_entries
from ui.components import apply_theme, render_brand
from ui.consultation import (
    build_mock_schedule, consultation_description, render_extraction_review, render_final_confirmation,
    render_guided_follow_up, start_consultation,
)
from ui.dashboard import render_dashboard
from ui.experience import render_experience
from ui.mascot import render_mascot
from ui.mechanisms import observe_calendar, record_task_updates, render_mechanisms, reset_plan_mechanisms
from ui.planner import add_weekly_task
from ui.questionnaire import render_questionnaire
from ui.showcase import render_showcase
from ui.welcome import render_welcome

DEMO_START = date(2026, 11, 23)
MECHANISM_KEY = "preview_demo"
SCHEDULE_KEY = "preview_schedule"
DEMO_PROFILE = {
    "summary": "You’re preparing a research proposal while keeping your project commitments in place. "
               "Set aside focused mornings for writing and leave lighter work for the afternoon."
}
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


def _open_page(page: str) -> None:
    st.session_state.preview_page = page
    if page != "planner":
        observe_calendar(MECHANISM_KEY, False)


def _after_calendar(view: str) -> None:
    observe_calendar(MECHANISM_KEY, view == "Week")
    if view == "Week":
        render_mechanisms(SCHEDULE_KEY, MECHANISM_KEY, DEMO_START)


def _show_plan(
    profile: dict, schedule: list[dict] | None = None, unscheduled: list[str] | None = None
) -> None:
    st.session_state.preview_profile = profile
    st.session_state.preview_schedule = schedule if schedule is not None else _demo_schedule()
    st.session_state.preview_using_calendar = schedule is not None
    st.session_state.preview_unscheduled = unscheduled or []
    st.session_state.preview_page = "planner"
    reset_plan_mechanisms(MECHANISM_KEY)
    st.rerun()


def main() -> None:
    st.set_page_config(page_title="LifePilot", page_icon="✦", layout="wide")
    view = st.query_params.get("view")
    if view not in ("classic", "brand"):
        render_experience()
        return

    apply_theme()
    if view == "brand":
        render_showcase()
        return

    state = st.session_state
    page = state.setdefault("preview_page", "planner")
    if page == "planner" and SCHEDULE_KEY not in state:
        state.preview_profile = DEMO_PROFILE
        state.preview_schedule = _demo_schedule()

    with st.container(key="lp_preview"):
        with st.container(key="lp_header"):
            brand, navigation = st.columns([4, 2], vertical_alignment="center")
            with brand:
                render_brand()
            with navigation, st.container(
                key="lp_header_actions", horizontal=True, horizontal_alignment="right", vertical_alignment="center",
            ):
                st.html('<a class="lp-classic-return" href="?">Return to LifePilot / 返回新版</a>', width="content")
                if page == "planner":
                    st.button("Plan my week", on_click=_open_page, args=("questionnaire",))
                    if ACCOUNT_KEY in state:
                        render_account_menu()
                    else:
                        st.button("Sign in / 登录", on_click=_open_page, args=("sign_in",), key="preview_open_sign_in")
                else:
                    st.button("Back to calendar", on_click=_open_page, args=("planner",))
                render_mascot()

        if page == "sign_in":
            if name := render_sign_in():
                state[ACCOUNT_KEY] = name
                _open_page("planner")
                st.rerun()
        elif page == "welcome":
            action = render_welcome(key="preview_welcome", offer_demo=True)
            if action == "start":
                state.preview_page = "questionnaire"
                st.rerun()
            if action == "demo":
                _show_plan(DEMO_PROFILE)
        elif page == "questionnaire":
            questionnaire = render_questionnaire(key="preview_questionnaire", default_date=DEMO_START, consultation=True)
            if questionnaire is not None:
                state.preview_consultation = start_consultation(
                    questionnaire, calendar_entries("preview_questionnaire"),
                    consultation_description("preview_questionnaire"), DEMO_START,
                )
                state.preview_page = "extraction"
                st.rerun()
        elif page == "extraction":
            with st.container(key="lp_consultation"):
                if render_extraction_review(state.preview_consultation):
                    state.preview_page = "follow_up"
                    st.rerun()
        elif page == "follow_up":
            with st.container(key="lp_consultation"):
                if next_page := render_guided_follow_up(state.preview_consultation):
                    state.preview_page = next_page
                    st.rerun()
        elif page == "confirmation":
            with st.container(key="lp_consultation"):
                draft = state.preview_consultation
                if payload := render_final_confirmation(draft):
                    state.preview_payload = payload
                    schedule, unscheduled = build_mock_schedule(draft, payload)
                    summary = "\n".join(payload["goals"] or payload["tasks"])
                    _show_plan({"summary": summary}, schedule, unscheduled)
        elif page == "planner":
            st.caption(
                "Preview · Plan built from your confirmed details"
                if state.get("preview_using_calendar", False) else "Preview · Example schedule"
            )
            updated = render_dashboard(
                state.preview_profile, state.preview_schedule, week_start=DEMO_START,
                key="preview_dashboard",
                add_task=lambda: add_weekly_task(DEMO_START, SCHEDULE_KEY),
                after_calendar=_after_calendar,
            )
            if updated is not None:
                record_task_updates(state.preview_schedule, updated, MECHANISM_KEY)
                state.preview_schedule = updated
                st.rerun()
            if unscheduled := state.get("preview_unscheduled"):
                with st.expander(f"Not scheduled · {len(unscheduled)}"):
                    st.caption("The mock planner did not find an open time for these tasks.")
                    for title in unscheduled:
                        st.text(title)
            st.button("About LifePilot", type="tertiary", on_click=_open_page, args=("welcome",))


if __name__ == "__main__":
    main()
