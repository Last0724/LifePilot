"""Editable weekly calendar for collecting questionnaire tasks."""

from datetime import date, time, timedelta
from html import escape
from uuid import uuid4

import streamlit as st


def week_of(day: date) -> date:
    return day - timedelta(days=day.weekday())


def calendar_entries(key: str) -> list[dict]:
    return st.session_state.setdefault(f"{key}_calendar", [])


def first_overlap(entries: list[dict], candidate: dict, *, exclude_id: str | None = None) -> dict | None:
    return next(
        (
            entry for entry in entries
            if entry["date"] == candidate["date"]
            and (exclude_id is None or entry.get("id") != exclude_id)
            and candidate["start"] < entry["end"] and entry["start"] < candidate["end"]
        ),
        None,
    )


def _default_times(day: date, key: str, entries: list[dict]) -> tuple[time, time]:
    def minutes(value: time) -> int:
        return value.hour * 60 + value.minute

    def clock(value: int) -> time:
        return time(*divmod(value, 60))

    start = minutes(st.session_state.get(f"{key}_work_start", time(9)))
    end = minutes(st.session_state.get(f"{key}_work_end", time(17)))
    occupied = sorted(
        (minutes(time.fromisoformat(item["start"])), minutes(time.fromisoformat(item["end"])))
        for item in entries if item["date"] == day.isoformat()
    )
    for duration in (60, 30, 15):
        cursor = start
        for left, right in occupied:
            if cursor + duration <= left:
                break
            cursor = max(cursor, right)
        if cursor + duration <= end:
            return clock(cursor), clock(cursor + duration)
    return time(9), time(10)


@st.dialog("Calendar task")
def _task_details(day: date, key: str, item: dict | None) -> None:
    st.caption(day.strftime("%A, %d %b %Y"))
    tasks = calendar_entries(key)
    fixed = st.session_state.get(f"{key}_commitments", [])
    if item is None:
        start_value, end_value = _default_times(day, key, tasks + fixed)
    else:
        start_value, end_value = time.fromisoformat(item["start"]), time.fromisoformat(item["end"])

    with st.form(f"{key}_calendar_form_{item['id'] if item else 'new'}"):
        title = st.text_input("Task name", value=item["title"] if item else "", max_chars=120)
        first, second = st.columns(2)
        start = first.time_input("Start time", start_value, step=60)
        end = second.time_input("End time", end_value, step=60)
        with st.container(horizontal=True, horizontal_alignment="right"):
            removed = item is not None and st.form_submit_button("Remove task")
            saved = st.form_submit_button("Save task", type="primary")

    if removed:
        st.session_state[f"{key}_calendar"] = [entry for entry in tasks if entry["id"] != item["id"]]
        st.rerun()
    if not saved:
        return
    if not title.strip():
        st.error("Enter a task name.")
        return
    if end <= start:
        st.error("The end time must be after the start time.")
        return
    task_id = item["id"] if item else uuid4().hex
    entry = {
        "id": task_id, "title": title.strip(), "date": day.isoformat(),
        "start": start.strftime("%H:%M"), "end": end.strftime("%H:%M"),
    }
    if conflict := first_overlap(tasks + fixed, entry, exclude_id=task_id):
        st.error(f'This time overlaps with {conflict["title"]}. Choose a different time.')
        return
    st.session_state[f"{key}_calendar"] = [existing for existing in tasks if existing["id"] != task_id] + [entry]
    st.rerun()


def render_calendar_editor(first_day: date, *, key: str) -> list[dict]:
    """Render all seven dates and return their draft entries in calendar order."""
    entries = calendar_entries(key)
    fixed = st.session_state.get(f"{key}_commitments", [])
    days = [first_day + timedelta(days=offset) for offset in range(7)]
    st.html(f'<p class="lp-calendar-range">{first_day:%d %b} – {days[-1]:%d %b %Y}</p>')
    selection = None
    with st.container(key=f"lp_calendar_grid_{key}"):
        columns = st.columns(7)
        for day, column in zip(days, columns, strict=True):
            date_key = day.isoformat()
            with column, st.container(key=f"lp_calendar_day_{key}_{date_key}"):
                st.html(
                    f'<h2 class="lp-calendar-date"><span>{day:%A}</span>'
                    f'<time datetime="{date_key}">{day:%d %b}</time></h2>'
                )
                blocks = [
                    (entry, is_fixed)
                    for collection, is_fixed in ((entries, False), (fixed, True))
                    for entry in collection if entry["date"] == date_key
                ]
                for entry, is_fixed in sorted(blocks, key=lambda pair: pair[0]["start"]):
                    if is_fixed:
                        st.html(
                            f'<div class="lp-calendar-fixed">'
                            f'<span>{entry["start"]}–{entry["end"]} · Fixed</span>'
                            f'<strong>{escape(entry["title"])}</strong></div>'
                        )
                    else:
                        title = entry["title"].replace("\\", "\\\\")
                        for char in "*_[]`!":
                            title = title.replace(char, f"\\{char}")
                        if st.button(
                            f'{entry["start"]}–{entry["end"]} · {title}',
                            key=f"{key}_edit_calendar_{entry['id']}", width="stretch",
                        ):
                            selection = (day, entry)

                if st.button("Add task", icon=":material/add:", key=f"{key}_add_calendar_{date_key}", width="stretch"):
                    selection = (day, None)
    if selection is not None:
        _task_details(selection[0], key, selection[1])
    return sorted(entries, key=lambda entry: (entry["date"], entry["start"]))
