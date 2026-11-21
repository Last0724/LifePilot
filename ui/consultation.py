"""Structured consultation controls for the standalone preview."""

import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from html import escape
from uuid import uuid4

import streamlit as st

from ui.calendar_input import first_overlap

SAMPLE_TRANSCRIPT = (
    "Goal: Finish my research proposal\n"
    "Tasks: Draft the outline; Review the reading notes\n"
    "Hours: 09:00–17:00"
)


def consultation_description(key: str) -> str:
    return st.session_state.get(f"{key}_description", "")


def _use_voice_sample(key: str) -> None:
    st.session_state[f"{key}_description"] = SAMPLE_TRANSCRIPT
    st.session_state[f"{key}_voice_text"] = SAMPLE_TRANSCRIPT


def _remember_text(key: str) -> None:
    st.session_state[f"{key}_description"] = st.session_state[f"{key}_voice_text"]


def render_consultation_input(key: str) -> str:
    """Offer a sample voice transcript and an editable text alternative."""
    widget_key = f"{key}_voice_text"
    st.session_state.setdefault(widget_key, consultation_description(key))
    with st.expander("Describe your week by voice or text", expanded=bool(consultation_description(key))):
        st.caption("Mention goals, tasks, fixed commitments, and when you can work.")
        st.button(
            "Try voice input (demo)", icon=":material/mic:", on_click=_use_voice_sample,
            args=(key,), key=f"{key}_voice_sample",
            help="Loads a sample transcript. This preview does not record audio.",
        )
        text = st.text_area(
            "Describe your week",
            placeholder="Goal: Finish the first draft\nTasks: Outline the report; Read the feedback\n"
                        "Hours: 09:00–17:00\nFixed: Wednesday 11:00–11:30 | Team check-in",
            key=widget_key, on_change=_remember_text, args=(key,), height=144,
        )
    return text


@dataclass(frozen=True)
class SchedulingField:
    label: str
    example: str
    question: str
    multiline: bool = False


FIELDS = {
    "goals": SchedulingField("Goals", "Finish my research proposal", "What goal should this week support?", True),
    "tasks": SchedulingField("Tasks", "Draft the outline", "What tasks should we put in your plan?", True),
    "hours": SchedulingField("Working hours", "09:00–17:00", "When can you work on a typical day?"),
    "fixed": SchedulingField(
        "Fixed commitments", "Wednesday 11:00–11:30 | Team check-in",
        "What appointments must stay at their current time?", True,
    ),
    "focus": SchedulingField("Focus time", "Morning, afternoon, or no preference", "When do you focus best?"),
    "style": SchedulingField(
        "Work style", "Long focus blocks, short sprints, or a mix of both", "How long do you like to work in one sitting?",
    ),
    "breaks": SchedulingField("Regular breaks", "Yes or no", "Would you like regular breaks in the plan?"),
}
ALIASES = {
    "goal": "goals", "goals": "goals", "目标": "goals",
    "task": "tasks", "tasks": "tasks", "任务": "tasks",
    "hours": "hours", "working hours": "hours", "工作时间": "hours",
    "fixed": "fixed", "fixed commitments": "fixed", "固定事项": "fixed",
    "focus": "focus", "focus time": "focus", "专注时间": "focus",
    "style": "style", "work style": "style", "工作方式": "style",
    "breaks": "breaks", "regular breaks": "breaks", "休息": "breaks",
}
DAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
DAY_OFFSETS = {label.casefold(): offset for offset, day in enumerate(DAYS) for label in (day, day[:3])}
OPTION_VALUES = {
    "focus": ("Morning", "Afternoon", "No preference"),
    "style": ("Long focus blocks", "Short sprints", "A mix of both", "No preference"),
    "breaks": ("Yes", "No"),
}
TIME = r"([01]?\d|2[0-3]):([0-5]\d)"
RANGE = re.compile(rf"{TIME}\s*(?:–|—|-|to|至)\s*{TIME}", re.IGNORECASE)


@dataclass
class ConsultationDraft:
    week_start: date
    values: dict[str, str]
    confirmed: set[str]
    calendar: list[dict]
    source_text: str
    unparsed: list[str] = field(default_factory=list)
    skipped: set[str] = field(default_factory=set)
    batch: bool = False
    revision: int = 0

    def status(self, key: str) -> str:
        if key in self.confirmed:
            return "Confirmed"
        if self.values.get(key):
            return "Needs review"
        if key in self.skipped:
            return "Not provided"
        return "Missing"


