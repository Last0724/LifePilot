"""Run with:

    python -m streamlit run ux/preview.py --theme.base light

Independent preview for Feature 02 (Guru Template upselling).  It reuses B's
theme, planner and dashboard components but never modifies files under ``ui/``.
"""

from datetime import date, timedelta

import streamlit as st

from ui.components import apply_theme, render_brand
from ui.dashboard import render_dashboard, render_profile
from ux.marketplace import (
    get_state,
    render_advanced_features,
    render_marketplace,
    render_post_plan_upsell,
)

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
DEMO_PROFILE = {
    "summary": (
        "You are preparing a research proposal while keeping project commitments "
        "in place. Focused mornings suit writing; lighter admin fits the afternoon."
    )
}


def _demo_schedule() -> list[dict]:
    return [
        {
            "id": f"ux_demo_{index}",
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


def _reset() -> None:
    for key in list(st.session_state):
        if isinstance(key, str) and key.startswith("ux_"):
            del st.session_state[key]
    st.session_state.ux_page = "welcome"
    st.rerun()


def _go(page: str) -> None:
    st.session_state.ux_page = page
    st.rerun()


def _ensure_demo_state() -> None:
    state = st.session_state
    state.setdefault("ux_page", "welcome")
    state.setdefault("ux_schedule", _demo_schedule())
    state.setdefault("ux_profile", DEMO_PROFILE)


def _welcome() -> None:
    st.html(
        '<section class="lp-hero"><div>'
        "<h1>Plan less.<br><em>Live more.</em></h1>"
        "<p>LifePilot turns your goals and commitments into a realistic week. "
        "This preview also demonstrates the Guru Template marketplace.</p>"
        "</div><div class='lp-sample'><h2>Try the demo</h2>"
        "<p>Generate a sample schedule, then explore free and premium planning systems.</p>"
        "</div></section>"
    )
    first, second = st.columns(2)
    with first:
        if st.button("Generate my demo schedule", type="primary", use_container_width=True):
            _go("planner")
    with second:
        if st.button("Explore Guru Templates", use_container_width=True):
            _go("marketplace")
    st.caption("Simulated product demo · no account, payment or real scheduling data required.")


def _top_bar() -> None:
    state = get_state()
    brand, plan, reset = st.columns([3, 2, 1])
    with brand:
        render_brand()
    with plan:
        if state.is_premium:
            st.caption("Plan: **Guru Premium** (simulated)")
        else:
            st.caption("Plan: Free · upgrade is simulated")
    with reset:
        if st.button("Reset demo", key="ux_reset_top"):
            _reset()


def _planner() -> None:
    state = get_state()
    st.caption("Demo schedule · 23–29 Nov 2026")
    render_profile(st.session_state.ux_profile)
    updated = render_dashboard(
        st.session_state.ux_profile,
        st.session_state.ux_schedule,
        week_start=DEMO_START,
        key="ux_dashboard",
    )
    if updated is not None:
        st.session_state.ux_schedule = updated
        st.rerun()

    st.divider()
    nav_left, nav_right = st.columns(2)
    with nav_left:
        if st.button("Browse all Guru Templates", use_container_width=True):
            _go("marketplace")
    with nav_right:
        if st.button("See advanced features", use_container_width=True):
            _go("advanced")

    if render_post_plan_upsell(state):
        _go("marketplace")


def _marketplace() -> None:
    state = get_state()
    if st.button("← Back to my plan", key="ux_back_from_market"):
        _go("planner")
    render_marketplace(state)
    st.divider()
    if st.button("See advanced features →", key="ux_advanced_link"):
        _go("advanced")


def _advanced() -> None:
    state = get_state()
    if st.button("← Back to my plan", key="ux_back_from_advanced"):
        _go("planner")
    render_advanced_features(state)
    st.divider()
    if st.button("Browse Guru Templates →", key="ux_market_link"):
        _go("marketplace")


def main() -> None:
    st.set_page_config(page_title="LifePilot · Guru Templates", page_icon="✦", layout="wide")
    apply_theme()
    _ensure_demo_state()
    with st.container(key="lp_preview"):
        _top_bar()
        page = st.session_state.ux_page
        if page == "welcome":
            _welcome()
        elif page == "planner":
            _planner()
        elif page == "marketplace":
            _marketplace()
        elif page == "advanced":
            _advanced()
        else:
            st.session_state.ux_page = "welcome"
            st.rerun()


if __name__ == "__main__":
    main()
