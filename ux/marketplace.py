"""Streamlit UI for the simulated Guru Template marketplace.

Visual conventions intentionally reuse B's LifePilot palette and card style.
All upgrade behaviour is local and deterministic; no real payment is made.
"""

import streamlit as st

from ux.templates import (
    ADVANCED_FEATURES,
    PREMIUM_PLAN_NAME,
    PREMIUM_PRICE,
    MarketplaceState,
    UpsellContext,
    can_use,
    get_template,
    paywall_benefits,
    preview_lines,
    template_status,
)

STATE_KEY = "ux_marketplace_state"


def get_state() -> MarketplaceState:
    """Return the session-scoped marketplace state."""
    state = st.session_state.get(STATE_KEY)
    if not isinstance(state, MarketplaceState):
        state = MarketplaceState()
        st.session_state[STATE_KEY] = state
    return state


def _inject_styles() -> None:
    st.html(
        """
        <style>
        .ux-eyebrow { color: #5b4bc7; font-size: .78rem; font-weight: 750;
            letter-spacing: .08em; text-transform: uppercase; margin-bottom: .25rem; }
        .ux-badge { display: inline-block; border-radius: 999px; padding: .15rem .55rem;
            font-size: .72rem; font-weight: 700; letter-spacing: .02em; }
        .ux-badge.is-free { background: #dff2ed; color: #21574d; }
        .ux-badge.is-premium { background: #eeeaff; color: #4b3a9e; }
        .ux-badge.is-unlocked { background: #e7f6ef; color: #1d6248; }
        .ux-price { color: #3d3e59; font-size: .86rem; }
        .ux-locked { color: #55566e; font-size: .86rem; }
        .ux-locked strong { color: #20213c; }
        .ux-panel { border: 1px solid #e8e3fa; border-radius: 1rem; padding: 1.1rem 1.2rem;
            background: #fbfaff; }
        .ux-panel h3 { color: #20213c; padding: 0; margin: 0 0 .4rem; }
        .ux-panel p { color: #484962; margin: 0 0 .7rem; line-height: 1.55; }
        .ux-benefit { color: #35405a; font-size: .9rem; margin: .3rem 0; }
        .ux-benefit::before { content: "✓"; color: #3f8575; font-weight: 800; margin-right: .45rem; }
        .ux-advanced { border-left: 3px solid #5b4bc7; padding-left: .85rem; }
        </style>
        """
    )


def _plan_chip(state: MarketplaceState) -> None:
    if state.is_premium:
        st.html(f'<span class="ux-badge is-unlocked">{PREMIUM_PLAN_NAME}</span>')
    else:
        st.html('<span class="ux-badge is-free">Free plan</span>')


def render_paywall(state: MarketplaceState | None = None) -> MarketplaceState:
    """Render the simulated paywall inline; no payment network is involved."""
    state = state or get_state()
    template_id = state.paywall_template_id
    if template_id is None:
        return state
    try:
        template = get_template(template_id)
    except KeyError:
        state.close_paywall()
        return state

    st.html(
        '<div class="ux-panel"><div class="ux-eyebrow">Guru Premium</div>'
        f"<h3>Unlock {template.name}</h3>"
        "<p>This is a simulated upgrade for the LifePilot demo. "
        "No payment details are collected and no charge is made.</p></div>"
    )
    st.markdown("**What you get**")
    for benefit in paywall_benefits(template):
        st.html(f'<div class="ux-benefit">{benefit}</div>')

    st.markdown("**Locked preview**")
    for line in template.preview:
        st.html(f'<div class="ux-locked">🔒 {line}</div>')
    st.caption(f"{PREMIUM_PRICE} · Cancel or return to the Free plan at any time.")

    upgrade_col, back_col = st.columns(2)
    with upgrade_col:
        if st.button(
            "Upgrade to Guru Premium",
            type="primary",
            key=f"ux_upgrade_{template_id}",
            use_container_width=True,
        ):
            state.upgrade()
            st.toast("Guru Premium preview activated. No payment was taken.")
            st.rerun()
    with back_col:
        if st.button(
            "Close / Not now",
            key=f"ux_paywall_back_{template_id}",
            use_container_width=True,
        ):
            state.close_paywall()
            st.rerun()
    return state