def task_lines(value: str) -> list[str]:
    return list(dict.fromkeys(line.strip() for line in re.split(r"[\n;；]", value) if line.strip()))


def _source_fields(text: str) -> tuple[dict[str, str], list[str]]:
    extracted = {}
    unparsed = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        heading, sep, content = line.replace("：", ":").partition(":")
        key = ALIASES.get(heading.strip().casefold())
        if sep and key and content.strip():
            content = content.strip()
            extracted[key] = "\n".join(filter(None, (extracted.get(key), content)))
        elif "hours" not in extracted and (match := RANGE.search(line)) and re.search(r"work|available|工作|有空", line, re.I):
            extracted["hours"] = match[0]
        else:
            unparsed.append(line)
    return extracted, unparsed


def start_consultation(payload: dict, calendar: list[dict], text: str, week_start: date) -> ConsultationDraft:
    """Make an editable mock draft while keeping the questionnaire contract intact."""
    preferences = payload["preferences"]
    hours = payload["preferred_work_hours"]
    values = {
        "goals": "\n".join(payload["goals"]),
        "tasks": "\n".join(payload["tasks"]),
        "hours": f'{hours["start"]}–{hours["end"]}' if hours != {"start": "09:00", "end": "17:00"} else "",
        "fixed": "\n".join(
            f'{item["date"]} {item["start"]}–{item["end"]} | {item["title"]}'
            for item in payload["fixed_commitments"]
        ),
        "focus": "Morning" if "Morning focus" in preferences else "Afternoon" if "Afternoon focus" in preferences else "",
        "style": payload["work_style"],
        "breaks": "Yes" if "Regular breaks" in preferences else "",
    }
    confirmed = {key for key, value in values.items() if value}
    extracted, unparsed = _source_fields(text)
    for key, value in extracted.items():
        if key in {"goals", "tasks"}:
            value = "\n".join(task_lines(f"{values[key]}\n{value}"))
        elif key == "fixed" and values[key]:
            value = f"{values[key]}\n{value}"
        if value != values[key]:
            values[key] = value
            confirmed.discard(key)
    return ConsultationDraft(
        week_start, values, confirmed, [entry.copy() for entry in calendar], text, unparsed,
        batch="Batch similar tasks" in preferences,
    )


def parse_hours(value: str) -> tuple[str, str]:
    match = RANGE.fullmatch(value.strip())
    if not match:
        raise ValueError("Use a time range such as 09:00–17:00.")
    sh, sm, eh, em = map(int, match.groups())
    start, end = f"{sh:02d}:{sm:02d}", f"{eh:02d}:{em:02d}"
    if start >= end:
        raise ValueError("The end time must be after the start time.")
    return start, end


def parse_fixed(value: str, week_start: date) -> list[dict]:
    if not value.strip() or value.strip().casefold() in {"none", "no", "not applicable", "无"}:
        return []
    entries = []
    for line in value.splitlines():
        if not line.strip():
            continue
        times, sep, title = line.partition("|")
        if not sep or not title.strip() or " " not in times.strip():
            raise ValueError("Use one entry per line, for example: Wednesday 11:00–11:30 | Team check-in.")
        day, interval = times.strip().split(maxsplit=1)
        if day.casefold() in DAY_OFFSETS:
            fixed_date = week_start + timedelta(days=DAY_OFFSETS[day.casefold()])
        else:
            try:
                fixed_date = date.fromisoformat(day)
            except ValueError as error:
                raise ValueError("Use a weekday such as Wednesday or a date such as 2026-11-25.") from error
        if not 0 <= (fixed_date - week_start).days <= 6:
            raise ValueError("Fixed commitments must be within the displayed week.")
        start, end = parse_hours(interval)
        entry = {"date": fixed_date.isoformat(), "start": start, "end": end, "title": title.strip()}
        if entry in entries:
            continue
        if conflict := first_overlap(entries, entry):
            raise ValueError(f'This commitment overlaps with {conflict["title"]}.')
        entries.append(entry)
    return entries


