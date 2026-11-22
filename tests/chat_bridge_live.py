"""Live bridge harness (E2E test page only — NOT part of B's frontend).

Run:
    .venv/Scripts/python.exe -m streamlit run tests/chat_bridge_live.py \
        --server.headless true --server.port 8513

This page reproduces the exact client contract documented in
ui/experience/chat_bridge.js (requestId envelope, chat_request trigger,
chatResponse in the data prop) with a minimal self-contained JS renderer,
and drives the REAL Python dispatcher through ui.chat_bridge.
"""

import streamlit as st

from tests.test_chat_planner import FakeClient, full_payload
from ui.chat_bridge import chat_bridge_data, on_chat_request_change

KEY = "lifepilot_bridge_live"
HANDLED = "bridge_live_handled"
SEEN = "bridge_live_seen_id"

HTML = """
<div data-live-root>
    <dl aria-label="Bridge diagnostics">
        <div><dt>handled</dt><dd data-live-handled></dd></div>
        <div><dt>sent</dt><dd data-live-sent></dd></div>
        <div><dt>response</dt><dd data-live-response></dd></div>
        <div><dt>status</dt><dd data-live-status></dd></div>
    </dl>
    <input data-live-input placeholder="say something" />
    <button data-live-send>Send</button>
    <button data-live-schedule>Build schedule</button>
    <div data-live-thread></div>
</div>
"""

JS = """
let next = 0;
let chatState = null;
export default function (component) {
  const root = component.parentElement.querySelector("[data-live-root]");
  const input = root.querySelector("[data-live-input]");
  const thread = root.querySelector("[data-live-thread]");
  const setMetric = (name, value) => {
    root.querySelector("[data-live-" + name + "]").textContent = String(value ?? "");
  };
  setMetric("handled", (component.data || {}).handled);
  const data = component.data || {};
  if (data.chatResponse && window.__pending) {
    const pending = window.__pending;
    if (pending.requestId === data.chatResponse.requestId) {
      window.__pending = null;
      setMetric("response", data.chatResponse.requestId);
      setMetric("status", data.chatResponse.ok ? "ok" : "error");
      const div = document.createElement("div");
      div.className = "msg";
      if (data.chatResponse.ok) {
        const result = data.chatResponse.result;
        div.textContent = "reply: " + (result && result.reply);
        if (result && result.entries) {
          div.textContent += " | entries=" + result.entries.length;
        }
        if (result && result.state) chatState = result.state;
      } else {
        div.textContent = "error: " + data.chatResponse.error;
      }
      thread.appendChild(div);
    }
  }
  const send = (operation, payload) => {
    const requestId = "live:" + (++next);
    window.__pending = { requestId, operation };
    setMetric("sent", requestId);
    component.setTriggerValue("chat_request", { requestId, operation, payload });
  };
  root.querySelector("[data-live-send]").onclick = () => {
    const message = input.value;
    input.value = "";
    send("handle_chat_message", { message, state: chatState });
  };
  root.querySelector("[data-live-schedule]").onclick = () => {
    send("build_confirmed_schedule", {
      state: chatState,
      confirmed_fields: {
        goal: "demo", tasks: [{ title: "写代码", details: "时长 60 分钟" }],
        commitments: [{ title: "Team check-in", date: "2026-11-23",
                        startTime: "11:00", endTime: "11:30" }],
        wake: "07:00", bed: "23:00", rest: "",
        workStart: "09:00", workEnd: "17:00", routine: "运动 30 分钟",
      },
    });
  };
}
"""


@st.cache_resource
def live_client():
    return FakeClient([full_payload()])


@st.cache_resource
def register():
    return st.components.v2.component(
        "lifepilot_bridge_live", html=HTML, js=JS, isolate_styles=False
    )


def on_request() -> None:
    entry = st.session_state.get(KEY)
    request = entry.get("chat_request") if isinstance(entry, dict) else None
    on_chat_request_change(KEY, client=live_client())
    if request and request.get("requestId") != st.session_state.get(SEEN):
        st.session_state[SEEN] = request["requestId"]
        st.session_state[HANDLED] = st.session_state.get(HANDLED, 0) + 1


def main() -> None:
    st.set_page_config(page_title="LifePilot Chat Bridge Live", layout="wide")
    st.title("LifePilot · Chat Bridge Live Harness")
    st.caption("真实 dispatcher + FakeClient。第一个 chat 消息走 DeepSeek 形状响应，后续消息走 fallback。")
    st.button("Trigger unrelated rerun")
    register()(
        key=KEY,
        data={**chat_bridge_data(KEY), "handled": st.session_state.get(HANDLED, 0)},
        on_chat_request_change=on_request,
    )


if __name__ == "__main__":
    main()