def render_marketplace(state: MarketplaceState | None = None) -> MarketplaceState:
    """Render the four template cards and the upgrade flow."""
    _inject_styles()
    state = state or get_state()

    header, status = st.columns([3, 1])
    with header:
        st.subheader("Guru Template Marketplace")
        st.caption("Ready-made weekly systems. Free previews, simulated premium unlock.")
    with status:
        _plan_chip(state)
        if state.is_premium and st.button("Return to Free plan", key="ux_market_return"):
            state.return_to_free()
            st.rerun()

    if state.applied_template_id:
        applied = get_template(state.applied_template_id)
        st.success(f"{applied.name} is now shown as your active demo template.")

    columns = st.columns(2, gap="medium")
    for index, template in enumerate(get_templates()):
        with columns[index % 2]:
            with st.container(border=True):
                st.markdown(f"### {template.name}")
                badge_class = (
                    "is-unlocked" if can_use(template, state.is_premium)
                    else "is-premium" if template.is_premium else "is-free"
                )
                st.html(
                    f'<span class="ux-badge {badge_class}">'
                    f"{template_status(template, state.is_premium)}</span>"
                )
                st.caption(template.tagline)
                st.write(template.description)

                with st.expander("Preview the routine"):
                    lines = preview_lines(template, state.is_premium)
                    for line in lines:
                        st.write(f"• {line}")
                    if template.is_premium and not state.is_premium:
                        st.caption("2 of 4 blocks shown — unlock to see the complete plan.")

                if can_use(template, state.is_premium):
                    if st.button(
                        "Use this template",
                        key=f"ux_apply_{template.template_id}",
                        use_container_width=True,
                    ):
                        state.apply(template.template_id)
                        st.toast(f"{template.name} applied to the demo plan.")
                        st.rerun()
                else:
                    if st.button(
                        "Unlock premium preview",
                        key=f"ux_open_{template.template_id}",
                        use_container_width=True,
                    ):
                        state.open_preview(template.template_id)
                        st.rerun()

    if state.paywall_template_id:
        st.divider()
        render_paywall(state)
    return state


def render_post_plan_upsell(state: MarketplaceState | None = None) -> bool:
    """Upsell touchpoint immediately after a schedule is generated.

    Returns True when the visitor asks to browse the full marketplace.
    """
    _inject_styles()
    state = state or get_state()
    if state.is_premium:
        st.success("Guru Premium is active. Your advanced planning tools are unlocked.")
        return False

    copy = _upsell_copy("schedule_generated")
    st.divider()
    left, right = st.columns([2, 1])
    with left:
        st.html(
            f'<div class="ux-eyebrow">{copy["eyebrow"]}</div>'
            f'<div class="ux-panel"><h3>{copy["title"]}</h3><p>{copy["body"]}</p></div>'
        )
    with right:
        explore = st.button(copy["cta"], type="primary", key="ux_post_plan_explore")
        st.caption("Simulated upgrade · no payment")

    st.markdown("#### Two premium systems you can preview")
    premium = [template for template in get_templates() if template.is_premium]
    cards = st.columns(2)
    for column, template in zip(cards, premium):
        with column:
            with st.container(border=True):
                st.markdown(f"**{template.name}**")
                st.caption("🔒 Premium · 2 of 4 blocks shown")
                st.write(template.preview[0])
                st.write(template.preview[1])
                if st.button(
                    "Preview locked plan",
                    key=f"ux_post_open_{template.template_id}",
                ):
                    state.open_preview(template.template_id)
                    st.rerun()

    if state.paywall_template_id:
        render_paywall(state)
    return explore


def render_advanced_features(state: MarketplaceState | None = None) -> None:
    """Third upsell touchpoint: premium-only advanced capabilities."""
    _inject_styles()
    state = state or get_state()
    st.subheader("Advanced features")
    st.caption("Available with Guru Premium. The upgrade is simulated for this demo.")
    for feature in ADVANCED_FEATURES:
        with st.container(border=True):
            left, right = st.columns([4, 1])
            with left:
                st.markdown(f"#### {feature.name}")
                st.write(feature.description)
                st.caption(f"Premium benefit · {feature.benefit}")
            with right:
                if state.is_premium:
                    st.success("Included")
                elif st.button(
                    "Unlock",
                    key=f"ux_advanced_{feature.feature_id}",
                ):
                    state.open_preview("ultimate-productivity-routine")
                    st.rerun()
    if state.paywall_template_id:
        render_paywall(state)


@st.dialog("Guru Template Marketplace", width="large")
def _marketplace_dialog() -> None:
    """Wide dialog so B's Week view keeps its single mechanisms row."""
    render_marketplace()


def render_marketplace_entry() -> None:
    """Drop-in entry point for B's planner mechanisms row.

    B replaces the template column of `ui/mechanisms.render_mechanisms` with:

        render_marketplace_entry()

    The dialog hosts the full marketplace, so no second template promotion
    needs to appear in the Week view. Optimisation and leaderboard columns
    remain untouched.
    """
    st.html(
        '<p class="lp-mechanism-kicker">GURU MARKETPLACE · FREE + PREMIUM</p>'
        '<h2 class="lp-mechanism-title">Guru Template Marketplace</h2>'
        '<p class="lp-mechanism-copy">Browse free and premium weekly systems.</p>'
    )
    if st.button("Open Guru Marketplace", key="ux_marketplace_open", width="stretch"):
        _marketplace_dialog()


def _upsell_copy(context: UpsellContext) -> dict[str, str]:
    from ux.templates import UPSELL_COPY

    return UPSELL_COPY[context]


def get_templates():
    """Small indirection so tests can replace the catalog if needed."""
    from ux.templates import TEMPLATES

    return TEMPLATES