def normalize_field(key: str, source: str, week_start: date) -> str:
    value = source.strip()
    if not value:
        return ""
    if key in {"goals", "tasks"}:
        lines = task_lines(value)
        if not lines:
            raise ValueError("Enter at least one item.")
        if any(len(line) > 120 for line in lines):
            raise ValueError("Keep each item under 120 characters.")
        return "\n".join(lines)
    if key == "hours":
        start, end = parse_hours(value)
        return f"{start}–{end}"
    if key == "fixed":
        fixed = parse_fixed(value, week_start)
        return "\n".join(
            f'{item["date"]} {item["start"]}–{item["end"]} | {item["title"]}' for item in fixed
        ) or "None"
    options = OPTION_VALUES[key]
    match = next((option for option in options if option.casefold() == value.casefold()), None)
    if match is None:
        raise ValueError("Enter one of: " + ", ".join(options) + ".")
    return match


def _field_input(key: str, value: str, widget_key: str) -> str:
    spec = FIELDS[key]
    if spec.multiline:
        return st.text_area(spec.label, value=value, placeholder=spec.example, height=91, key=widget_key)
    return st.text_input(spec.label, value=value, placeholder=spec.example, key=widget_key)


def _status_note(draft: ConsultationDraft, key: str) -> None:
    status = draft.status(key)
    tone = "confirmed" if status == "Confirmed" else "secondary"
    st.html(f'<span class="lp-field-status {tone}">{escape(status)}</span>')


def _edit_details(draft: ConsultationDraft, key: str, button: str) -> bool:
    values = {}
    with st.form(f"{key}_form_{draft.revision}"):
        fields = list(draft.values.items())
        for index in range(0, len(fields), 2):
            row = fields[index:index + 2]
            for (name, value), column in zip(row, st.columns(2)):
                with column:
                    _status_note(draft, name)
                    values[name] = _field_input(name, value, f"{key}_{name}_{draft.revision}")
        submitted = st.form_submit_button(button, type="primary")
    if not submitted:
        return False
    checked = {}
    errors = []
    for name, value in values.items():
        try:
            checked[name] = normalize_field(name, value, draft.week_start)
        except ValueError as error:
            errors.append(f"{FIELDS[name].label}: {error}")
    if errors:
        st.error("\n\n".join(errors))
        return False
    draft.values = checked
    draft.confirmed = {name for name, value in checked.items() if value}
    draft.skipped -= draft.confirmed
    draft.revision += 1
    return True


def render_extraction_review(draft: ConsultationDraft) -> bool:
    st.title("Review extracted details", anchor=False)
    st.caption("Mock AI extraction · Correct the details below. You can leave missing fields blank for now.")
    if draft.source_text:
        with st.expander("Original input"):
            st.text(draft.source_text)
            if draft.unparsed:
                st.caption("The mock could not extract these lines. Add them manually if needed.")
                st.text("\n".join(draft.unparsed))
    return _edit_details(draft, "preview_extraction", "Confirm details and continue")


def mandatory_missing(draft: ConsultationDraft) -> list[str]:
    missing = []
    if not (draft.values["goals"] or draft.values["tasks"]):
        missing.append("tasks")
    if not draft.values["hours"]:
        missing.append("hours")
    return missing


def _remaining_fields(draft: ConsultationDraft) -> list[str]:
    return mandatory_missing(draft) + [
        key for key in ("fixed", "focus", "style", "breaks") if not draft.values[key]
    ]


def _collected_list(
    draft: ConsultationDraft, *, only_confirmed: bool = False, show_required: bool = False
) -> None:
    rows = []
    required = set(mandatory_missing(draft)) if show_required else set()
    for name, value in draft.values.items():
        if only_confirmed and name not in draft.confirmed:
            continue
        status = "Required · missing" if name in required else draft.status(name)
        content = escape(value or "—")
        label = escape(FIELDS[name].label)
        badge = escape(status)
        rows.append(
            f'<div class="lp-consult-detail"><dt>{label} <small>{badge}</small></dt><dd>{content}</dd></div>'
        )
    if rows:
        st.html('<dl class="lp-consult-details">' + "".join(rows) + "</dl>")
    else:
        st.caption("No details have been confirmed yet.")


