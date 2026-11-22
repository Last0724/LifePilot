(function (root, factory) {
  const chat = factory();
  if (typeof module === "object" && module.exports) module.exports = chat;
  else root.LifePilotChat = chat;
})(globalThis, function () {
  "use strict";

  // Import only the returned blocks using the existing planner's validation.
  function importSchedule(model, state, fields, schedule, now) {
    if (!Array.isArray(schedule?.entries) || !schedule.entries.length) return { error: { code: "noTasks" } };
    const defaults = state.user.routine;
    const routine = {
      wake: fields.wake || defaults.wake, bed: fields.bed || defaults.bed,
      workStart: fields.workStart || defaults.workStart, workEnd: fields.workEnd || defaults.workEnd,
    };
    if (model.routineError(routine)) return { error: { code: "routine" } };
    const goal = fields.goal.trim();

    const next = { ...state, tasks: [...state.tasks], notifications: [...state.notifications] };
    for (const { title, date, startTime, endTime, category, priority, repeatWeekly } of schedule.entries) {
      const result = model.saveTask(next, { title, date, startTime, endTime, category, priority, repeatWeekly }, now);
      if (result.error) return result;
    }
    const firstDate = schedule.entries.map((entry) => entry.date).sort()[0];
    Object.assign(state, {
      tasks: next.tasks, notifications: next.notifications,
      user: { ...state.user, routine, goal, chatPlanWeek: model.monday(firstDate), onboardingCompleted: true },
    });
    return { updated: true, firstDate };
  }

  function create({ adapter, t, e, onBack, onPlan }) {
    let panel = null;
    let messages = [];
    let conversation = null;
    let fields = {};
    let ready = false;
    let fallback = false;
    let manualReview = false;
    let draft = "";
    let busy = "";
    let issue = null;
    let retryMessage = null;
    let session = 0;

    const text = (en, zh) => e(t(en, zh));
    const disabledAttr = () => busy ? "disabled" : "";
    const field = (label, name, value, { type = "text", required = false, limit = 160 } = {}) => {
      const attrs = `data-chat-field="${name}" name="${name}" maxlength="${limit}" ${required ? "required" : ""} ${disabledAttr()}`;
      const control = type === "textarea"
        ? `<textarea ${attrs} rows="2">${e(value)}</textarea>`
        : `<input ${attrs} type="${type}" value="${e(value)}">`;
      return `<label class="lp-field lp-chat-field"><span>${label}</span>${control}</label>`;
    };
    const button = (label, action, cls = "lp-subtle", disabled = Boolean(busy)) =>
      `<button type="button" class="lp-button ${cls}" data-chat-action="${action}" ${disabled ? "disabled" : ""}>${label}</button>`;

    function summary() {
      const rows = [
        [text("Goal", "目标"), fields.goal],
        [text("Tasks", "任务"), fields.tasks?.map((item) => item.title).join(t(", ", "、"))],
        [text("Fixed commitments", "固定安排"), fields.commitments?.map((item) => item.title).join(t(", ", "、"))],
        [text("Work hours", "工作时间"), [fields.workStart, fields.workEnd].filter(Boolean).join("–")],
      ].filter(([, value]) => value);
      return `<aside class="lp-card lp-chat-review"><h2>${text("Planner notes", "规划摘要")}</h2>${rows.length
        ? `<dl>${rows.map(([label, value]) => `<div><dt>${label}</dt><dd>${e(value)}</dd></div>`).join("")}</dl>`
        : `<p>${text("Your goal, tasks and constraints will appear as we talk.", "对话中整理出的目标、任务和时间限制会显示在这里。")}</p>`}
        ${fallback ? button(text("Fill in planning details", "手动补充规划信息"), "review", "lp-outline") : ""}</aside>`;
    }

    function confirmation() {
      const tasks = fields.tasks ?? [];
      const commitments = fields.commitments ?? [];
      return `<form class="lp-card lp-chat-review" data-chat-form="confirm" aria-labelledby="lp-chat-review-title">
        <h2 id="lp-chat-review-title" tabindex="-1">${text("Review your plan", "确认规划信息")}</h2>
        <p>${text("Edit anything here before generating your week.", "生成周计划前，可以直接修改下面的信息。")}</p>
        ${field(text("Main goal", "主要目标"), "goal", fields.goal)}
        <fieldset><legend>${text("Tasks", "任务")}</legend>
          ${tasks.map((task, index) => `<div class="lp-chat-item">
            ${field(text("Task name", "任务名称"), `tasks.${index}.title`, task.title, { required: true, limit: 90 })}
            ${field(text("Details", "时长、期限或备注"), `tasks.${index}.details`, task.details)}
            ${button(text("Remove task", "移除任务"), `remove.tasks.${index}`)}
          </div>`).join("")}
          ${button(text("Add task", "添加任务"), "add.tasks", "lp-outline", Boolean(busy) || tasks.length >= (adapter.taskLimit ?? Infinity))}
        </fieldset>
        <fieldset><legend>${text("Fixed commitments", "固定安排")}</legend>
          ${commitments.map((item, index) => `<div class="lp-chat-item">
            ${field(text("Commitment name", "安排名称"), `commitments.${index}.title`, item.title, { required: true, limit: 90 })}
            ${field(text("Date", "日期"), `commitments.${index}.date`, item.date, { type: "date", required: true })}
            <div class="lp-chat-times">
              ${field(text("Starts", "开始"), `commitments.${index}.startTime`, item.startTime, { type: "time", required: true })}
              ${field(text("Ends", "结束"), `commitments.${index}.endTime`, item.endTime, { type: "time", required: true })}
            </div>
            ${button(text("Remove commitment", "移除安排"), `remove.commitments.${index}`)}
          </div>`).join("")}
          ${button(text("Add commitment", "添加固定安排"), "add.commitments", "lp-outline")}
        </fieldset>
        <fieldset><legend>${text("Sleep and rest", "睡眠与休息")}</legend>
          <div class="lp-chat-times">
            ${field(text("Wake up", "起床"), "wake", fields.wake, { type: "time" })}
            ${field(text("Bedtime", "入睡"), "bed", fields.bed, { type: "time" })}
          </div>
          ${field(text("Rest preferences", "休息偏好"), "rest", fields.rest, { type: "textarea", limit: 2000 })}
        </fieldset>
        <fieldset><legend>${text("Work hours", "工作时间")}</legend>
          <div class="lp-chat-times">
            ${field(text("Work starts", "开始工作"), "workStart", fields.workStart, { type: "time" })}
            ${field(text("Work ends", "结束工作"), "workEnd", fields.workEnd, { type: "time" })}
          </div>
        </fieldset>
        ${field(text("Daily routine", "日常习惯"), "routine", fields.routine, { type: "textarea", limit: 2000 })}
        ${issue?.area === "plan" ? `<p class="lp-chat-error" role="alert">${e(issue.message)}</p>` : ""}
        <button class="lp-button lp-primary lp-chat-confirm" type="submit" ${disabledAttr()}>
          ${busy === "plan" ? text("Generating…", "正在生成…") : text("Confirm and generate week", "确认并生成周计划")}</button>
      </form>`;
    }

    function draw(focus, { scroll = false } = {}) {
      if (!panel?.isConnected) return;
      const oldLog = panel.querySelector("[data-chat-log]");
      const logTop = oldLog?.scrollTop;
      const opening = { role: "assistant", value: t("Tell me what you want to accomplish this week. You can share a long note about your tasks, fixed commitments and usual routine. I’ll ask about anything that’s missing.",
        "这周你想完成什么？可以用一段话告诉我任务、固定安排和日常作息。缺的信息我会再问你。") };
      const example = adapter.exampleMessage?.(conversation);
      panel.innerHTML = `<div class="lp-chat-wrap">
        <div class="lp-chat-heading"><div><h1>${text("AI Planner", "AI 规划助手")}</h1>
          ${adapter.exampleMessage ? `<p>${text("Demo mode uses sample information and a preset calendar. You can edit the sample before generating.", "当前演示使用示例信息和预设时段。生成周历前，你可以修改示例。")}</p>` : ""}
        </div>${button(text("Back", "返回"), "back", "lp-outline")}</div>
        <div class="lp-chat-grid">
          <section class="lp-card lp-chat-thread" aria-label="${text("Planner conversation", "规划对话")}">
            <div data-chat-log role="log" aria-live="polite" aria-relevant="additions" aria-label="${text("Conversation history", "对话记录")}">
              ${[opening, ...messages].map(({ role, value }) => `<div class="lp-chat-message lp-chat-${role}">
                <strong>${role === "user" ? text("You", "你") : text("LifePilot", "LifePilot")}</strong>
                <p>${e(value)}</p></div>`).join("")}
              ${busy === "message" ? `<p class="lp-chat-status" role="status">${text("Waiting for LifePilot…", "正在等待 LifePilot 回复…")}</p>` : ""}
            </div>
            <form data-chat-form="message" class="lp-chat-composer">
              ${issue?.area === "message" ? `<p class="lp-chat-error" role="alert">${e(issue.message)}</p>` : ""}
              <label class="lp-field"><span>${text("Message", "你的消息")}</span>
                <textarea name="message" rows="4" maxlength="12000" required ${disabledAttr()}
                  placeholder="${text("What does your week look like?", "说说你这一周的安排…")}">${e(draft)}</textarea></label>
              <div class="lp-chat-actions">
                ${example ? button(text("Use example", "填入示例"), "example") : ""}
                ${retryMessage !== null ? button(text("Retry message", "重试消息"), "retry", "lp-outline") : ""}
                <button class="lp-button lp-primary" type="submit" ${disabledAttr()}>${text("Send", "发送")}</button>
              </div>
            </form>
          </section>
          ${ready || manualReview ? confirmation() : summary()}
        </div></div>`;
      const log = panel.querySelector("[data-chat-log]");
      log.scrollTop = scroll || logTop === undefined ? log.scrollHeight : logTop;
      if (focus) panel.querySelector(focus)?.focus({ preventScroll: focus !== "#lp-chat-review-title" });
    }

    async function send(value, retry = false) {
      const message = value.trim();
      if (!message || busy) return;
      const current = session;
      if (!retry) {
        messages.push({ role: "user", value: message });
        draft = "";
      }
      retryMessage = null;
      issue = null;
      busy = "message";
      draw(null, { scroll: true });
      let reviewAppeared = false;
      try {
        const result = await adapter.handle_chat_message(message, conversation);
        if (current !== session) return;
        if (typeof result?.reply !== "string" || !result.reply.trim()) throw new Error("Missing reply.");
        conversation = result.state;
        fallback = result.provider === "fallback";
        if (result.fields) {
          fields = ready && result.ready ? { ...fields, ...result.fields } : structuredClone(result.fields);
        }
        reviewAppeared = Boolean(result.ready && !ready);
        ready = Boolean(result.ready);
        messages.push({ role: "assistant", value: result.reply });
      } catch {
        if (current !== session) return;
        retryMessage = message;
        issue = { area: "message", message: t("LifePilot couldn’t reply. Retry to send the same message again.", "LifePilot 回复失败。可以重试这条消息。") };
      } finally {
        if (current === session) {
          busy = "";
          draw(reviewAppeared ? "#lp-chat-review-title" : '[name="message"]', { scroll: true });
        }
      }
    }

    async function generate() {
      if ((!ready && !manualReview) || busy) return;
      const current = session;
      const confirmed = structuredClone(fields);
      issue = null;
      busy = "plan";
      draw();
      try {
        const schedule = await adapter.build_confirmed_schedule(conversation, confirmed);
        if (current !== session || !panel?.isConnected) return;
        const message = onPlan(confirmed, schedule);
        if (message) issue = { area: "plan", message };
      } catch {
        if (current !== session) return;
        issue = { area: "plan", message: t("Couldn’t generate your week. Your edits are saved here. Try again.",
          "周计划生成失败。修改仍保留在确认卡片中，请重试。") };
      } finally {
        if (current === session) {
          busy = "";
          draw(".lp-chat-confirm");
        }
      }
    }

    function mount(element) {
      panel = element;
      panel.oninput = (event) => {
        if (event.target.name === "message") draft = event.target.value;
        const path = event.target.dataset.chatField;
        if (!path) return;
        const [key, index, name] = path.split(".");
        if (name) fields[key][index][name] = event.target.value;
        else fields[key] = event.target.value;
      };
      panel.onsubmit = (event) => {
        event.preventDefault();
        if (event.target.dataset.chatForm === "message") {
          return send(event.target.elements.message.value);
        }
        return generate();
      };
      panel.onclick = (event) => {
        const control = event.target.closest("[data-chat-action]");
        if (!control || control.disabled || busy) return;
        const [action, group, index] = control.dataset.chatAction.split(".");
        if (action === "back") onBack();
        else if (action === "review" && fallback) {
          manualReview = true;
          draw("#lp-chat-review-title");
        } else if (action === "retry" && retryMessage !== null) return send(retryMessage, true);
        else if (action === "example") {
          draft = adapter.exampleMessage(conversation);
          draw('[name="message"]');
        } else if (action === "add") {
          fields[group] ??= [];
          fields[group].push({ title: "" });
          draw(`[name="${group}.${fields[group].length - 1}.title"]`);
        } else if (action === "remove") {
          fields[group].splice(Number(index), 1);
          draw(`[data-chat-action="add.${group}"]`);
        }
      };
      draw();
    }

    function reset() {
      session += 1;
      panel = null;
      messages = [];
      conversation = null;
      fields = {};
      ready = false;
      fallback = false;
      manualReview = false;
      draft = "";
      busy = "";
      issue = null;
      retryMessage = null;
    }

    return { mount, reset };
  }

  return { create, importSchedule };
});
