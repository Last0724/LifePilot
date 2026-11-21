"""Mount the local, browser-persisted weekly planner in Streamlit."""

from base64 import b64encode
import json
from pathlib import Path

import streamlit as st


ASSETS = Path(__file__).with_name("experience")
MEDIA = Path(__file__).with_name("assets")
MARKUP = """<div class="lp-experience" data-lifepilot-app>
    <div data-lp-surface></div>
    <div class="lp-toasts" data-lp-toasts aria-live="polite"></div>
    <div class="lp-cat-layer" data-lp-cat></div>
    <div class="lp-xp-flash" data-lp-flash aria-live="polite"></div>
    <audio data-lp-guru-audio preload="none"></audio>
    <dialog aria-labelledby="lp-experience-dialog-title"></dialog>
</div>"""


@st.cache_resource
def _register(styles: str, scripts: str):
    return st.components.v2.component(
        "lifepilot_weekly_planner",
        html=MARKUP,
        css=styles,
        js=scripts + """
        export default function (component) {
            return mountLifePilot(component.parentElement.querySelector("[data-lifepilot-app]"));
        }
        """,
        isolate_styles=False,
    )


def render_experience() -> None:
    """Mount checked-in UI assets. User data stays in browser storage."""
    styles = "\n".join((ASSETS / name).read_text(encoding="utf-8") for name in ("style.css", "guru.css"))
    media = {
        "portrait": _data_uri("guru-musk-royal-society.jpg", "image/jpeg"),
        "sleep": {language: _data_uri(f"guru-sleep-{language}.wav", "audio/wav") for language in ("en", "zh")},
    }
    scripts = "\n".join(
        (ASSETS / filename).read_text(encoding="utf-8")
        for filename in ("model.js", "guru.js", "guru_view.js", "view.js", "app.js")
    )
    scripts = f"window.LifePilotGuruMedia = {json.dumps(media)};\n{scripts}"

    _register(styles, scripts)(key="lifepilot_weekly")


def _data_uri(filename: str, content_type: str) -> str:
    encoded = b64encode((MEDIA / filename).read_bytes()).decode("ascii")
    return f"data:{content_type};base64,{encoded}"
