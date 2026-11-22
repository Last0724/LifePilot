"""Request dispatcher for B's chat bridge (ui/experience/chat_bridge.js).

Contract (from chat_bridge.js):

- Component -> Python (trigger):
    st.session_state[<component key>]["chat_request"] =
        {"requestId": str, "operation": str, "payload": dict}
- Python -> Component (data prop):
    {"chatResponse": {"requestId": str, "ok": bool,
                      "result": dict | None, "error": str | None}}

Supported operations:

- ``handle_chat_message``      payload = {"message": str, "state": dict | None}
                               -> core.chat_planner.handle_chat_message + adapt_chat
- ``build_confirmed_schedule`` payload = {"state": dict | None,
                                          "confirmed_fields": dict}
                               -> core.chat_adapter.plan_from_confirmed

This module is pure Python (no Streamlit import) so it can be unit-tested
offline; the Streamlit glue lives in ui/chat_bridge.py.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Mapping

from core.chat_adapter import adapt_chat, plan_from_confirmed
from core.chat_planner import handle_chat_message

OPERATION_CHAT = "handle_chat_message"
OPERATION_SCHEDULE = "build_confirmed_schedule"
SCHEDULE_PROVIDER = "python"  # 排程路径纯 Python 确定性计算，不调用 DeepSeek


def _parse_week_start(state: Mapping[str, Any] | None) -> date | None:
    """Read the chat state's week_start anchor, if any, as a date."""
    if not state:
        return None
    raw = state.get("week_start")
    if isinstance(raw, str):
        try:
            return date.fromisoformat(raw)
        except ValueError:
            return None
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw
    return None


def dispatch_operation(
    operation: Any,
    payload: Any,
    *,
    client: Any = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Run one bridge operation and return its plain result dict.

    Raises ValueError for malformed requests so the envelope wrapper can
    turn them into ``{"ok": False, "error": ...}``.
    """
    if not isinstance(payload, Mapping):
        raise ValueError("payload 必须是 JSON 对象。")
    state = payload.get("state")
    if state is not None and not isinstance(state, Mapping):
        raise ValueError("state 必须是 JSON 对象或 null。")

    if operation == OPERATION_CHAT:
        message = payload.get("message")
        if not isinstance(message, str):
            raise ValueError("chat 请求的 message 必须是字符串。")
        result = handle_chat_message(message, state, client=client)
        return adapt_chat(result)

    if operation == OPERATION_SCHEDULE:
        confirmed_fields = payload.get("confirmed_fields")
        if not isinstance(confirmed_fields, Mapping):
            raise ValueError("schedule 请求缺少 confirmed_fields（必须是 JSON 对象）。")
        return plan_from_confirmed(
            confirmed_fields,
            week_start=_parse_week_start(state),
            now=now,
            provider=SCHEDULE_PROVIDER,
        )

    raise ValueError(f"未知 operation: {operation!r}")


def handle_bridge_request(
    request: Any,
    *,
    client: Any = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Wrap a full bridge request in the {requestId, ok, result|error} envelope.

    Never raises: every failure becomes ``ok=False`` with a readable error so
    the component's promise rejection path works.
    """
    if not isinstance(request, Mapping):
        return {"requestId": None, "ok": False,
                "error": "request 必须是 JSON 对象。"}
    request_id = request.get("requestId")
    try:
        result = dispatch_operation(
            request.get("operation"), request.get("payload"),
            client=client, now=now,
        )
        return {"requestId": request_id, "ok": True, "result": result}
    except Exception as error:  # noqa: BLE001 - 桥接层必须兜底所有异常
        return {"requestId": request_id, "ok": False, "error": str(error)}
