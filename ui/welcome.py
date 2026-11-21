"""Product introduction and first navigation action."""

import streamlit as st


def render_welcome(*, key: str = "welcome", offer_demo: bool = False) -> str | None:
    """Return 'start' or 'demo' when the corresponding button is pressed."""
    with st.container(key=f"lp_hero_{key}"):
        introduction, example = st.columns([1.1, 1], gap="large", vertical_alignment="center")
        with introduction:
            st.html(
                """
                <section class="lp-hero" aria-labelledby="lp-welcome-title">
                  <h1 id="lp-welcome-title">Make time for<br>what matters.</h1>
                  <p>Tell LifePilot what you want to get done. Review a weekly
                    plan and adjust it as life changes.</p>
                </section>
                """
            )
            if offer_demo:
                primary, secondary = st.columns(2)
                demo = secondary.button("Explore demo", key=f"{key}_demo", width="stretch")
            else:
                primary, demo = st.container(), False
            start = primary.button("Start planning", type="primary", key=f"{key}_start", width="stretch")
        with example:
            st.html(
                """
                <div class="lp-sample" aria-label="Example day">
                  <p>Example day</p>
                  <h2>Monday</h2>
                  <div class="lp-sample-row"><time>09:00</time><b>Outline your most important project</b></div>
                  <div class="lp-sample-row is-fixed"><time>11:00</time><b>Team check-in · Fixed</b></div>
                  <div class="lp-sample-row"><time>14:00</time><b>Review and wrap up</b></div>
                </div>
                """
            )
    return "start" if start else "demo" if demo else None
