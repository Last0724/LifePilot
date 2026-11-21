"""Profile, completion metrics, and weekly and daily navigation."""

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
    profile: dict, schedule: list[dict], *, week_start: date | None = None, key: str = "dashboard"
) -> list[dict] | None:
    """Render the dashboard and return a replacement schedule when a task is saved."""
    if week_start is None:
        week_start = min((date.fromisoformat(task["date"]) for task in schedule), default=date.today())
    days = [week_start + timedelta(days=offset) for offset in range(7)]
    week_dates = {day.isoformat() for day in days}
    planned = [task for task in schedule if task["date"] in week_dates]
    flexible = [task for task in planned if not task["is_fixed"]]
    completed = sum(task["completed"] for task in flexible)

    st.title("Your planner")
    st.caption(f"{days[0]:%d %b} – {days[-1]:%d %b %Y}")
    render_profile(profile)
    st.html(
        '<dl class="lp-metrics">'
        f"<div><dt>Flexible tasks</dt><dd>{len(flexible)}</dd></div>"
        f"<div><dt>Fixed commitments</dt><dd>{len(planned) - len(flexible)}</dd></div>"
        f"<div><dt>Completed</dt><dd>{completed} / {len(flexible)}</dd></div>"
        "</dl>"
    )
    if flexible:
        st.progress(completed / len(flexible), text="Weekly task progress")

    view = st.radio(
        "Planner view", ("Week", "Day"), horizontal=True, key=f"{key}_view", label_visibility="collapsed"
    )
    if view == "Week":
        st.subheader("Week at a glance")
        render_weekly_planner(planned, week_start)
        return None

    day = st.selectbox("Day", days, format_func=lambda value: f"{value:%A, %d %b}", key=f"{key}_day")
    render_daily_planner(planned, day)
    return render_task_editor(schedule, day, key=f"{key}_editor")
