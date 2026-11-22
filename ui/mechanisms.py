"""Interactive, browser-session-only simulations for the weekly planner."""

from datetime import date
from html import escape
from time import monotonic
from uuid import uuid4

import streamlit as st

from ui.calendar_input import first_overlap

TEMPLATES = (
    {
        "title": "The 5 AM CEO Miracle", "gain": 300, "price": 199,
        "summary": "Start early, protect a focus block, and finish a priority before breakfast.",
        "blocks": (("05:00", "05:30", "Morning reflection"), ("05:30", "06:00", "Morning movement"),
                   ("06:00", "07:30", "Deep work")),
    },
    {
        "title": "The Deep Work Blueprint", "gain": 500, "price": 299,
        "summary": "Concentrate two important sessions into a low-distraction morning.",
        "blocks": (("08:00", "09:30", "Focus block I"), ("09:45", "10:45", "Focus block II"),
                   ("12:00", "12:30", "Review the morning")),
    },
    {
        "title": "The Mindful Student", "gain": 220, "price": 149,
        "summary": "Combine active recall, a study block, and an end-of-day review.",
        "blocks": (("09:00", "09:45", "Active recall"), ("10:00", "11:00", "Focused study"),
                   ("15:30", "16:00", "Review and reflection")),
    },
)

RANKINGS = {
    "Global ranking": (("Productivity Master", 998), ("WorkHarder_24_7", 995), ("Efficiency King", 989)),
    "Friends ranking": (("Maya (demo)", 892), ("Jordan (demo)", 841), ("Sam (demo)", 801)),
    "Weekly challenge": (("Productivity Master", 318), ("WorkHarder_24_7", 315), ("Efficiency King", 309)),
}
GAINS = (2, 3, 2.3, 2.7)
TIP_INTERVAL = 25


def _mechanics(key: str) -> dict:
    return st.session_state.setdefault(f"{key}_mechanisms", {
        "score": 784, "rank": 12_847, "round": 0, "tip_since": monotonic(),
        "visits": 0, "was_week": False, "undo": None, "notice": "",
    })


def observe_calendar(key: str, is_week: bool) -> None:
    """Rotate recommendations on each new visit to the weekly view."""
    state = _mechanics(key)
    if is_week and not state["was_week"]:
        state["visits"] += 1
    state["was_week"] = is_week


def reset_plan_mechanisms(key: str) -> None:
    """Keep the simulated score while discarding changes tied to the previous plan."""
    _mechanics(key).update(round=0, tip_since=monotonic(), was_week=False, undo=None)
    st.session_state.pop(f"{key}_flash", None)


def _reward(state: dict, earned: int, reopened: int = 0) -> None:
    state["score"] = max(0, state["score"] + 12 * (earned - reopened))
    state["rank"] = max(1, state["rank"] + 17 * (earned - reopened))
    if earned:
        state["notice"] = f"+{12 * earned} points. Your simulated global rank fell {17 * earned} places."
    elif reopened:
        state["notice"] = "The simulated score and rank were updated when you reopened a task."


def record_task_updates(before: list[dict], after: list[dict], key: str) -> None:
    def completed(items: list[dict]) -> set[str]:
        return {item["id"] for item in items if not item["is_fixed"] and item["completed"]}

    old, new = completed(before), completed(after)
    if new != old:
        _reward(_mechanics(key), len(new - old), len(old - new))


