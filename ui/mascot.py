"""LifePilot's full-body pixel cat."""

from base64 import b64encode
from pathlib import Path

import streamlit as st


_SPRITE = Path(__file__).with_name("assets") / "pixel-cat.png"
_SPRITE_DATA = b64encode(_SPRITE.read_bytes()).decode("ascii")
MASCOT_IMAGE = (
    '<img class="lp-mascot" alt="全身马赛克黑猫 / Full-body pixel black cat" '
    f'width="22" height="15" src="data:image/png;base64,{_SPRITE_DATA}">'
)


def render_mascot() -> None:
    st.html(MASCOT_IMAGE, width="content")
