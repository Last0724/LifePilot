"""Schedule views and edits for the provisional task dictionary contract."""

from datetime import date, time, timedelta
from html import escape

import streamlit as st


def _tasks_on_day(schedule: list[dict], day: date) -> list[dict]:
    return sorted(
        (task for task in schedule if task["date"] == day.isoformat()),
        key=lambda task: (task["start"], task["end"], task["title"]),
    )


def _event_html(task: dict, *, detailed: bool = False) -> str:
    if task["is_fixed"]:
        style, status = "is-fixed", "Fixed commitment"
    elif task["completed"]:
        style, status = "is-complete", "Completed"
    else:
        style, status = "", "To do"
    title = escape(task["title"])
    clock = f'{escape(task["start"])}–{escape(task["end"])}'
    if detailed:
        category = escape(task["category"])
        return (
            f'<article class="lp-event {style}"><small>{clock}</small>'
            f"<div><strong>{title}</strong><small>{category} · {status}</small></div></article>"
        )
    return (
        f'<article class="lp-event {style}"><small>{clock}</small>'
        f"<strong>{title}</strong><small>{status}</small></article>"
    )


def render_weekly_planner(schedule: list[dict], week_start: date) -> None:
    """Show seven consecutive days, including days without events."""
    days = []
    for offset in range(7):
        day = week_start + timedelta(days=offset)
        events = "".join(_event_html(task) for task in _tasks_on_day(schedule, day))
        days.append(
            f'<section class="lp-day"><h3><span>{day:%A}</span>{day.day} {day:%b}</h3>'
            + (events or '<p class="lp-empty">No tasks planned</p>')
            + "</section>"
        )
    st.html(
        '<div class="lp-legend"><span>Flexible task</span><span>Fixed commitment</span>'
        '<span>Completed task</span></div><div class="lp-week">' + "".join(days) + "</div>"
    )


def render_daily_planner(schedule: list[dict], day: date) -> None:
    """Show the selected day's timeline in order."""
    events = "".join(_event_html(task, detailed=True) for task in _tasks_on_day(schedule, day))
    if events:
        st.html(f'<div class="lp-timeline" aria-label="Daily schedule">{events}</div>')
    else:
        st.info("No tasks are planned for this day.")


def render_task_editor(schedule: list[dict], day: date, *, key: str = "editor") -> list[dict] | None:
    """Return an updated schedule on save without changing the input list."""
    day_tasks = _tasks_on_day(schedule, day)
    editable = {task["id"]: task for task in day_tasks if not task["is_fixed"]}
    if not editable:
        return None

    st.subheader("Manage tasks")
    selected_id = st.selectbox(
        "Task to edit",
        options=list(editable),
        format_func=lambda task_id: f'{editable[task_id]["start"]} · {editable[task_id]["title"]}',
        key=f"{key}_task_{day.isoformat()}",
    )
    task = editable[selected_id]
    with st.form(f"{key}_form_{selected_id}"):
        title = st.text_input("Task name", task["title"]).strip()
        first, second = st.columns(2)
        start = first.time_input("Start time", time.fromisoformat(task["start"]), step=60)
        end = second.time_input("End time", time.fromisoformat(task["end"]), step=60)
        completed = st.checkbox("Mark as completed", value=task["completed"])
        save = st.form_submit_button("Save task", type="primary")
    if not save:
        return None
    if not title or start >= end:
        st.error("Enter a task name and choose an end time after the start.")
        return None

    start_text, end_text = start.strftime("%H:%M"), end.strftime("%H:%M")
    if (start_text, end_text) != (task["start"], task["end"]):
        conflict = next(
            (
                other for other in day_tasks
                if other["id"] != selected_id
                and start_text < other["end"] and other["start"] < end_text
            ),
            None,
        )
        if conflict:
            st.error(f'This time overlaps with {conflict["title"]}. Choose a different time.')
            return None

    updated = dict(task, title=title, start=start_text, end=end_text, completed=completed)
    return [updated if current["id"] == selected_id else current for current in schedule]
