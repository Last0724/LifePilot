"""Collect the provisional questionnaire payload using native controls."""

from datetime import date, time, timedelta

import streamlit as st

from ui.calendar_input import calendar_entries, first_overlap, render_calendar_editor, week_of
from ui.consultation import render_consultation_input


def _lines(value: str) -> list[str]:
    return [line.strip() for line in value.splitlines() if line.strip()]


def _add_commitment(key: str) -> None:
    state = st.session_state
    title = state[f"{key}_fixed_title"].strip()
    start = state[f"{key}_fixed_start"]
    end = state[f"{key}_fixed_end"]
    if not title or end <= start:
        state[f"{key}_fixed_error"] = "Enter a name and choose an end time after the start."
        return
    commitment = {
        "title": title,
        "date": state[f"{key}_fixed_date"].isoformat(),
        "start": start.strftime("%H:%M"),
        "end": end.strftime("%H:%M"),
    }
    commitments = state[f"{key}_commitments"]
    if commitment in commitments:
        state[f"{key}_fixed_error"] = "This commitment is already in the list."
        return
    conflict = first_overlap([*commitments, *calendar_entries(key)], commitment)
    if conflict:
        state[f"{key}_fixed_error"] = f'This time overlaps with {conflict["title"]}.'
        return
    commitments.append(commitment)
    state[f"{key}_fixed_title"] = ""
    state.pop(f"{key}_fixed_error", None)


def _remove_commitment(key: str, index: int) -> None:
    st.session_state[f"{key}_commitments"].pop(index)
    st.session_state.pop(f"{key}_fixed_error", None)


def render_questionnaire(
    *, key: str = "questionnaire", default_date: date | None = None, consultation: bool = False
) -> dict | None:
    """Return the questionnaire dictionary on valid submission."""
    first_day = week_of(default_date or date.today())
    last_day = first_day + timedelta(days=6)
    with st.container(key=f"lp_questionnaire_{key}"):
        with st.container(key=f"lp_question_intro_{key}"):
            st.title("Plan your week", anchor=False)
            st.caption(
                "Add tasks to the calendar or describe your week."
                if consultation else "Choose a day and add what you plan to do."
            )

        description = render_consultation_input(key) if consultation else ""
        entries = render_calendar_editor(first_day, key=key)
        with st.container(key=f"lp_question_action_{key}"):
            submitted = st.button("Continue", type="primary", key=f"{key}_submit")
        if submitted:
            feedback = st.empty()

        with st.expander("Goals and work preferences"):
            goals = st.text_area(
                "Goals", placeholder="Finish the first draft", help="One goal per line.",
                key=f"{key}_goals",
            )
            left, right = st.columns(2)
            work_start = left.time_input("Workday starts", time(9), step=60, key=f"{key}_work_start")
            work_end = right.time_input("Workday ends", time(17), step=60, key=f"{key}_work_end")

            left, right = st.columns(2)
            work_style = left.selectbox(
                "Work style",
                ("No preference", "Long focus blocks", "Short sprints", "A mix of both"),
                key=f"{key}_style",
            )
            preferences = right.multiselect(
                "Work preferences",
                ("Morning focus", "Afternoon focus", "Regular breaks", "Batch similar tasks"),
                key=f"{key}_preferences",
            )

        commitments = st.session_state.setdefault(f"{key}_commitments", [])
        fixed_label = f"Fixed commitments ({len(commitments)})" if commitments else "Fixed commitments"
        with st.expander(fixed_label, expanded=bool(commitments)):
            for index, commitment in enumerate(commitments):
                details, action = st.columns([4, 1])
                details.text(
                    f'{commitment["title"]} · {commitment["date"]} · '
                    f'{commitment["start"]}–{commitment["end"]}'
                )
                action.button(
                    "Remove", key=f"{key}_remove_{index}",
                    on_click=_remove_commitment, args=(key, index),
                )
            st.text_input("Commitment name", placeholder="Team check-in", key=f"{key}_fixed_title")
            day, start, end = st.columns(3)
            day.date_input(
                "Date", default_date or date.today(), min_value=first_day, max_value=last_day,
                key=f"{key}_fixed_date",
            )
            start.time_input("Start", time(11), step=60, key=f"{key}_fixed_start")
            end.time_input("End", time(11, 30), step=60, key=f"{key}_fixed_end")
            st.button("Add commitment", key=f"{key}_add", on_click=_add_commitment, args=(key,))
            if message := st.session_state.get(f"{key}_fixed_error"):
                st.error(message)

    if not submitted:
        return None
    if st.session_state[f"{key}_fixed_title"].strip():
        feedback.error("Add the commitment you entered, or clear its name before continuing.")
    elif work_end <= work_start:
        feedback.error("The workday must end after it starts.")
    elif not (_lines(goals) or entries or description.strip()):
        feedback.error(
            "Add a task, enter a goal, or describe your week."
            if consultation else "Enter at least one goal or task to continue."
        )
    else:
        return {
            "goals": _lines(goals),
            "tasks": [entry["title"] for entry in entries],
            "fixed_commitments": [commitment.copy() for commitment in commitments],
            "preferred_work_hours": {
                "start": work_start.strftime("%H:%M"),
                "end": work_end.strftime("%H:%M"),
            },
            "work_style": "" if work_style == "No preference" else work_style,
            "preferences": preferences,
        }
    return None
