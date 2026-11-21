"""Product introduction and first navigation action."""

import streamlit as st


def render_welcome(*, key: str = "welcome", offer_demo: bool = False) -> str | None:
    """Return 'start' or 'demo' when the corresponding button is pressed."""
    st.html(
        """
        <section class="lp-hero" aria-labelledby="lp-welcome-title">
          <div>
            <h1 id="lp-welcome-title">Make time for<br><em>what matters.</em></h1>
            <p>Tell LifePilot what you want to get done. Get an AI-assisted
              weekly plan you can adjust as life changes.</p>
          </div>
          <div class="lp-sample" aria-label="Example day">
            <h2>What your day could look like</h2>
            <div class="lp-sample-row"><time>09:00</time><b>Focus on your most important goal</b></div>
            <div class="lp-sample-row is-fixed"><time>11:00</time><b>Team check-in · Fixed</b></div>
            <div class="lp-sample-row"><time>14:00</time><b>Review and wrap up</b></div>
          </div>
        </section>
        """
    )
    primary, secondary, _ = st.columns([1, 1, 3])
    if primary.button("Start planning", type="primary", key=f"{key}_start", width="stretch"):
        return "start"
    if offer_demo and secondary.button("Explore demo", key=f"{key}_demo", width="stretch"):
        return "demo"
    return None