def render_guided_follow_up(draft: ConsultationDraft) -> str | None:
    """Ask one question for each relevant unanswered field, on demand."""
    remaining = _remaining_fields(draft)
    active = [key for key in remaining if key not in draft.skipped]
    if not active:
        return "confirmation"
    field_key = active[0]
    spec = FIELDS[field_key]
    st.title("A few details for your plan", anchor=False)
    st.caption("Questions are based on the fields still missing from this week’s plan.")

    question, overview = st.columns([1.35, 1], gap="large")
    with question:
        st.caption(f"{spec.label} · {'Required' if field_key in mandatory_missing(draft) else 'Optional'}")
        st.subheader(spec.question, anchor=False)
        with st.form(f"preview_follow_up_{field_key}_{draft.revision}"):
            if spec.multiline:
                raw = st.text_area("Your answer", placeholder=spec.example, height=100)
            else:
                raw = st.text_input("Your answer", placeholder=spec.example)
            with st.container(horizontal=True):
                saved = st.form_submit_button("Save answer", type="primary")
                skipped = st.form_submit_button("I don't know / Not applicable")
        if saved:
            if not raw.strip():
                st.error("Enter an answer or choose the skip option.")
                return None
            try:
                draft.values[field_key] = normalize_field(field_key, raw, draft.week_start)
            except ValueError as error:
                st.error(str(error))
                return None
            draft.confirmed.add(field_key)
            draft.skipped.discard(field_key)
            draft.revision += 1
            st.rerun()
        if skipped:
            draft.skipped.add(field_key)
            draft.revision += 1
            st.rerun()
        if st.button("Review details now", type="tertiary"):
            return "confirmation"
        if st.button("Back to extracted details", type="tertiary"):
            return "extraction"

    with overview:
        st.subheader("Collected details", anchor=False)
        _collected_list(draft, only_confirmed=True)
        st.subheader("Still missing", anchor=False)
        mandatory = set(mandatory_missing(draft))
        pending = [key for key in remaining if key not in draft.skipped or key in mandatory]
        for key in pending:
            title = FIELDS[key].label
            status = " · needed at confirmation" if key in draft.skipped else ""
            st.text(title + status)
        if not pending:
            st.caption("No questions remaining.")
    return None


def _as_questionnaire_payload(draft: ConsultationDraft) -> dict:
    """Use the existing questionnaire dictionary; no backend integration is invoked."""
    values = draft.values
    start, end = parse_hours(values["hours"])
    preferences = []
    if values["focus"] in {"Morning", "Afternoon"}:
        preferences.append(f'{values["focus"]} focus')
    if values["breaks"] == "Yes":
        preferences.append("Regular breaks")
    if draft.batch:
        preferences.append("Batch similar tasks")
    return {
        "goals": task_lines(values["goals"]),
        "tasks": task_lines(values["tasks"]),
        "fixed_commitments": parse_fixed(values["fixed"], draft.week_start),
        "preferred_work_hours": {"start": start, "end": end},
        "work_style": "" if values["style"] == "No preference" else values["style"],
        "preferences": preferences,
    }


def _retained_calendar(draft: ConsultationDraft) -> list[dict]:
    titles = set(task_lines(draft.values["tasks"]))
    return [entry for entry in draft.calendar if entry["title"] in titles]


def _calendar_conflicts(draft: ConsultationDraft) -> list[str]:
    fixed = parse_fixed(draft.values["fixed"], draft.week_start)
    return [
        f'"{task["title"]}" overlaps with fixed commitment "{conflict["title"]}". '
        "Edit the commitment or remove the conflicting task from the list before confirming."
        for task in _retained_calendar(draft) if (conflict := first_overlap(fixed, task))
    ]


def _complete_required(draft: ConsultationDraft, missing: list[str]) -> None:
    with st.form(f"preview_required_{draft.revision}"):
        raw = {
            name: _field_input(name, "", f"preview_required_{name}_{draft.revision}")
            for name in missing
        }
        saved = st.form_submit_button("Save required details")
    if not saved:
        return
    checked = {}
    try:
        for name, value in raw.items():
            if value.strip():
                checked[name] = normalize_field(name, value, draft.week_start)
    except ValueError as error:
        st.error(f"{FIELDS[name].label}: {error}")
        return
    if not checked:
        st.error("Fill in at least one required field.")
        return
    draft.values.update(checked)
    draft.confirmed.update(checked)
    draft.skipped.difference_update(checked)
    draft.revision += 1
    st.rerun()


