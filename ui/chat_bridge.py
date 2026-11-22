"""Streamlit glue for the chat bridge. New module; does not touch B's files.

B 的页面（例如 tests/chat_bridge_preview.py 的模式）只需三件事：

1. ``on_chat_request_change=<callback>`` 传给 components.v2 component；
2. 把 ``chat_bridge_data(key)`` 合并进 ``data=``；
3. 在 ``data=`` 中按需带上自己的额外键（如 runs/handled 诊断项）。

示例（替换 Echo Stub 的核心三行）：

    from ui.chat_bridge import on_chat_request_change, chat_bridge_data
    ...
    register_component()(
        key=KEY,
        data={**chat_bridge_data(KEY), "runs": st.session_state[RUNS]},
        on_chat_request_change=lambda: on_chat_request_change(KEY),
    )

rerun 语义：响应只对同一个 requestId 计算一次；无关 rerun 会重放旧的
chatResponse 但不会重复调用昂贵的 AI 请求。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import streamlit as st

from core.chat_bridge import handle_bridge_request

RESPONSE_PREFIX = "lifepilot_chat_bridge_response"
HANDLED_PREFIX = "lifepilot_chat_bridge_handled_id"


def needs_response(
    request_id: Any,
    handled_id: Any,
    has_response: bool,
) -> bool:
    """Pure dedupe rule: only compute when there is no answer for this id yet."""
    return not (has_response and handled_id == request_id)


def on_chat_request_change(
    component_key: str,
    *,
    client: Any = None,
    now: datetime | None = None,
) -> None:
    """Handle one bridge request during the component-triggered rerun."""
    entry = st.session_state.get(component_key)
    request = entry.get("chat_request") if isinstance(entry, dict) else None
    if not isinstance(request, dict) or not request.get("requestId"):
        return
    response_key = f"{RESPONSE_PREFIX}_{component_key}"
    handled_key = f"{HANDLED_PREFIX}_{component_key}"
    if not needs_response(
        request["requestId"],
        st.session_state.get(handled_key),
        st.session_state.get(response_key) is not None,
    ):
        return
    response = handle_bridge_request(request, client=client, now=now)
    st.session_state[response_key] = response
    st.session_state[handled_key] = request["requestId"]


def chat_bridge_data(component_key: str) -> dict[str, Any]:
    """Data prop fragment carrying the latest chatResponse for the component."""
    return {"chatResponse": st.session_state.get(f"{RESPONSE_PREFIX}_{component_key}")}
