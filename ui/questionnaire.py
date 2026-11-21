"""Collect the provisional questionnaire payload using native controls."""

from datetime import date, time

import streamlit as st


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
    if commitment in state[f"{key}_commitments"]:
        state[f"{key}_fixed_error"] = "This commitment is already in the list."
        return
    state[f"{key}_commitments"].append(commitment)
    state[f"{key}_fixed_title"] = ""
    state.pop(f"{key}_fixed_error", None)


def _remove_commitment(key: str, index: int) -> None:
    st.session_state[f"{key}_commitments"].pop(index)
    st.session_state.pop(f"{key}_fixed_error", None)


def render_questionnaire(
    *, key: str = "questionnaire", default_date: date | None = None
) -> dict | None:
    """Return the questionnaire dictionary on valid submission."""
    st.title("What should your week make room for?")
    st.caption("Start with a goal or a task. Add the commitments you need to keep.")

    left, right = st.columns(2)
    goals = left.text_area(
        "Goals", placeholder="Finish the first draft", help="One goal per line.",
        key=f"{key}_goals",
    )
    tasks = right.text_area(
        "Important tasks", placeholder="Outline chapter one", help="One task per line.",
        key=f"{key}_tasks",
    )
    st.subheader("Working hours")
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
    with st.expander(f"Fixed commitments ({len(commitments)})", expanded=bool(commitments)):
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
        day.date_input("Date", default_date or date.today(), key=f"{key}_fixed_date")
        start.time_input("Start", time(11), step=60, key=f"{key}_fixed_start")
        end.time_input("End", time(11, 30), step=60, key=f"{key}_fixed_end")
        st.button("Add commitment", key=f"{key}_add", on_click=_add_commitment, args=(key,))
        if message := st.session_state.get(f"{key}_fixed_error"):
            st.error(message)

    if not st.button("Continue to analysis", type="primary", key=f"{key}_submit"):
        return None
    if st.session_state[f"{key}_fixed_title"].strip():
        st.error("Add the commitment you entered, or clear its name before continuing.")
    elif work_end <= work_start:
        st.error("The workday must end after it starts.")
    elif not (_lines(goals) or _lines(tasks)):
        st.error("Enter at least one goal or task to continue.")
    else:
        return {
            "goals": _lines(goals),
            "tasks": _lines(tasks),
            "fixed_commitments": [commitment.copy() for commitment in commitments],
            "preferred_work_hours": {
                "start": work_start.strftime("%H:%M"),
                "end": work_end.strftime("%H:%M"),
            },
            "work_style": "" if work_style == "No preference" else work_style,
            "preferences": preferences,
        }
    return None


def render_follow_up(
    questions: list[dict[str, str]], *, key: str = "follow_up"
) -> dict[str, str] | None:
    """Collect at most two answers keyed by the consultant's question IDs."""
    if not questions:
        return {}
    st.title("A little more about your week")
    st.caption("You can skip any question.")
    with st.form(key):
        answers = {
            item["id"]: st.text_input(item["question"], key=f'{key}_{item["id"]}').strip()
            for item in questions[:2]
        }
        if st.form_submit_button("Continue", type="primary"):
            return {question_id: answer for question_id, answer in answers.items() if answer}
    return None