def render_final_confirmation(draft: ConsultationDraft) -> dict | None:
    st.title("Confirm your scheduling details", anchor=False)
    st.caption("Review the details below. The preview builds a local weekly plan only after you confirm.")
    missing = mandatory_missing(draft)
    conflicts = _calendar_conflicts(draft)
    blocked = bool(missing or conflicts)

    summary, approval = st.columns([1.3, 1], gap="large")
    with summary:
        st.subheader("Scheduling information", anchor=False)
        _collected_list(draft, show_required=True)
        retained = _retained_calendar(draft)
        if retained:
            with st.expander("Tasks already placed on the calendar"):
                for task in retained:
                    st.text(f'{task["date"]} · {task["start"]}–{task["end"]} · {task["title"]}')

    with approval:
        st.subheader("Before building the plan", anchor=False)
        if missing:
            labels = ", ".join("Goal or task" if key == "tasks" else FIELDS[key].label for key in missing)
            st.warning(f"Required information missing: {labels}.")
            _complete_required(draft, missing)
        for conflict in conflicts:
            st.error(conflict)
        if not blocked:
            st.caption("All required information is ready. Optional answers may be left blank.")
        accepted = st.checkbox(
            "I confirm these scheduling details",
            disabled=blocked, key=f"preview_consent_{draft.revision}",
        )
        build = st.button("Build weekly plan", type="primary", disabled=blocked or not accepted)
    with st.expander("Edit any scheduling detail"):
        if _edit_details(draft, "preview_manual", "Save changes"):
            st.rerun()
    if build and accepted and not blocked:
        return _as_questionnaire_payload(draft)
    return None


def build_mock_schedule(draft: ConsultationDraft, payload: dict) -> tuple[list[dict], list[str]]:
    """Carry explicit calendar blocks forward and find mock slots for text-only tasks."""
    entries = [
        {**task, "category": "Task", "completed": False, "is_fixed": False}
        for task in _retained_calendar(draft)
    ] + [
        {**item, "id": f"fixed_{index}", "category": "Commitment", "completed": False, "is_fixed": True}
        for index, item in enumerate(payload["fixed_commitments"])
    ]
    placed = {item["title"] for item in entries if not item["is_fixed"]}
    tasks = payload["tasks"] or [f"Work on: {goal}" for goal in payload["goals"]]
    hours = payload["preferred_work_hours"]

    def minute(value: str) -> int:
        hour, minute_of_hour = map(int, value.split(":"))
        return hour * 60 + minute_of_hour

    def clock(value: int) -> str:
        hour, minute_of_hour = divmod(value, 60)
        return f"{hour:02d}:{minute_of_hour:02d}"

    start, end = minute(hours["start"]), minute(hours["end"])
    duration = {"Long focus blocks": 60, "Short sprints": 30}.get(payload["work_style"], 45)
    duration = min(duration, end - start)
    offsets = range(start, end - duration + 1, 15)
    focus = draft.values["focus"]
    preferred_offsets = sorted(
        offsets,
        key=lambda value: (value >= 720 if focus == "Morning" else value < 720 if focus == "Afternoon" else False),
    )
    scheduled_dates = [(draft.week_start + timedelta(days=i)).isoformat() for i in range(7)]
    buffer = 10 if draft.values["breaks"] == "Yes" else 0
    unscheduled = []
    for title in tasks:
        if title in placed:
            continue
        for day in scheduled_dates:
            for at in preferred_offsets:
                end_at = at + duration
                if any(
                    other["date"] == day
                    and at < minute(other["end"]) + (0 if other["is_fixed"] else buffer)
                    and end_at > minute(other["start"]) - (0 if other["is_fixed"] else buffer)
                    for other in entries
                ):
                    continue
                entries.append({
                    "id": uuid4().hex, "title": title, "date": day,
                    "start": clock(at), "end": clock(end_at), "category": "Task",
                    "completed": False, "is_fixed": False,
                })
                break
            else:
                continue
            break
        else:
            unscheduled.append(title)
    return entries, unscheduled
