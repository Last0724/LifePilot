# Feature 01 — Endless Optimization · Integration Guide

For the frontend owner (B). This module is self-contained and does **not**
require any change to `core/` models or the scheduler. It reads your existing
schedule dictionaries as-is.

## What it does

An "endless optimization" loop: after you show the user their plan, this
component keeps surfacing a new optimization nudge. `Optimize now`,
`Keep current schedule`, and `Remind me later` all advance to the *next*
suggestion (wrapping around), so the schedule is never "good enough". It never
mutates your schedule — `Optimize now` only records the suggested change as
text, so your task list stays intact.

## Schedule contract it reads

Each item must be a dict with these keys (your existing contract — no change
needed):

```python
{
    "id": "...", "title": "...", "date": "...", "start": "09:00",
    "end": "10:30", "category": "...", "completed": False, "is_fixed": False,
}
```

Only `title`, `start`, and `end` are read; the rest are ignored.

## Hook location (one line)

File: `ui/dashboard.py` → function `render_dashboard(...)`.

Import at the top of `ui/dashboard.py`:

```python
from ux.endless_optimization import render as render_endless_optimization
```

Call it once, after the planner view is rendered and before `render_dashboard`
returns, passing the schedule list:

```python
render_endless_optimization(planned)   # or the full `schedule`
```

`planned` (the week-filtered list) is recommended so the nudge refers only to
the week on screen. Pass the full `schedule` if you prefer.

Because `render_dashboard` returns early in the Week branch, the cleanest
placement is to render the reverse-UX module after the `if view == "Week" ...`
block in both paths, e.g.:

```python
    if view == "Week":
        st.subheader("Week at a glance")
        render_weekly_planner(planned, week_start)
        result = None
    else:
        day = st.selectbox("Day", days, format_func=..., key=f"{key}_day")
        render_daily_planner(planned, day)
        result = render_task_editor(schedule, day, key=f"{key}_editor")

    render_endless_optimization(planned)
    return result
```

## Arguments

| Argument | Type | Required | Notes |
| --- | --- | --- | --- |
| `schedule` | `list[dict]` | No | B's task dicts. `None`/omitted → a dict-shaped mock (standalone demo). |

- **No `key` parameter** — the module owns its own `st.session_state` keys
  (prefixed `lifeplot_opt_*`), so it will not collide with your widget keys.
- **Returns `None`** — it never returns a replacement schedule; it is a
  display/nudge loop only.

## Standalone preview (test without touching `ui/`)

```bash
streamlit run ux/endless_optimization.py
```

Runs independently with a dict-shaped mock schedule (same contract as above),
so you can verify the interaction before wiring it into the Dashboard.
