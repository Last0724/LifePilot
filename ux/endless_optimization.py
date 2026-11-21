"""Streamlit UI for the Endless Optimization reverse-UX feature.

Run standalone for a demo preview::

    streamlit run ux/endless_optimization.py

Or integrate into ``app.py`` by calling ``render(schedule)`` once the real
scheduler produces a schedule. The component owns its own ``st.session_state``
so it can be dropped in without coordinating state with the rest of the app.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Streamlit adds the *script's* directory (ux/) to sys.path, not the repo
# root, so `from ux.optimization import ...` would fail when this file is run
# standalone (`streamlit run ux/endless_optimization.py`). Add the repo root
# explicitly so the sibling package resolves in both standalone and integrated
# (imported by app.py) modes.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st

from ux.optimization import (
    CATEGORY_LABELS,
    OptimizationEngine,
    build_mock_schedule,
    build_mock_suggestions,
)

_SESSION_KEY = "lifeplot_opt_engine"
_ACK_KEY = "lifeplot_opt_ack"
_PREVIEW_KEY = "lifeplot_show_preview"


def render(schedule: list | None = None) -> None:
    """Render the optimization interaction.

    ``schedule`` may be a list of :class:`~ux.optimization.ScheduleEntry` (or
    any objects with ``title``/``start``/``end``). When omitted, a mock
    schedule is used so the component is independently runnable.
    """
    schedule = list(schedule) if schedule else build_mock_schedule()
    engine = _get_engine()

    _show_ack()

    st.subheader("Your schedule")
    _render_schedule(schedule, engine)

    st.divider()

    suggestion = engine.current
    if suggestion is None:
        st.info("No optimization suggestions right now.")
        return

    _render_suggestion(engine, suggestion)


# -- state ----------------------------------------------------------------


def _get_engine() -> OptimizationEngine:
    if _SESSION_KEY not in st.session_state:
        st.session_state[_SESSION_KEY] = OptimizationEngine(build_mock_suggestions())
    return st.session_state[_SESSION_KEY]


def _show_ack() -> None:
    """Surface the acknowledgement from the action the user just took."""
    message = st.session_state.pop(_ACK_KEY, None)
    if message:
        st.success(message)


# -- rendering ------------------------------------------------------------


def _render_schedule(schedule: list, engine: OptimizationEngine) -> None:
    applied = engine.applied_changes
    rows = []
    for entry in schedule:
        title = getattr(entry, "title", "?")
        start = getattr(entry, "start", "")
        end = getattr(entry, "end", "")
        modified = any(title in change for change in applied)
        rows.append(
            {
                "Task": title,
                "Start": start,
                "End": end,
                "Status": "modified" if modified else "as generated",
            }
        )
    st.table(rows)

    if applied:
        st.caption("Applied simulated changes:")
        for change in applied:
            st.markdown(f"- {change}")
    else:
        st.caption("No changes applied yet — your schedule is intact.")


def _render_suggestion(engine: OptimizationEngine, suggestion) -> None:
    badge = "SIMULATED (demo data)" if suggestion.simulated else "AI-generated"
    category = CATEGORY_LABELS.get(suggestion.category, suggestion.category)
    st.caption(
        f"Optimizer #{engine.step} · Source: {badge} · {category}"
    )

    st.markdown(f"### {suggestion.headline}")
    st.write(suggestion.detail)

    if st.session_state.get(_PREVIEW_KEY, False):
        st.info(
            f"**Suggested change:** {suggestion.change}\n\n"
            "This is a preview — your schedule stays unchanged until you "
            "confirm with \"Optimize now\"."
        )

    c1, c2, c3, c4 = st.columns(4)
    if c1.button("Optimize now", use_container_width=True, type="primary"):
        applied = engine.apply()
        st.session_state[_ACK_KEY] = f"Optimized: {applied.change}"
        st.rerun()
    if c2.button("Keep current schedule", use_container_width=True):
        engine.keep()
        st.session_state[_ACK_KEY] = "Kept your current schedule (for now)."
        st.rerun()
    if c3.button("Remind me later", use_container_width=True):
        engine.remind_later()
        st.session_state[_ACK_KEY] = "We'll remind you later. Again."
        st.rerun()
    if c4.button("Preview suggested changes", use_container_width=True):
        st.session_state[_PREVIEW_KEY] = not st.session_state.get(_PREVIEW_KEY, False)
        st.rerun()

    st.caption(
        f"Suggestions shown: {engine.step} · "
        f"Applied: {len(engine.applied_changes)} · "
        f"Reminded: {engine.remind_count}"
    )


if __name__ == "__main__":
    render()
