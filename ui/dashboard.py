"""Profile, completion metrics, and weekly and daily navigation."""

from collections.abc import Callable
from datetime import date, timedelta
from html import escape

import streamlit as st

from ui.planner import render_daily_planner, render_task_editor, render_weekly_planner


def render_profile(profile: dict) -> None:
    """Display the profile summary returned by the AI consultation module."""
    summary = profile.get("summary") or "Your profile will appear here once it is available."
    st.html(
        '<section class="lp-profile"><h2>Your planning profile</h2>'
        f"<p>{escape(summary)}</p></section>"
    )


def render_dashboard(
    profile: dict,
    schedule: list[dict],
    *,
    week_start: date | None = None,
    key: str = "dashboard",
    add_task: Callable[[], None] | None = None,
    after_calendar: Callable[[str], None] | None = None,
) -> list[dict] | None:
    """Render the current week and return a replacement schedule when an edit is saved."""
    if week_start is None:
        week_start = min((date.fromisoformat(task["date"]) for task in schedule), default=date.today())
    days = [week_start + timedelta(days=offset) for offset in range(7)]
    week_dates = {day.isoformat() for day in days}
    planned = [task for task in schedule if task["date"] in week_dates]
    flexible = [task for task in planned if not task["is_fixed"]]
    completed = sum(task["completed"] for task in flexible)

    st.title("Weekly calendar", anchor=False)
    with st.container(key="lp_calendar_toolbar", horizontal=True, vertical_alignment="center"):
        st.html(f'<p class="lp-calendar-range">{days[0]:%d %b} – {days[-1]:%d %b %Y}</p>', width="content")
        if after_calendar is not None and st.session_state.get(f"{key}_view", "Week") == "Week":
            st.html('<a class="lp-demo-shortcut" href="#lp-demo-features">Demo features</a>', width="content")
        if add_task is not None and st.button("Add task", icon=":material/add:", key=f"{key}_quick_add"):
            add_task()

    view = st.radio(
        "Planner view", ("Week", "Day"), horizontal=True, key=f"{key}_view", label_visibility="collapsed"
    )
    if view == "Week":
        render_weekly_planner(planned, week_start)
        updated = None
    else:
        day = st.selectbox("Day", days, format_func=lambda value: f"{value:%A, %d %b}", key=f"{key}_day")
        render_daily_planner(planned, day)
        updated = render_task_editor(schedule, day, key=f"{key}_editor")
    if updated is not None:
        return updated

    if after_calendar is not None:
        after_calendar(view)

    st.html(
        '<dl class="lp-metrics">'
        f"<div><dt>Flexible tasks</dt><dd>{len(flexible)}</dd></div>"
        f"<div><dt>Fixed commitments</dt><dd>{len(planned) - len(flexible)}</dd></div>"
        f"<div><dt>Completed</dt><dd>{completed} / {len(flexible)}</dd></div>"
        "</dl>"
    )
    if flexible:
        st.progress(completed / len(flexible), text="Weekly task progress")

    with st.expander("Planning profile"):
        render_profile(profile)
    return None
