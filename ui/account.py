"""Session-only sign-in for the independently runnable preview."""

import streamlit as st


ACCOUNT_KEY = "preview_account_name"


def render_account_menu() -> None:
    with st.popover("Account", key="lp_account_menu"):
        st.caption("Signed in as / 当前登录")
        st.text(st.session_state[ACCOUNT_KEY])
        if st.button("Sign out / 退出登录", key="preview_sign_out"):
            del st.session_state[ACCOUNT_KEY]
            st.rerun()


def render_sign_in() -> str | None:
    """Return the submitted display name once the demo form is valid."""
    with st.container(key="lp_sign_in"):
        with st.container(key="lp_sign_in_heading"):
            st.title("Sign in to LifePilot", anchor=False)
            st.markdown("登录 LifePilot")
        with st.form("lp_sign_in_form", border=False):
            st.caption("Use a display name for this preview. / 输入一个昵称即可体验。")
            name = st.text_input("Display name / 昵称", max_chars=32, placeholder="Alex").strip()
            submitted = st.form_submit_button("Sign in / 登录", type="primary", width="stretch")
            if submitted and not name:
                st.error("Enter a display name. / 请输入昵称。")
    return name if submitted and name else None
