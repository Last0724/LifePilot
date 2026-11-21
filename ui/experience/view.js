(function () {
  "use strict";

  const M = window.LifePilotModel;
  const ICONS = {
    calendar: '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M16 3v4M8 3v4M3 10h18"/>',
    tasks: '<rect x="4" y="4" width="16" height="16" rx="3"/><path d="m8 12 3 3 5-6"/>',
    leaderboard: '<path d="M4 21h16M6 17v-5h4v5m0 0V5h4v12m0 0V9h4v8"/>',
    notifications: '<path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9m-8 12a2 2 0 0 0 4 0"/>',
    settings: '<path d="M12 3v3m0 12v3M3 12h3m12 0h3M5.6 5.6l2.1 2.1m8.6 8.6 2.1 2.1m0-12.8-2.1 2.1m-8.6 8.6-2.1 2.1"/><circle cx="12" cy="12" r="5"/>',
    guru: '<rect x="5" y="3" width="14" height="18" rx="2"/><path d="M9 3v18m3-13h4m-4 4h4"/>',
    points: '<path d="M13 2 4 14h7l-1 8 10-12h-7l1-8Z"/>',
    plus: '<path d="M12 5v14M5 12h14"/>',
    prev: '<path d="m15 18-6-6 6-6"/>',
    next: '<path d="m9 18 6-6-6-6"/>',
    close: '<path d="m6 6 12 12M18 6 6 18"/>',
    check: '<path d="m4 12 5 5L20 6"/>',
    pressure: '<path d="M12 8v5m0 3v1m-8 3h16L12 3 4 20Z"/>',
    play: '<path d="m9 5 11 7-11 7V5Z"/>',
  };
  const icon = (name, cls = "") => `<svg class="lp-icon ${cls}" viewBox="0 0 24 24" fill="none" stroke="currentColor"
    stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICONS[name] || ICONS.notifications}</svg>`;
  const labels = {
    calendar: ["Weekly Calendar", "周历"], tasks: ["My Tasks", "我的任务"],
    leaderboard: ["Leaderboard", "排行榜"], notifications: ["Notifications", "通知"],
    settings: ["Settings", "设置"], points: ["Points History", "积分记录"], guru: ["Guru Templates", "大师模板"],
  };
  const categories = { Study: "学习", Work: "工作", Exercise: "运动", Personal: "个人", Rest: "休息", Other: "其他" };
  const priorities = { High: "高", Medium: "中", Low: "低" };
  const rewardLabels = {
    check: ["Daily schedule check", "每日首次查看周历"], task: ["Task completed", "完成普通任务"],
    high: ["High-priority task completed", "完成高优先级任务"], day: ["All tasks for the day", "当日全部完成"],
    week: ["All tasks for the week", "当周全部完成"],
  };
  const DAY_SHORT = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
  const DAY_CN = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"];
  const escape = (input) => String(input ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[c]);
  const e = escape;
  const cat = (cls = "") => `<svg class="lp-cat ${cls}" viewBox="0 0 22 15" shape-rendering="crispEdges" aria-hidden="true">
    <path class="lp-cat-tail" d="M16 7h1V3h1V2h3v2h-2v3h-1v2h-1v1h-2V8h1Z"/>
    <path d="M2 1h2v1h1v1h2V2h1V1h2v3h1v3h6v2h1v1h-1v4h-2v-3h-1v2h-2v-2H8v2H6v-2H5v3H3v-5H2V8H1V4h1Z"/>
    <path class="lp-cat-eyes" d="M3 5h1v2H3zm4 0h1v2H7z" fill="white"/>
  </svg>`;
  const brand = () => '<span class="lp-wordmark"><span class="lp-logo" aria-hidden="true">✦</span>LifePilot</span>';
  const button = (text, action, cls = "", attrs = "") => `<button type="button" class="lp-button ${cls}" data-action="${action}" ${attrs}>${text}</button>`;
  const routeButton = (name, text, cls = "lp-subtle", attrs = "") => button(text, "navigate", cls, `data-route="${name}" ${attrs}`);

  window.LifePilotViews = function createViews(context) {
    const { state: get, t, view, week, step } = context;
    const renderGuru = window.LifePilotGuruView({ ...context, button, e });
    const tt = (pair) => t(pair[0], pair[1]);
    const lang = () => get().preferences.locale === "zh" ? "zh-CN" : "en-US";
    const date = (day, options = { month: "short", day: "numeric" }) => M.dateAt(day).toLocaleDateString(lang(), options);
    const timestamp = (value) => new Date(value).toLocaleString(lang(), { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
    const userName = (row) => e(row.name || t("You", "你"));
    const taskCategory = (value) => t(value, categories[value]);
    const taskPriority = (value) => t(value, priorities[value]);
    const unread = () => get().notifications.filter((row) => !row.isRead).length;
    const word = (route) => tt(labels[route]);
    const language = () => button(t("中文", "EN"), "language", "lp-language lp-subtle", `aria-label="${t("Switch to Chinese", "切换到英文")}"`);
    const demoBadge = () => `<span class="lp-demo-badge">${t("Demo", "演示")}</span>`;
    const rangeText = () => `${date(week())} – ${date(M.addDays(week(), 6), { month: "short", day: "numeric", year: "numeric" })}`;
    const empty = (text) => `<p class="lp-empty">${text}</p>`;
    const back = () => routeButton("calendar", t("Back to Weekly Calendar", "返回周历"));

    function welcome() {
      return `<main class="lp-welcome">
        <header class="lp-entry-header">${brand()}${language()}</header>
        <section class="lp-welcome-content">
          <div class="lp-welcome-stage">
            <div class="lp-welcome-glow"></div>
            <div class="lp-cat-shadow"></div>
            <button type="button" data-action="cat-jump" class="lp-welcome-cat" aria-label="${t("Play with the cat", "和小猫玩")}">${cat()}</button>
            <p class="lp-welcome-bubble">${t("Hi there! Let’s plan your perfect week!", "你好！一起安排你的一周吧！")}</p>
          </div>
          <h1>${t("Welcome to LifePilot!", "欢迎来到 LifePilot！")}</h1>
          <p class="lp-welcome-description">${t("Your personal productivity companion.", "你的个人效率伙伴。")}</p>
          <form data-form="sign-in" class="lp-welcome-start lp-welcome-sign-in">
            ${field(t("Display name", "昵称"), "name", get().user.name, "text", 'required maxlength="40" autocomplete="nickname"')}
            <button class="lp-button lp-primary" type="submit">${t("Sign in / 登录", "登录 / Sign in")}</button>
            <p class="lp-form-error" role="alert" hidden></p>
            <p class="lp-muted">${t("Sign in with a display name for this local demo.", "输入昵称登录本地演示。")}</p>
          </form>
        </section>
      </main>`;
    }

    function field(label, name, value, type = "text", attrs = "") {
      return `<label class="lp-field"><span>${label}</span><input type="${type}" name="${name}" value="${e(value)}" ${attrs}></label>`;
    }

    function tasksTable(tasks, { setup = false } = {}) {
      if (!tasks.length) return empty(t("No activities yet.", "还没有活动。"));
      return `<div class="lp-task-list">${tasks.map((task) => `
        <div class="lp-task-row">
          <span class="lp-task-dot lp-color-${task.category.toLowerCase()}"></span>
          <span class="lp-task-row-main"><strong>${e(task.title)}</strong><small>${date(task.date)} · ${e(task.startTime)}–${e(task.endTime)} · ${taskCategory(task.category)}${task.repeatWeekly ? t(" · Repeats weekly", " · 每周重复") : ""}</small></span>
          ${setup
            ? button(t("Delete", "删除"), "ask-delete", "lp-subtle", `data-id="${e(task.id)}"`)
            : button(task.completed ? t("Mark Pending", "设为待办") : t("Mark Completed", "标记完成"), "complete", "lp-subtle", `data-id="${e(task.id)}" data-date="${e(task.date)}" data-completed="${!task.completed}"`)}
          ${button(t("Edit", "编辑"), "edit-task", "lp-subtle", `data-id="${e(task.id)}" data-date="${e(task.date)}"`)}
        </div>`).join("")}</div>`;
    }

    function miniCalendar() {
      const days = M.weekDays(week());
      const tasks = M.occurrences(get(), days);
      return `<aside class="lp-card lp-mini"><div class="lp-mini-title"><h2>${t("Schedule Preview", "日程预览")}</h2><span>${rangeText()}</span></div>
        <div class="lp-mini-grid">${days.map((day, index) => `<div class="lp-mini-day"><strong>${t(DAY_SHORT[index], DAY_CN[index])}</strong>
          <span>${M.dateAt(day).getDate()}</span>${tasks.filter((item) => item.date === day).map((item) =>
            `<div class="lp-mini-task lp-color-${item.category.toLowerCase()}" title="${e(item.title)} · ${e(item.startTime)}">${e(item.title)}<small>${e(item.startTime)}</small></div>`).join("")}</div>`).join("")}</div>
        ${tasks.length ? "" : empty(t("Added activities appear here.", "添加的活动会出现在这里。"))}
      </aside>`;
    }

    function setup() {
      const user = get().user;
      const steps = [t("Daily Routine", "日常作息"), t("Add Your Activities", "添加活动"), t("Weekly Goal", "本周目标")];
      let form;
      if (step() === 1) {
        form = `<form data-form="routine" class="lp-form">
          <div class="lp-field-grid">
            ${field(t("Wake-up Time", "起床时间"), "wake", user.routine.wake, "time", "required")}
            ${field(t("Bedtime", "睡觉时间"), "bed", user.routine.bed, "time", "required")}
          </div>
          <fieldset><legend>${t("Preferred Study / Work Hours", "偏好的学习或工作时段")}</legend>
          <div class="lp-field-grid">
            ${field(t("From", "从"), "workStart", user.routine.workStart, "time", "required")}
            ${field(t("To", "到"), "workEnd", user.routine.workEnd, "time", "required")}
          </div></fieldset>
          <p class="lp-form-error" role="alert" hidden></p>
          <div class="lp-actions">${button(t("Back to welcome", "返回欢迎页"), "setup-back", "lp-subtle")}
            <button class="lp-button lp-primary" type="submit">${t("Continue", "继续")}</button></div>
        </form>`;
      } else if (step() === 2) {
        const tasks = [...get().tasks].sort((a, b) => a.date.localeCompare(b.date) || a.startTime.localeCompare(b.startTime));
        form = `<div class="lp-activity-head"><p>${t("Add the plans you already have for this week.", "填入你这周已经有的安排。")}</p>
          ${button(icon("plus") + t("Add Activity", "添加活动"), "add-task", "lp-primary")}</div>
          ${tasksTable(tasks, { setup: true })}
          <p class="lp-form-error" role="alert" hidden></p>
          <div class="lp-actions">${button(t("Back", "返回"), "setup-back", "lp-subtle")}${button(t("Continue", "继续"), "setup-next", "lp-primary")}</div>`;
      } else {
        form = `<form data-form="goal" class="lp-form">
          ${field(t("Main Goal This Week", "本周主要目标"), "goal", user.goal, "text", 'required maxlength="160"')}
          ${field(t("Target Study / Work Hours (optional)", "计划学习或工作时长（可选）"), "target", user.targetHours,
            "number", 'min="0" max="168" step="0.5"')}
          <p class="lp-form-error" role="alert" hidden></p>
          <div class="lp-actions">${button(t("Back", "返回"), "setup-back", "lp-subtle")}
            <button class="lp-button lp-primary" type="submit">${t("Generate My Schedule", "生成我的日程")}</button></div>
        </form>`;
      }
      return `<main class="lp-setup">
        <header class="lp-entry-header">${brand()}${language()}</header>
        <div class="lp-setup-wrap">
          <h1>${t("Let’s Build Your Week", "安排你的一周")}</h1>
          <p class="lp-page-description">${t("Tell us about your schedule, and we’ll organize it for you.", "告诉我们你的安排，我们会帮你整理成周历。")}</p>
          <ol class="lp-steps" aria-label="${t("Schedule setup progress", "日程设置进度")}">${steps.map((name, index) => `<li class="${step() === index + 1 ? "lp-current" : ""}" ${step() === index + 1 ? 'aria-current="step"' : ""}><span>${index + 1}</span>${name}</li>`).join("")}</ol>
          <div class="lp-setup-grid"><section class="lp-card lp-setup-form">
            <div class="lp-setup-step-heading"><h2 tabindex="-1">${steps[step() - 1]}</h2><span>${t(`Step ${step()} of ${steps.length}`, `第 ${step()} 步 / 共 ${steps.length} 步`)}</span></div>
            ${form}</section>${miniCalendar()}</div>
        </div>
      </main>`;
    }

    function generating(ready) {
      return `<main class="lp-welcome lp-generating">
        <header class="lp-entry-header">${brand()}</header>
        <section class="lp-welcome-content" aria-live="polite">
          ${cat("lp-cat-generate")}<h1>${ready ? t("Your schedule is ready!", "你的日程准备好了！") : t("Organizing your week...", "正在整理你的一周…")}</h1>
        </section>
      </main>`;
    }

    function taskDialog(task, occurrence, initialDate) {
      const editing = Boolean(task);
      const item = task || { title: "", category: "Study", date: initialDate, startTime: "09:00", endTime: "10:00", priority: "Medium", repeatWeekly: false };
      const dayOptions = M.weekDays(week()).map((day, index) => `<option value="${e(day)}" ${day === item.date ? "selected" : ""}>${t(M.DAYS[index], DAY_CN[index])}</option>`).join("");
      const selectField = (text, name, values, selected, translate) => `<label class="lp-field"><span>${text}</span><select name="${name}" required>${values.map((value) => `<option value="${value}" ${selected === value ? "selected" : ""}>${translate(value)}</option>`).join("")}</select></label>`;
      const setupMode = view() === "setup";
      return `
        <form data-form="task" class="lp-form" data-id="${e(item.id || "")}">
          ${field(t("Task Name", "任务名称"), "title", item.title, "text", 'required maxlength="90" autofocus')}
          <div class="lp-field-grid">
            ${selectField(t("Category", "类别"), "category", M.CATEGORIES, item.category, taskCategory)}
            ${selectField(t("Priority", "优先级"), "priority", M.PRIORITIES, item.priority, taskPriority)}
          </div>
          ${setupMode ? `<label class="lp-field"><span>${t("Day of Week", "星期")}</span><select name="date" required>${dayOptions}</select></label>`
            : field(t(item.repeatWeekly ? "Series start date" : "Date", item.repeatWeekly ? "重复任务开始日期" : "日期"), "date", item.date, "date", "required")}
          <div class="lp-field-grid">
            ${field(t("Start Time", "开始时间"), "startTime", item.startTime, "time", "required")}
            ${field(t("End Time", "结束时间"), "endTime", item.endTime, "time", "required")}
          </div>
          <label class="lp-check"><input type="checkbox" name="repeatWeekly" ${item.repeatWeekly ? "checked" : ""}>${t("Repeat Weekly", "每周重复")}</label>
          ${editing && item.repeatWeekly && !setupMode ? `<p class="lp-muted">${t("Edits apply to the series. Completion applies to ${date(occurrence)} only.", "修改适用于整个重复系列。完成状态仅适用于 " + date(occurrence) + "。")}</p>` : ""}
          <p class="lp-form-error" role="alert" hidden></p>
          ${editing && !setupMode ? `<div class="lp-dialog-tools">${button(get().completions[occurrence === item.date ? item.id : item.id + "@" + occurrence]
            ? t("Mark Pending", "设为待办") : t("Mark Completed", "标记完成"),
            "complete", "lp-outline", `data-id="${e(item.id)}" data-date="${e(occurrence)}" data-completed="${!get().completions[occurrence === item.date ? item.id : item.id + "@" + occurrence]}"`)}
            ${button(t(item.repeatWeekly ? "Delete series" : "Delete Task", item.repeatWeekly ? "删除整个系列" : "删除任务"), "ask-delete", "lp-danger-text", `data-id="${e(item.id)}"`)}</div>` : ""}
          <div class="lp-actions">${button(t("Cancel", "取消"), "close-dialog", "lp-subtle")}
            <button type="submit" class="lp-button lp-primary">${editing ? t("Save changes", "保存修改") : setupMode ? t("Add Activity", "添加活动") : t("Add Task", "添加任务")}</button>
          </div>
        </form>`;
    }

    function pointsPanel() {
      const xp = M.totalXP(get());
      const level = M.level(xp);
      const progress = M.progress(xp);
      return `<section class="lp-card lp-points" aria-label="${t("Productivity Points", "效率积分")}">
        <div class="lp-points-title">${icon("points")}<h2>${t("Productivity Points", "效率积分")}</h2></div>
        <div class="lp-xp" data-xp>${xp} <span>XP</span></div>
        <strong>${t("Level", "等级")} ${level} · ${level === 1 ? t("Getting Started", "初露锋芒") : level === 2 ? t("Rising Achiever", "稳步前进") : t("Productivity Pro", "效率达人")}</strong>
        <div class="lp-progress" role="progressbar" aria-label="${t("Progress to next level", "升级进度")}" aria-valuemin="0" aria-valuemax="200" aria-valuenow="${progress}">
          <span style="width:${progress / 2}%"></span>
        </div>
        <div class="lp-points-footer"><span>${t(`${200 - progress} XP to next level`, `距离下一级还差 ${200 - progress} XP`)}</span>
          ${button(word("points"), "points-history", "lp-subtle")}</div>
      </section>`;
    }

    function rankPanel() {
      const ranks = M.ranking(get());
      const mine = ranks.find((entry) => !entry.simulated);
      return `<section class="lp-card lp-panel">
        <div class="lp-panel-title"><h2>${t("Productivity Leaderboard", "效率排行榜")}</h2>${demoBadge()}</div>
        <ol class="lp-mini-ranks">${ranks.slice(0, 3).map((row) => `<li><span class="lp-rank-symbol">${row.rank}</span><span>${userName(row)}</span><strong>${row.xp} XP</strong></li>`).join("")}</ol>
        <div class="lp-panel-footer"><strong data-rank>${t("Your Rank", "你的排名")} <span>#${mine.rank}</span></strong>
        ${routeButton("leaderboard", t("View Leaderboard", "查看排行榜"))}</div>
      </section>`;
    }

    function noticeCard(item, compact = false) {
      const graphic = item.type === "cat" ? cat("lp-cat-tiny") : icon(({ xp: "points", rank: "leaderboard", pressure: "pressure" })[item.type] || "calendar");
      return `<div class="lp-notice ${item.isRead ? "" : "lp-unread"}"><span class="lp-notice-icon lp-notice-${item.type}">${graphic}</span>
          <div><strong>${e(tt(item.title))}</strong><p>${e(tt(item.message))}</p>
          <time datetime="${e(item.timestamp)}">${e(timestamp(item.timestamp))}</time></div>
          ${compact || item.isRead ? "" : button(t("Mark as Read", "标为已读"), "read-notice", "lp-subtle", `data-id="${e(item.id)}"`)}
        </div>`;
    }

    function notifPanel() {
      const state = get();
      const busy = state.demo.enabled && state.demo.index < M.DEMO_NOTICES.length;
      return `<section class="lp-card lp-panel">
        <div class="lp-panel-title"><h2>${word("notifications")}</h2><span class="lp-count" data-unread>${unread()} ${t("Unread", "未读")}</span></div>
        <div class="lp-recent-notices">${state.notifications.slice(0, 3).map((item) => noticeCard(item, true)).join("")
          || empty(t("You’re all caught up.", "你已看完所有通知。"))}</div>
        <div class="lp-panel-footer">${routeButton("notifications", t("View All", "查看全部"))}
          ${button(busy ? t("Restart Demo", "重播演示") : t(state.demo.enabled ? "Replay Demo" : "Start Demo", state.demo.enabled ? "重播演示" : "启动演示"),
            "start-demo", "lp-subtle")}</div>
      </section>`;
    }

    function calendar() {
      const days = M.weekDays(week());
      const tasks = M.occurrences(get(), days);
      const today = M.localDate(new Date());
      return `<section class="lp-calendar-page">
        <div class="lp-page-heading"><div><h1>${t("My Weekly Schedule", "我的每周日程")}</h1>
          <p class="lp-page-description">${e(rangeText())}</p></div>
          ${button(icon("plus") + t("Add Task", "添加任务"), "add-task", "lp-primary")}
        </div>
        <div class="lp-calendar-toolbar"><div class="lp-stat-list">
          <span><strong data-total-tasks>${tasks.length}</strong> ${t("Total Tasks", "全部任务")}</span>
          <span><strong data-completed-tasks>${tasks.filter((task) => task.completed).length}</strong> ${t("Completed Tasks", "已完成")}</span>
          <span><strong>${M.totalXP(get())}</strong> ${t("Total XP", "总积分")}</span>
        </div><div class="lp-calendar-nav">
          ${button(icon("prev"), "prev-week", "lp-outline lp-icon-button", `aria-label="${t("Previous week", "上一周")}"`)}
          ${button(t("Today", "今天"), "today", "lp-outline")}
          ${button(icon("next"), "next-week", "lp-outline lp-icon-button", `aria-label="${t("Next week", "下一周")}"`)}
        </div></div>
        <div class="lp-calendar-scroll" tabindex="0" aria-label="${t("Weekly calendar grid", "周历网格")}">
          <div class="lp-calendar-board">
            <div class="lp-calendar-days"><span class="lp-time-head"></span>
              ${days.map((day, i) => `<div class="lp-calendar-day-head ${day === today ? "lp-today" : ""}">
                 <span>${t(M.DAYS[i], DAY_CN[i])}</span><strong>${M.dateAt(day).getDate()}</strong>
              </div>`).join("")}
            </div>
            <div class="lp-calendar-body">
              <div class="lp-time-axis">${Array.from({ length: 25 }, (_, hour) =>
                `<span style="--hour-index:${hour}">${String(hour).padStart(2, "0")}:00</span>`).join("")}</div>
              ${days.map((day) => `<div class="lp-day-track">${tasks.filter((task) => task.date === day).map((task) => {
                const start = M.minutes(task.startTime);
                const span = M.minutes(task.endTime) - start;
                return `<button type="button" class="lp-event lp-color-${task.category.toLowerCase()} ${task.completed ? "lp-completed" : ""}"
                  style="--minute-start:${start};--minute-span:${span}" data-action="edit-task" data-id="${e(task.id)}" data-date="${e(day)}"
                  aria-label="${e(task.title)} · ${e(task.startTime)}–${e(task.endTime)} · ${task.completed ? t("Completed", "已完成") : t("Pending", "待办")}"
                  title="${e(task.title)} · ${e(task.startTime)}–${e(task.endTime)}"><strong>${task.completed ? "✓ " : ""}${e(task.title)}</strong>
                    <small>${e(task.startTime)}–${e(task.endTime)}</small>${span >= 45 ? `<span>${taskCategory(task.category)} · ${task.completed ? t("Completed", "已完成") : t("Pending", "待办")}</span>` : ""}</button>`;
              }).join("")}</div>`).join("")}
            </div>
          </div>
        </div>
        <div class="lp-legend">${M.CATEGORIES.map((category) => `<span><i class="lp-task-dot lp-color-${category.toLowerCase()}"></i>${taskCategory(category)}</span>`).join("")}</div>
      </section>`;
    }

    function leaderboard() {
      const rows = M.ranking(get());
      return `<section class="lp-feature"><div class="lp-page-heading"><div><h1>${word("leaderboard")}</h1>
        <p class="lp-page-description">${t("Demo Leaderboard — Simulated Competitors", "演示排行榜 · 模拟竞争者")}</p></div>${back()}</div>
        <div class="lp-card lp-table-wrap"><table><thead><tr>${[
          t("Rank", "名次"), t("User", "用户"), t("Total XP", "总积分"), t("Completed Tasks", "已完成任务"), t("Rank Change", "名次变化"),
        ].map((title) => `<th scope="col">${title}</th>`).join("")}</tr></thead><tbody>
        ${rows.map((row) => `<tr class="${row.simulated ? "" : "lp-player-row"}" ${row.simulated ? "" : 'data-player-row'}><td>#${row.rank}</td>
          <td><strong>${userName(row)}</strong>${row.simulated ? "" : ` <span>${t("(you)", "（你）")}</span>`}</td>
          <td>${row.xp}</td><td>${row.completedTasks}</td><td class="${row.change < 0 ? "lp-negative" : row.change > 0 ? "lp-positive" : ""}">${row.change ? (row.change > 0 ? "+" : "") + row.change : "—"}</td></tr>`).join("")}</tbody></table></div>
      </section>`;
    }

    function notifications(filter) {
      const all = get().notifications;
      const visible = filter === "unread" ? all.filter((item) => !item.isRead) : all;
      return `<section class="lp-feature">
        <div class="lp-page-heading"><div><h1>${word("notifications")}</h1><p class="lp-page-description" data-unread>${unread()} ${t("Unread", "未读")}</p></div>${back()}</div>
        <div class="lp-card lp-notification-center">
          <div class="lp-inline-actions">
            ${button(t("All", "全部"), "filter-notices", filter === "all" ? "lp-selected" : "lp-subtle", 'data-filter="all"')}
            ${button(t("Unread", "未读"), "filter-notices", filter === "unread" ? "lp-selected" : "lp-subtle", 'data-filter="unread"')}
            ${button(t("Mark All as Read", "全部标为已读"), "read-all", "lp-subtle", unread() ? "" : "disabled")}
            ${button(t("Clear Notifications", "清空通知"), "ask-clear", "lp-danger-text", all.length ? "" : "disabled")}
          </div>
          ${visible.map((item) => noticeCard(item)).join("") || empty(t("No notifications here.", "这里没有通知。"))}
        </div>
      </section>`;
    }

    function settings() {
      const state = get();
      return `<section class="lp-feature">
        <div class="lp-page-heading"><h1>${word("settings")}</h1>${back()}</div>
        <section class="lp-card lp-settings">
          <h2>${t("Your profile", "个人资料")}</h2>
          <form class="lp-profile-form" data-form="profile">
            ${field(t("Display name", "显示名称"), "name", state.user.name, "text", 'maxlength="40"')}
            <button class="lp-button lp-outline" type="submit">${t("Save name", "保存名称")}</button>
          </form>
          <dl class="lp-profile-info"><div><dt>${t("This week’s goal", "本周目标")}</dt><dd>${e(state.user.goal)}</dd></div>
            <div><dt>${t("Daily routine", "日常作息")}</dt><dd>${e(state.user.routine.wake)}–${e(state.user.routine.bed)}</dd></div>
            <div><dt>${t("Work hours", "工作时段")}</dt><dd>${e(state.user.routine.workStart)}–${e(state.user.routine.workEnd)}</dd></div>
            ${state.user.targetHours === null ? "" : `<div><dt>${t("Weekly hours target", "本周计划时长")}</dt><dd>${e(state.user.targetHours)} h</dd></div>`}
          </dl>
        </section>
        <section class="lp-card lp-settings">
          <h2>${word("notifications")}</h2>
          <label class="lp-check"><input type="checkbox" data-pref="paused" ${state.preferences.paused ? "checked" : ""}>${t("Pause Notifications", "暂停通知")}</label>
          <label class="lp-check"><input type="checkbox" data-pref="optional" ${state.preferences.optional ? "checked" : ""}>${t("Show optional reminders", "接收非必要提醒")}</label>
        </section>
        <section class="lp-card lp-settings">
          <div class="lp-panel-title"><h2>${t("Demo Mode", "演示模式")}</h2>${demoBadge()}</div>
          <p>${t("Simulated competitors and in-site notifications. Your schedule and points are stored in this browser.", "竞争者和通知为站内模拟。日程和积分保存在当前浏览器。")}</p>
          <div class="lp-inline-actions">
            ${button(t("Replay Notification Demo", "重播通知演示"), "start-demo", "lp-outline")}
            ${state.demo.enabled ? button(t("Stop Demo", "停止演示"), "stop-demo", "lp-subtle") : ""}
            ${button(t("Reset Demo", "重置演示"), "ask-reset", "lp-danger-text")}
          </div>
          <a class="lp-legacy-link" href="?view=classic">${t("Classic AI consultation and demo features", "旧版 AI 咨询与演示功能")}</a>
        </section>
      </section>`;
    }

    function pointsHistory() {
      return `<div class="lp-points-history">${pointsPanel()}<div class="lp-history-list">
        ${[...get().points].reverse().map((entry) => `<div class="lp-history-row">
          <strong>${e(tt(rewardLabels[entry.actionType]))}</strong><span>${e(entry.taskTitle || timestamp(entry.timestamp))}</span><b>+${entry.points} XP</b>
          ${entry.taskTitle ? `<time datetime="${e(entry.timestamp)}">${e(timestamp(entry.timestamp))}</time>` : ""}
        </div>`).join("") || empty(t("No points yet.", "还没有积分记录。"))}</div></div>`;
    }

    function dashboard(filter) {
      const state = get();
      const current = view();
      const nav = ["calendar", "tasks", "leaderboard", "notifications", "guru", "settings"];
      let content = "";
      if (current === "calendar") content = calendar();
      if (current === "tasks") content = `<section class="lp-feature"><div class="lp-page-heading">
        <div><h1>${word("tasks")}</h1><p class="lp-page-description">${rangeText()}</p></div>
        ${button(icon("plus") + t("Add Task", "添加任务"), "add-task", "lp-primary")}</div>
        <div class="lp-task-page-toolbar">${back()}<div class="lp-calendar-nav">
          ${button(icon("prev"), "prev-week", "lp-outline lp-icon-button", `aria-label="${t("Previous week", "上一周")}"`)}
          ${button(t("Today", "今天"), "today", "lp-outline")}
          ${button(icon("next"), "next-week", "lp-outline lp-icon-button", `aria-label="${t("Next week", "下一周")}"`)}
        </div></div><div class="lp-card lp-task-page-list">${tasksTable(M.occurrences(state, M.weekDays(week())))}</div></section>`;
      if (current === "leaderboard") content = leaderboard();
      if (current === "notifications") content = notifications(filter);
      if (current === "guru") content = renderGuru();
      if (current === "settings") content = settings();
      return `<div class="lp-app-shell ${current === "calendar" ? "lp-with-panel" : ""}">
        <aside class="lp-sidebar"><div class="lp-side-brand">${brand()}${language()}</div>
          <nav aria-label="${t("Main navigation", "主导航")}">${nav.map((route) => routeButton(route,
            icon(route) + `<span>${word(route)}</span>` + (route === "notifications" && unread() ? `<small>${unread()}</small>` : ""),
            `lp-nav-link ${route === current ? "lp-selected" : ""}`, route === current ? 'aria-current="page"' : "")).join("")}</nav>
          <div class="lp-side-user">${cat("lp-cat-tiny")}<span>${userName(state.user)}</span>${demoBadge()}</div>
        </aside>
        <main class="lp-central">${content}</main>
        ${current === "calendar" ? `<aside class="lp-productivity" aria-label="${t("Productivity panel", "效率面板")}">${pointsPanel()}${rankPanel()}${notifPanel()}</aside>` : ""}
      </div>`;
    }

    function noticeToast(item) {
      return `<div class="lp-toast"><button type="button" class="lp-toast-main" data-action="notice-target" data-id="${e(item.id)}">
        ${item.type === "cat" ? cat("lp-cat-tiny") : icon(({ xp: "points", rank: "leaderboard", pressure: "pressure" })[item.type] || "calendar")}
        <span><strong>${e(tt(item.title))}</strong><small>${e(tt(item.message))}</small></span></button>
        ${button(icon("close"), "dismiss-toast", "lp-icon-button lp-subtle", `aria-label="${t("Dismiss notification", "关闭通知")}" data-id="${e(item.id)}"`)}</div>`;
    }

    function errorText(error) {
      const messages = {
        displayName: ["Enter your display name to sign in.", "请输入昵称后再登录。"],
        title: [ "Enter a task name.", "请输入任务名称。" ], choices: ["Choose a category and priority.", "请选择类别和优先级。"],
        date: ["Choose a valid date.", "请选择有效日期。"], times: ["End time must be later than start time.", "结束时间必须晚于开始时间。"],
        overlap: [`This time overlaps with “${error.title}”. Choose a different time.`, `此时段与「${error.title}」重叠，请更换时间。`],
        noTasks: ["Add at least one activity to continue.", "请至少添加一个活动再继续。"],
        routine: ["Check your routine and choose work hours with an end after the start.", "请核对作息，工作结束时间必须晚于开始时间。"],
        goal: ["Enter your main goal for the week.", "请输入本周主要目标。"],
        target: ["Enter a weekly target between 0 and 168 hours.", "每周目标时长应在 0 到 168 小时之间。"],
      };
      return tt(messages[error.code]);
    }

    return {
      welcome, setup, generating, dashboard, taskDialog, pointsHistory, noticeToast,
      button, cat, icon, e, errorText,
      editTitle: (editing) => editing ? t("Edit Task", "编辑任务") :
        view() === "setup" ? t("Add Activity", "添加活动") : t("Add Task", "添加任务"),
    };
  };
})();
