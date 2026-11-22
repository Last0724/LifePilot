"""Standalone LifePilot brand showcase."""

import streamlit as st

from ui.components import BRAND_MARKUP
from ui.mascot import MASCOT_IMAGE


def render_showcase() -> None:
    st.html(
        """
        <style>
        .stApp:has(.lp-showcase) { background: #fff; }
        .stApp:has(.lp-showcase) [data-testid="stHeader"] { display: none; }
        .stApp:has(.lp-showcase) .stMainBlockContainer { max-width: none; padding: 0; }
        .lp-showcase {
            box-sizing: border-box;
            min-height: 100svh;
            display: grid;
            align-content: center;
            justify-items: center;
            gap: clamp(1.4rem, 5svh, 3rem);
            padding: clamp(1.5rem, 4vw, 3rem);
            color: #181818;
            text-align: center;
        }
        .lp-showcase .lp-brand { gap: .7rem; font-size: clamp(1.6rem, 3.5vw, 2.1rem); }
        .lp-showcase .lp-logo { width: 2.55rem; height: 2.55rem; font-size: 1.4rem; border-radius: .75rem; }
        .lp-showcase-cat { display: grid; justify-items: center; }
        .lp-showcase .lp-mascot {
            width: clamp(10.1rem, min(57vw, 46svh), 20.125rem);
            --lp-mascot-lift: -6px;
        }
        .lp-showcase-cat::after {
            content: "";
            width: 76%;
            height: .55rem;
            background: #ededed;
            clip-path: polygon(5% 0, 95% 0, 95% 33%, 100% 33%, 100% 67%, 95% 67%,
                               95% 100%, 5% 100%, 5% 67%, 0 67%, 0 33%, 5% 33%);
        }
        .lp-showcase h1 {
            margin: 0;
            padding: 0;
            font-size: clamp(1.45rem, 4vw, 3rem);
            line-height: 1.2;
            font-weight: 720;
            letter-spacing: -.035em;
            text-wrap: balance;
        }
        .lp-showcase p {
            margin: .65rem 0 0;
            color: #555;
            font-size: clamp(1rem, 2vw, 1.2rem);
            line-height: 1.45;
            text-wrap: balance;
        }
        .lp-showcase .lp-showcase-enter {
            display: inline-flex;
            align-items: center;
            min-height: 2.75rem;
            margin-top: 1.55rem;
            padding: .55rem 1.2rem;
            border-radius: .65rem;
            background: #181818;
            color: #fff;
            font-weight: 650;
            text-decoration: none;
        }
        .lp-showcase .lp-showcase-enter:hover { background: #383838; }
        .lp-showcase .lp-showcase-enter:focus-visible {
            outline: 2px solid #181818;
            outline-offset: 3px;
        }
        </style>
        """
        f"""
        <article class="lp-showcase" aria-label="LifePilot">
            {BRAND_MARKUP}
            <div class="lp-showcase-cat">{MASCOT_IMAGE}</div>
            <div>
                <h1 lang="zh-CN">用 AI，把目标排进一周。</h1>
                <p lang="en">Turn your goals into a weekly plan with AI.</p>
                <a class="lp-showcase-enter" href="?"><span lang="zh-CN">进入</span>&nbsp;/&nbsp;<span lang="en">Enter LifePilot</span></a>
            </div>
        </article>
        """
    )
