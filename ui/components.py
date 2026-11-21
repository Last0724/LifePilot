"""Shared visual components for the LifePilot interface."""

import streamlit as st


BRAND_MARKUP = (
    '<div class="lp-brand"><span class="lp-logo" aria-hidden="true">✦</span>'
    "<span>LifePilot</span></div>"
)


def apply_theme() -> None:
    """Apply the preview's shared styles."""
    st.html(
        """
        <style>
        .stApp:has(.st-key-lp_preview) {
            --lp-ink: #181818;
            --lp-secondary: #555;
            --lp-border: #dedede;
            --lp-wash: #f4f4f4;
            background: #fafafa;
        }
        .stApp:has(.st-key-lp_preview) [data-testid="stHeader"] { display: none; }
        .stApp:has(.st-key-lp_preview) .stMainBlockContainer {
            max-width: 82rem;
            padding-top: clamp(1rem, 3vw, 2.25rem);
            padding-bottom: 2rem;
        }
        .st-key-lp_header [data-testid="stHorizontalBlock"]:not(.st-key-lp_header_actions) {
            align-items: center; justify-content: space-between; flex-wrap: nowrap;
        }
        .st-key-lp_header [data-testid="stColumn"] { width: auto; min-width: 0; flex: 0 1 auto; }
        .st-key-lp_header button { white-space: nowrap; }
        .lp-classic-return { display: inline-block; color: #181818; font-size: .82rem; text-underline-offset: .2em; }
        .lp-mascot {
            display: block; width: 44px; height: auto; image-rendering: pixelated;
            animation: lp-mascot-bob 3.8s ease-in-out infinite;
        }
        @keyframes lp-mascot-bob {
            0%, 60%, 100% { transform: translateY(0); }
            25% { transform: translateY(var(--lp-mascot-lift, -2px)); }
        }
        @media (prefers-reduced-motion: reduce) {
            .lp-mascot { animation: none; }
        }
        @media (max-width: 540px) {
            .st-key-lp_header [data-testid="stHorizontalBlock"]:not(.st-key-lp_header_actions) {
                flex-wrap: wrap; gap: .5rem;
            }
            .st-key-lp_header [data-testid="stColumn"]:last-child { margin-inline-start: auto; }
            .st-key-lp_header_actions { gap: .35rem; }
            .st-key-lp_header button { font-size: .8rem; padding-inline: .45rem; }
            .st-key-lp_header button p { font-size: .8rem; }
            .st-key-lp_header .lp-brand { font-size: 1rem; gap: .4rem; }
        }
        .st-key-lp_sign_in {
            width: min(100%, 27rem); margin-inline: auto;
            margin-top: clamp(2rem, 11vh, 7rem);
            padding: clamp(1.25rem, 4vw, 2rem);
            background: white; border: 1px solid var(--lp-border); border-radius: 1rem;
        }
        .st-key-lp_sign_in_heading { text-align: center; gap: .25rem; }
        .st-key-lp_sign_in_heading h1 { margin: 0; padding: 0; font-size: clamp(1.8rem, 6vw, 2.25rem); }
        .st-key-lp_sign_in_heading p { color: var(--lp-secondary); }
        .st-key-lp_sign_in [data-testid="stForm"] { padding: 0; }
        .st-key-lp_preview [data-testid="stHeading"] h1,
        .st-key-lp_preview [data-testid="stHeading"] h2 { color: var(--lp-ink); }
        .st-key-lp_preview h1 { letter-spacing: -.045em; }
        [class*="st-key-lp_questionnaire_"] {
            width: min(100%, 72rem);
            align-self: center;
            margin-inline: auto;
            padding-top: clamp(2rem, 6vh, 4.5rem);
            gap: .75rem;
        }
        [class*="st-key-lp_question_intro_"] {
            text-align: center;
            gap: .5rem;
            margin-bottom: .55rem;
        }
        .st-key-lp_preview [class*="st-key-lp_question_intro_"] h1 {
            padding: 0;
            margin: 0;
            font-size: clamp(2rem, 5vw, 3rem);
            font-weight: 660;
            line-height: 1.15;
            text-align: center;
        }
        [class*="st-key-lp_question_intro_"] p {
            color: var(--lp-secondary, #555);
            font-size: .95rem;
            text-align: center;
        }
        .lp-calendar-range {
            margin: 0; color: var(--lp-secondary, #555);
            font-size: .86rem; font-weight: 600; font-variant-numeric: tabular-nums;
        }
        [class*="st-key-lp_calendar_grid_"] [data-testid="stHorizontalBlock"] {
            display: grid; grid-template-columns: repeat(7, minmax(0,1fr)); gap: .55rem;
            align-items: stretch;
        }
        [class*="st-key-lp_calendar_grid_"] [data-testid="stColumn"] {
            width: 100%; min-width: 0;
        }
        [class*="st-key-lp_calendar_day_"] {
            gap: .5rem; min-height: 10rem; padding: .65rem;
            border: 1px solid var(--lp-border, #dedede); border-radius: .7rem; background: white;
        }
        .lp-calendar-date {
            display: grid; gap: .1rem; margin: 0; padding: 0 0 .55rem;
            border-bottom: 1px solid var(--lp-border, #dedede);
            font-size: .9rem; line-height: 1.5; letter-spacing: 0;
        }
        .lp-calendar-date time {
            color: var(--lp-secondary, #555); font-size: .76rem; font-weight: 450;
        }
        [class*="st-key-lp_calendar_day_"] button {
            min-height: 2.15rem; padding: .35rem .5rem; text-align: left;
        }
        [class*="st-key-lp_calendar_day_"] button p {
            margin: 0; font-size: .77rem; line-height: 1.4; overflow-wrap: anywhere;
        }
        [class*="st-key-lp_calendar_day_"] [class*="_edit_calendar_"] button {
            justify-content: flex-start; background: var(--lp-wash, #f4f4f4);
        }
        [class*="st-key-lp_calendar_day_"] [class*="_add_calendar_"] button {
            border-style: dashed;
        }
        .lp-calendar-fixed {
            padding: .38rem .45rem; color: #444; border: 1px dashed #aaa; border-radius: .4rem;
            font-size: .76rem; overflow-wrap: anywhere;
        }
        .lp-calendar-fixed span, .lp-calendar-fixed strong { display: block; }
        [class*="st-key-lp_question_action_"] > [data-testid="stElementContainer"] {
            align-self: flex-end;
        }
        [class*="st-key-lp_question_action_"] button { min-width: 7rem; }
        @media (max-width: 1000px) {
            [class*="st-key-lp_calendar_grid_"] [data-testid="stHorizontalBlock"] {
                grid-template-columns: repeat(4, minmax(0,1fr));
            }
        }
        @media (max-width: 600px) {
            [class*="st-key-lp_questionnaire_"] { padding-top: 2rem; }
            [class*="st-key-lp_calendar_grid_"] [data-testid="stHorizontalBlock"] {
                grid-template-columns: repeat(2, minmax(0,1fr));
            }
            [class*="st-key-lp_calendar_day_"] { min-height: 7rem; }
        }
        .lp-brand, .lp-hero, .lp-week, .lp-timeline, .lp-profile {
            box-sizing: border-box;
            color: var(--lp-ink, #181818);
        }
        .lp-brand { display: flex; align-items: center; gap: .65rem; font-weight: 750;
            font-size: 1.22rem; letter-spacing: -.035em; }
        .lp-logo { display: inline-grid; place-items: center; width: 2.1rem; height: 2.1rem;
            border-radius: .65rem; background: #181818; color: white; font-size: 1.15rem; }
        [class*="st-key-lp_hero_"] {
            border: 1px solid var(--lp-border, #dedede); border-radius: 1.4rem;
            background: #fff; padding: clamp(1.2rem, 4vw, 3.5rem);
        }
        .lp-hero h1 { font-size: clamp(2.55rem, 6vw, 4.65rem); color: var(--lp-ink, #181818);
            letter-spacing: -.075em; line-height: 1.01; padding: 0; margin: 0 0 1rem; }
        .lp-hero p { max-width: 27rem; font-size: 1.05rem; line-height: 1.65; margin: 0;
            color: var(--lp-secondary, #555); }
        .lp-sample { padding: 1.2rem; border: 1px solid var(--lp-border, #dedede); background: #fff;
            border-radius: 1rem; box-shadow: 0 10px 24px #0000000d; }
        .lp-sample p { color: var(--lp-secondary, #555); margin: 0 0 .2rem; font-size: .8rem; }
        .lp-sample h2 { color: var(--lp-ink, #181818); padding: 0; margin: 0 0 .65rem; font-size: 1.35rem; }
        .lp-sample-row { display: grid; grid-template-columns: 3rem minmax(0, 1fr); align-items: center;
            gap: .6rem; margin-top: .55rem; font-size: .85rem; color: var(--lp-secondary, #555); }
        .lp-sample-row b { padding: .65rem; border-radius: .48rem; border-left: 2px solid #181818;
            background: var(--lp-wash, #f4f4f4); color: var(--lp-ink, #181818); }
        .lp-sample-row.is-fixed b { background: #fff; border: 1px dashed #a7a7a7; }
        .lp-profile { background: var(--lp-wash, #f4f4f4); border: 1px solid var(--lp-border, #dedede);
            border-radius: .75rem; padding: 1rem 1.15rem; }
        .lp-profile h2 { padding: 0; margin: 0 0 .4rem; font-size: 1.05rem; }
        .lp-profile p { margin: 0; color: var(--lp-secondary, #555); line-height: 1.55;
            white-space: pre-wrap; overflow-wrap: anywhere; }
        .lp-metrics { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr));
            gap: .6rem; margin: 0; padding: 0; color: var(--lp-ink, #181818); }
        .lp-metrics div { min-width: 0; padding: .7rem clamp(.45rem, 2vw, 1rem);
            border: 1px solid var(--lp-border, #dedede); background: #fff; border-radius: .7rem; }
        .lp-metrics dt { font-size: .8rem; line-height: 1.3; color: var(--lp-secondary, #555); }
        .lp-metrics dd { margin: .25rem 0 0; font-size: clamp(1.1rem, 4vw, 1.7rem);
            font-weight: 700; letter-spacing: -.04em; }
        .lp-week { display: grid; grid-template-columns: repeat(7, minmax(0, 1fr)); gap: .55rem; }
        .lp-day { min-width: 0; background: #fff; border: 1px solid var(--lp-border, #dedede);
            border-radius: .75rem; padding: .65rem; min-height: 10rem; }
        .lp-day h3 { color: var(--lp-ink, #181818); font-size: 1.12rem; letter-spacing: -.025em; padding: 0;
            margin: 0 0 .6rem; }
        .lp-day h3 span { display: block; font-size: .76rem; color: var(--lp-secondary, #555); }
        .lp-event { padding: .5rem; border-radius: .42rem; margin: .35rem 0 0;
            border-left: 3px solid #333; background: #f0f0f0; color: #272727; }
        .lp-event.is-fixed { border: 1px dashed #999; background: #fff; }
        .lp-event.is-complete { border-color: #999; background: #f4f4f4; color: #555; }
        .lp-event.is-complete strong { text-decoration: line-through; }
        .lp-event strong { display: block; font-size: .85rem; overflow-wrap: anywhere; }
        .lp-event small { font-size: .73rem; display: block; line-height: 1.4;
            font-variant-numeric: tabular-nums; }
        .lp-legend { display: flex; flex-wrap: wrap; gap: .4rem 1rem; margin: 0 0 .7rem;
            font-size: .8rem; color: var(--lp-secondary, #555); }
        .lp-legend span::before { content: "■"; color: #333; margin-right: .35rem; }
        .lp-legend span:nth-child(2)::before { content: "□"; }
        .lp-legend span:nth-child(3)::before { content: "✓"; }
        .lp-empty { color: var(--lp-secondary, #555); font-size: .78rem; margin: 0; }
        .lp-timeline { display: grid; gap: .45rem; }
        .lp-timeline .lp-event { display: grid; grid-template-columns: minmax(5.25rem, 7.5rem) minmax(0, 1fr);
            align-items: center; gap: .65rem; padding: .65rem .85rem; margin: 0; }
        .lp-timeline .lp-event strong { font-size: .93rem; }
        .lp-timeline .lp-event small { font-size: .77rem; }
        .st-key-lp_calendar_toolbar {
            justify-content: space-between;
        }
        .st-key-lp_consultation {
            width: min(100%, 60rem); align-self: center; margin-inline: auto;
            padding-top: clamp(1rem, 4vh, 2.75rem);
        }
        .lp-field-status {
            display: inline-block; padding: .15rem .5rem; margin-bottom: -.35rem;
            border-radius: 999px; border: 1px solid #dedede;
            color: #555; background: #f5f5f5; font-size: .72rem; font-weight: 600;
        }
        .lp-field-status.confirmed { background: #181818; color: white; border-color: #181818; }
        .lp-consult-details {
            display: grid; gap: .5rem; margin: 0; padding: 0;
        }
        .lp-consult-detail {
            border: 1px solid #dedede; border-radius: .6rem; background: white;
            padding: .6rem .75rem; min-width: 0;
        }
        .lp-consult-detail dt { font-size: .82rem; font-weight: 650; }
        .lp-consult-detail dt small { margin-inline-start: .4rem; font-weight: 450; color: #555; }
        .lp-consult-detail dd {
            margin: .2rem 0 0; color: #444; font-size: .86rem;
            white-space: pre-wrap; overflow-wrap: anywhere;
        }
        .lp-demo-shortcut, .lp-demo-anchor { color: var(--lp-secondary, #555); font-size: .82rem; }
        .lp-demo-shortcut { text-underline-offset: .2rem; }
        .lp-demo-anchor { margin: .35rem 0 0; font-weight: 650; }
        .st-key-lp_mechanisms {
            margin-block: .3rem .5rem;
        }
        .st-key-lp_mechanisms [data-testid="stHorizontalBlock"] { align-items: stretch; }
        [class*="st-key-lp_mechanism_"] {
            padding: .8rem; gap: .55rem; min-height: 8.25rem;
            background: white; border: 1px solid var(--lp-border, #dedede);
            border-radius: .75rem;
        }
        .lp-mechanism-kicker {
            margin: 0 0 .32rem; color: var(--lp-secondary, #555);
            font-size: .68rem; letter-spacing: .075em; font-weight: 650;
        }
        .lp-mechanism-title {
            margin: 0; padding: 0; font-size: 1.02rem; line-height: 1.3;
            letter-spacing: -.025em;
        }
        .lp-mechanism-copy { margin: .4rem 0 0; color: #555; font-size: .79rem; line-height: 1.4; }
        .lp-rankings {
            width: 100%; border-collapse: collapse; font-variant-numeric: tabular-nums;
        }
        .lp-rankings th, .lp-rankings td {
            padding: .5rem .65rem; text-align: left; border-bottom: 1px solid #dedede;
        }
        .lp-rankings th:last-child, .lp-rankings td:last-child { text-align: right; }
        @media (max-width: 1070px) { .lp-week { grid-template-columns: repeat(4, minmax(0, 1fr)); } }
        @media (max-width: 760px) {
            .lp-week { grid-template-columns: repeat(2, minmax(0, 1fr)); }
            .lp-day { min-height: 7.5rem; }
            .st-key-lp_preview [data-testid="stHeading"] h1 { font-size: clamp(1.75rem, 8vw, 2.25rem); }
            .lp-hero h1 { letter-spacing: -.06em; }
        }
        </style>
        """
    )


def render_brand() -> None:
    """Show the LifePilot wordmark."""
    st.html(BRAND_MARKUP)
