# Guru Template Marketplace — Integration Guide for B

The `ux/` package implements Feature 02. It is self-contained: it imports
LifePilot's visual conventions from `ui/` at runtime but never modifies any
file under `ui/`, `core/` or `app.py`.

## Run the standalone preview

```bash
python -m streamlit run ux/preview.py --theme.base light
```

## What to import

```python
from ux.marketplace import (
    get_state,                     # MarketplaceState stored in st.session_state
    render_marketplace_entry,      # one-button entry for the Week view (Plan A)
    render_marketplace,            # template cards + paywall + upgrade flow
    render_post_plan_upsell,       # upsell right after schedule generation
    render_advanced_features,      # premium-only capabilities section
    render_paywall,                # inline paywall for the selected template
)
```

## Single entry point (Plan A, approved)

In the Week view replace the template column of
`ui/mechanisms.render_mechanisms` with one call:

```python
from ux.marketplace import render_marketplace_entry
render_marketplace_entry()
```

The button opens a wide `st.dialog` hosting the full marketplace, so no
second template promotion appears in the planner. Optimisation and
leaderboard columns stay untouched.

## Session state

- Key: `ux_marketplace_state`, holding a `MarketplaceState` dataclass
  (`ux/templates.py`). Do not construct it yourself; call `get_state()`.
- Pure catalog and rules (`ux/templates.py`) have no Streamlit import and are
  safe to reuse for tests or any other frontend.

## The three paywall actions (keep them distinct)

| Button | Behavior |
| --- | --- |
| `Upgrade to Guru Premium` | `state.upgrade()` → Free becomes Premium, templates/features unlock. Simulated only. |
| `Close / Not now` | `state.close_paywall()` → closes the panel, subscription unchanged. |
| `Return to Free plan` | `state.return_to_free()` → explicit downgrade, premium relocks. Shown in the marketplace header, not in the paywall. |

## Upsell touchpoints

1. `render_post_plan_upsell()` — call it right after a schedule is generated/displayed.
2. `render_marketplace()` — premium cards open the paywall via "Unlock premium preview".
3. `render_advanced_features()` — each feature's "Unlock" opens the same paywall.

## Integration rules

- Reuse `ui/components.apply_theme()` before rendering, and keep `ui/` untouched.
- All upsell data is deterministic mock data in `ux/templates.py`
  (`TEMPLATES`, `ADVANCED_FEATURES`, `UPSELL_COPY`); there is no payment code.
- The demo schedule contract is the same dict shape used by `ui/preview.py`
  (`id/title/date/start/end/category/completed/is_fixed`), so B can pass its own
  schedule into `render_dashboard` exactly as before; the marketplace adds
  nothing to the schedule itself.
- The marketplace never mutates the calendar. If "apply a template to the day"
  is still wanted, keep B's existing apply/undo logic in `ui/mechanisms.py` as
  the single writer; the marketplace only manages browsing and the simulated
  subscription state.
