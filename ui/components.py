"""Shared visual components for the LifePilot interface."""

import streamlit as st


def apply_theme() -> None:
    """Apply the shared styles once from the Streamlit entry point."""
    st.html(
        """
        <style>
        .stApp {
            background: #f7f7fc;
            color: #20213c;
        }
        .stMainBlockContainer {
            max-width: 82rem;
            padding-top: clamp(1.5rem, 4vw, 3.5rem);
            padding-bottom: 3rem;
        }
        .st-key-lp_preview [data-testid="stHeading"] h1,
        .st-key-lp_preview [data-testid="stHeading"] h2 { color: #20213c; }
        .lp-brand, .lp-hero, .lp-week, .lp-timeline, .lp-profile {
            box-sizing: border-box;
            color: #20213c;
        }
        .lp-brand { display: flex; align-items: center; gap: .65rem; font-weight: 750;
            font-size: 1.22rem; letter-spacing: -.035em; padding-bottom: .5rem; }
        .lp-logo { display: inline-grid; place-items: center; width: 2.1rem; height: 2.1rem;
            border-radius: .65rem; background: #5b4bc7; color: white; font-size: 1.15rem; }
        .lp-hero { display: grid; grid-template-columns: 1.1fr 1fr; gap: 2rem; align-items: center;
            border: 1px solid #e8e3fa; border-radius: 1.65rem; padding: clamp(1.6rem, 5vw, 4.2rem);
            background: radial-gradient(ellipse at 95% 10%, #dcd6ff, transparent 55%), #eeebfc;
            min-height: 26rem; }
        .lp-hero h1 { font-size: clamp(2.4rem, 6vw, 4.85rem); color: #20213c;
            letter-spacing: -.075em; line-height: .99; padding: 0; margin: 0 0 1.35rem; }
        .lp-hero h1 em { font-style: normal; color: #5846bc; }
        .lp-hero p { max-width: 29rem; font-size: 1.08rem; line-height: 1.6; margin: 0; color: #484962; }
        .lp-sample { padding: 1.3rem; border: 1px solid #e0daf4; background: #fcfbff;
            border-radius: 1.2rem; box-shadow: 0 14px 42px #392d7f14; }
        .lp-sample h2 { color: #20213c; padding: 0; margin: 0 0 .85rem; font-size: 1.15rem; }
        .lp-sample-row { display: grid; grid-template-columns: 3.1rem minmax(0, 1fr); align-items: center;
            gap: .65rem; margin-top: .55rem; font-size: .82rem; color: #555671; }
        .lp-sample-row b { padding: .65rem; border-radius: .48rem; background: #ede9fc; color: #41348a; }
        .lp-sample-row.is-fixed b { background: #dff2ed; color: #21574d; }
        .lp-profile { background: #29254f; color: #f5f2ff; border-radius: 1rem; padding: 1.35rem 1.6rem; }
        .lp-profile h2 { padding: 0; margin: 0 0 .4rem; font-size: 1.1rem; color: #fff; }
        .lp-profile p { margin: 0; color: #eeebff; line-height: 1.55; white-space: pre-wrap;
            overflow-wrap: anywhere; }
        .lp-metrics { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr));
            gap: .65rem; margin: 0; color: #20213c; }
        .lp-metrics div { min-width: 0; padding: .75rem clamp(.55rem, 2vw, 1.15rem);
            border: 1px solid #e8e6f4; background: #fff; border-radius: .75rem; }
        .lp-metrics dt { font-size: .82rem; line-height: 1.3; color: #53546c; }
        .lp-metrics dd { margin: .25rem 0 0; font-size: clamp(1.1rem, 4vw, 1.8rem);
            font-weight: 700; letter-spacing: -.04em; }
        .lp-week { display: grid; grid-template-columns: repeat(7, minmax(0, 1fr)); gap: .55rem; }
        .lp-day { min-width: 0; background: #fff; border: 1px solid #e8e6f4; border-radius: .85rem;
            padding: .65rem; min-height: 12.5rem; }
        .lp-day h3 { color: #242441; font-size: 1.25rem; letter-spacing: -.025em; padding: 0;
            margin: 0 0 .7rem; }
        .lp-day h3 span { display: block; font-size: .76rem; color: #55566e; }
        .lp-event { padding: .5rem; border-radius: .42rem; margin: .35rem 0 0;
            border-left: 3px solid #6b58cb; background: #eeebff; color: #372d72; }
        .lp-event.is-fixed { border-color: #3f8575; background: #e0f2ed; color: #205649; }
        .lp-event.is-complete { border-color: #74788b; background: #edf0f5; color: #3d465a; }
        .lp-event strong { display: block; font-size: .79rem; overflow-wrap: anywhere; }
        .lp-event small { font-size: .69rem; display: block; line-height: 1.35; }
        .lp-legend { display: flex; flex-wrap: wrap; gap: .4rem 1rem; margin: 0 0 .7rem;
            font-size: .82rem; color: #53546c; }
        .lp-legend span::before { content: "●"; color: #6b58cb; margin-right: .35rem; }
        .lp-legend span:nth-child(2)::before { color: #3f8575; }
        .lp-legend span:nth-child(3)::before { color: #74788b; }
        .lp-empty { color: #61627c; font-size: .78rem; margin: 0; }
        .lp-timeline { display: grid; gap: .45rem; }
        .lp-timeline .lp-event { display: grid; grid-template-columns: minmax(5.5rem, 7.5rem) minmax(0, 1fr);
            align-items: center; gap: .65rem; padding: .7rem .85rem; margin: 0; }
        .lp-timeline .lp-event strong { font-size: .93rem; }
        .lp-timeline .lp-event small { font-size: .77rem; }
        @media (max-width: 1070px) { .lp-week { grid-template-columns: repeat(4, minmax(0, 1fr)); } }
        @media (max-width: 760px) {
            .lp-week { grid-template-columns: repeat(2, minmax(0, 1fr)); }
            .lp-hero { grid-template-columns: 1fr; min-height: auto; gap: 1.3rem; }
            .lp-day { min-height: 8rem; }
        }
        </style>
        """
    )


def render_brand() -> None:
    st.html(
        '<div class="lp-brand"><span class="lp-logo" aria-hidden="true">✦</span>'
        "<span>LifePilot</span></div>"
    )