def _gain(state: dict) -> int | float:
    elapsed = int((monotonic() - state["tip_since"]) // TIP_INTERVAL)
    return GAINS[(state["round"] + elapsed) % len(GAINS)]


def _minutes(value: str) -> int:
    hour, minute = map(int, value.split(":"))
    return hour * 60 + minute


def _clock(value: int) -> str:
    return f"{value // 60:02d}:{value % 60:02d}"


def _propose(schedule: list[dict], round_number: int) -> tuple[list[dict], list[tuple[dict, dict]]]:
    updated = [item.copy() for item in schedule]
    changes = []
    offsets = (5, -5, 10, -10) if round_number % 2 == 0 else (-5, 5, -10, 10)
    ordered = sorted(enumerate(schedule), key=lambda pair: (pair[1]["date"], pair[1]["start"]))
    for index, entry in ordered:
        if entry["is_fixed"] or entry["completed"]:
            continue
        for step in offsets:
            start, end = _minutes(entry["start"]) + step, _minutes(entry["end"]) + step
            if not (0 <= start < end < 1440):
                continue
            proposed = dict(entry, start=_clock(start), end=_clock(end))
            if not first_overlap(updated, proposed, exclude_id=entry["id"]):
                updated[index] = proposed
                changes.append((entry, proposed))
                break
        if len(changes) == 6:
            break
    return updated, changes


@st.dialog("Review AI optimization", width="medium")
def _optimization_dialog(schedule_key: str, key: str, gain: int | float) -> None:
    state = _mechanics(key)
    updated, changes = _propose(st.session_state[schedule_key], state["round"])
    st.caption(f"Round {state['round'] + 1} · Claimed improvement +{gain}% · Simulated estimate")
    if not changes:
        st.info("There are no unfinished, movable tasks with an open time slot.")
        return
    st.write("Confirm each change to apply this round.")
    with st.form(f"{key}_confirm_round_{state['round']}"):
        accepted = [
            st.checkbox(
                f"{date.fromisoformat(old['date']):%a} · {old['title']}  |  "
                f"{old['start']}–{old['end']} → {new['start']}–{new['end']}",
                key=f"{key}_confirm_{state['round']}_{old['id']}",
            )
            for old, new in changes
        ]
        submitted = st.form_submit_button("Apply changes", type="primary")
    if submitted:
        if not all(accepted):
            st.error("Confirm each proposed change before applying this round.")
            return
        st.session_state[schedule_key] = updated
        state["round"] += 1
        state["tip_since"] = monotonic()
        state["score"] += 3
        st.session_state[f"{key}_flash"] = (
            f"Round applied. AI found another +{_gain(state)}% improvement."
        )
        st.rerun()


@st.fragment(run_every=f"{TIP_INTERVAL}s")
def _optimization_signal(key: str) -> None:
    state = _mechanics(key)
    st.html(
        '<p class="lp-mechanism-kicker">AI SUGGESTION · SIMULATED</p>'
        f'<h2 class="lp-mechanism-title">+{_gain(state)}% potential improvement</h2>'
        f'<p class="lp-mechanism-copy">{state["round"]} rounds applied. '
        'AI will look again for more room to optimize.</p>'
    )


def _suggested_template(state: dict) -> dict:
    return TEMPLATES[(max(1, state["visits"]) - 1) % len(TEMPLATES)]


@st.dialog("Template preview", width="medium")
def _template_dialog(schedule_key: str, key: str, day: date, template: dict) -> None:
    state = _mechanics(key)
    schedule = st.session_state[schedule_key]
    st.subheader(template["title"])
    st.caption(f"Simulated promotion · +{template['gain']}% claim · Demo price ¥{template['price']}")
    st.write(template["summary"])
    st.caption(f"Proposed routine for {day:%A, %d %b}")
    for start, end, title in template["blocks"]:
        st.text(f"{start}–{end}  {title}")
    removed = [
        item for item in schedule
        if item["date"] == day.isoformat() and not item["is_fixed"] and not item["completed"]
    ]
    kept = [item for item in schedule if item not in removed]
    added = []
    for start, end, title in template["blocks"]:
        item = {
            "id": f"template_{uuid4().hex}", "date": day.isoformat(),
            "title": title, "start": start, "end": end,
            "completed": False, "is_fixed": False, "category": "Demo template",
        }
        if not first_overlap(kept + added, item):
            added.append(item)
    st.caption(
        f"Replaces {len(removed)} unfinished task(s) that day. "
        f"{len(added)} template blocks fit without moving fixed or completed items."
    )
    if st.button("Apply demo template", type="primary", disabled=not added):
        st.session_state[schedule_key] = kept + added
        state["undo"] = {"removed": removed, "added": {item["id"] for item in added}}
        st.session_state[f"{key}_flash"] = f"Applied {template['title']} to {day:%A}."
        st.rerun()


def _undo_template(schedule_key: str, key: str) -> None:
    state = _mechanics(key)
    snapshot = state["undo"]
    if not snapshot:
        return
    preserved = [item for item in st.session_state[schedule_key] if item["id"] not in snapshot["added"]]
    conflict = next(
        (item for item in snapshot["removed"] if first_overlap(preserved, item)),
        None,
    )
    if conflict:
        st.error(f'Cannot restore "{conflict["title"]}" because another task now occupies its time.')
        return
    st.session_state[schedule_key] = preserved + snapshot["removed"]
    state["undo"] = None
    st.session_state[f"{key}_flash"] = "Restored your calendar before the template."
    st.rerun()


@st.dialog("Productivity leaderboard", width="medium")
def _leaderboard_dialog(key: str) -> None:
    state = _mechanics(key)
    scope = st.radio("Ranking scope", tuple(RANKINGS), horizontal=True, key=f"{key}_rank_scope")
    st.caption("Fictional players and simulated scores.")
    entries = RANKINGS[scope]
    rows = "".join(
        f'<tr><td>{index}</td><td>{escape(name)}</td><td>{score:,}</td></tr>'
        for index, (name, score) in enumerate(entries, 1)
    )
    st.html(
        '<table class="lp-rankings"><thead><tr><th>Rank</th><th>Player</th><th>Score</th></tr></thead>'
        f"<tbody>{rows}</tbody></table>"
    )
    score = max(0, state["score"] - 680) if scope == "Weekly challenge" else state["score"]
    st.write(f"**Your score: {score:,}** · Simulated global rank **#{state['rank']:,}**")
    st.caption(f"{max(0, entries[0][1] - score):,} points behind first place in this view.")
    if st.button("Simulate task completion", type="primary", key=f"{key}_simulate_completion"):
        _reward(state, 1)
        st.session_state[f"{key}_flash"] = state["notice"]
        st.rerun()
    if state["notice"]:
        st.caption(state["notice"])


def render_mechanisms(schedule_key: str, key: str, week_start: date) -> None:
    state = _mechanics(key)
    template = _suggested_template(state)
    st.html('<p id="lp-demo-features" class="lp-demo-anchor">Demo features</p>')
    if message := st.session_state.pop(f"{key}_flash", None):
        st.info(message)
    with st.container(key="lp_mechanisms"):
        for name, column in zip(("optimization", "template", "rank"), st.columns(3), strict=True):
            with column, st.container(key=f"lp_mechanism_{name}"):
                if name == "optimization":
                    _optimization_signal(key)
                    if st.button("Review optimization", key=f"{key}_review", width="stretch"):
                        _optimization_dialog(schedule_key, key, _gain(state))
                elif name == "template":
                    st.html(
                        '<p class="lp-mechanism-kicker">AI PICK · DEMO PROMOTION</p>'
                        f'<h2 class="lp-mechanism-title">{escape(template["title"])}</h2>'
                        f'<p class="lp-mechanism-copy">Claims +{template["gain"]}% productivity.</p>'
                    )
                    if st.button("View template", key=f"{key}_template", width="stretch"):
                        _template_dialog(schedule_key, key, week_start, template)
                    if state["undo"] and st.button("Undo template", key=f"{key}_undo", width="stretch"):
                        _undo_template(schedule_key, key)
                else:
                    st.html(
                        '<p class="lp-mechanism-kicker">DAILY SCORE · SIMULATED</p>'
                        f'<h2 class="lp-mechanism-title">{state["score"]:,} points</h2>'
                        f'<p class="lp-mechanism-copy">Global rank #{state["rank"]:,} · '
                        f'{max(0, 998 - state["score"]):,} points to first.</p>'
                    )
                    if st.button("View leaderboard", key=f"{key}_leaderboard", width="stretch"):
                        _leaderboard_dialog(key)
    if state["notice"]:
        st.caption(state["notice"])
    tasks = [item for item in st.session_state[schedule_key] if not item["is_fixed"]]
    if tasks and all(item["completed"] for item in tasks):
        st.caption("All tasks are complete. The simulated leaderboard can still move you down.")
