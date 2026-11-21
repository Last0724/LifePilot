function mountLifePilot(root) {
  "use strict";

  if (!root || root.dataset.mounted) return;
  root.dataset.mounted = "true";
  const surface = root.querySelector("[data-lp-surface]");
  const toasts = root.querySelector("[data-lp-toasts]");
  const catLayer = root.querySelector("[data-lp-cat]");
  const dialogue = root.querySelector("dialog");
  const flash = root.querySelector("[data-lp-flash]");
  const audio = root.querySelector("[data-lp-guru-audio]");
  const M = window.LifePilotModel;
  const G = window.LifePilotGuru;
  const key = "lifepilot.weekly.v1";
  let storageFault = false;

  function read() {
    try {
      const saved = JSON.parse(localStorage.getItem(key) || "null");
      return saved?.version === 1 ? saved : null;
    } catch {
      storageFault = true;
      return null;
    }
  }

  let data = read() || M.newState();
  let route = "welcome";
  let week = M.monday(M.localDate(new Date()));
  let step = 1;
  let filter = "all";
  let ready = false;
  let guruSelection = null;
  let guruAudioStatus = "";
  let generationTimers = [];
  let catText = null;
  let catOpen = false;
  let ticking = null;
  let promotionAfter = null;
  let toastQueue = [];
  const shown = new Map();
  const abort = new AbortController();
  const signal = abort.signal;
  const t = (en, zh) => data.preferences.locale === "zh" ? zh : en;
  const V = window.LifePilotViews({
    state: () => data, t, view: () => route, week: () => week, step: () => step,
    selection: () => guruSelection, audioStatus: () => guruAudioStatus,
  });
  const initialized = () => data.user.onboardingCompleted && route !== "generating";
  const toastRoute = () => route === "calendar" || route === "guru";

  function save(state) {
    try {
      localStorage.setItem(key, JSON.stringify(state));
      storageFault = false;
    } catch {
      storageFault = true;
    }
    data = state;
  }

  function change(operation, { redraw = true } = {}) {
    const next = (storageFault ? null : read()) || JSON.parse(JSON.stringify(data));
    const previous = new Set(next.notifications.map((item) => item.id));
    const result = operation(next, new Date()) || {};
    if (!result.updated) return result;
    save(next);
    if (redraw) render();
    if (toastRoute()) {
      const fresh = data.notifications.filter((item) => !previous.has(item.id)).reverse();
      toastQueue.push(...fresh);
      showNextToast();
    }
    feedback(result);
    return result;
  }

  function syncTimer() {
    const shouldTick = root.isConnected && route === "calendar" && initialized() &&
      !data.preferences.paused && !document.hidden;
    if (shouldTick && ticking === null) {
      ticking = window.setInterval(() => {
        change(M.tick);
        if (promotionAfter && Date.now() >= promotionAfter && !dialogue.open && data.preferences.optional) {
          promotionAfter = null;
          showNextCoursePromotion(M.localDate(new Date()));
        }
      }, 1000);
    } else if (!shouldTick && ticking !== null) {
      window.clearInterval(ticking);
      ticking = null;
    }
  }

  function showNextToast() {
    if (!toastRoute() || data.preferences.paused) return;
    while (shown.size < 3 && toastQueue.length) {
      const item = toastQueue.shift();
      if (item.optional && !data.preferences.optional) continue;
      const wrapper = document.createElement("div");
      wrapper.innerHTML = V.noticeToast(item);
      const el = wrapper.firstElementChild;
      toasts.append(el);
      shown.set(item.id, { el, timer: window.setTimeout(() => dismissToast(item.id), 7300) });
    }
  }

  function dismissToast(id) {
    const toast = shown.get(id);
    if (!toast || toast.leaving) return;
    window.clearTimeout(toast.timer);
    toast.el.classList.add("lp-toast-out");
    toast.leaving = true;
    toast.timer = window.setTimeout(() => {
      toast.el.remove();
      shown.delete(id);
      showNextToast();
    }, 220);
  }

  function clearToasts() {
    for (const toast of shown.values()) window.clearTimeout(toast.timer);
    shown.clear();
    toastQueue = [];
    toasts.replaceChildren();
  }

  function updateCat() {
    if (!initialized()) {
      catLayer.textContent = "";
      return;
    }
    const message = catText || [
      "Hi! I’m here if you want to check how your week is going.",
      "嗨，想看看这一周过得怎么样，随时来找我。",
    ];
    catLayer.innerHTML = `${catOpen ? `<p class="lp-cat-message" aria-live="polite">${V.e(t(...message))}</p>` : ""}
      ${V.button(V.cat(), "cat-toggle", "lp-cat-fab", `aria-label="${t("Cat Assistant", "小猫助手")}" aria-expanded="${catOpen}"`)}`;
    if (catOpen) catLayer.querySelector("svg")?.animate?.(
      [{ transform: "translateY(0)" }, { transform: "translateY(-4px)" }, { transform: "translateY(0)" }],
      { duration: matchMedia("(prefers-reduced-motion: reduce)").matches ? 0 : 330 },
    );
  }

  function feedback(result) {
    const increments = [
      [result.taskXP, t("Task", "任务")],
      [result.dayXP, t("Daily bonus", "当日奖励")],
      [result.weekXP, t("Weekly bonus", "当周奖励")],
    ].filter(([points]) => points);
    if (increments.length) {
      flash.innerHTML = increments.map(([points, label]) =>
        `<span>+${points} XP <small>${label}</small></span>`).join("");
    }
    if (result.levelUp) catText = ["Wow! You’re leveling up!", "太棒了，你升级了！"];
    else if (result.rankDelta < 0) catText = ["Oh no! A simulated competitor just passed you!", "糟糕，有模拟竞争者超过你了！"];
    else if (result.completed && result.taskXP) catText = ["Great job! You earned more XP!", "做得好！你又获得了积分！"];
    else if (result.catNudge) catText = ["So many things to keep up with!", "要关注的事可真多！"];
    else return;
    catOpen = true;
    updateCat();
  }

  function render({ resetScroll = false } = {}) {
    const grid = surface.querySelector(".lp-calendar-scroll");
    const scroll = grid && !resetScroll ? [grid.scrollLeft, grid.scrollTop] : null;
    const oldProgress = surface.querySelector(".lp-progress span")?.style.width;
    const lastRoutineScroll = surface.querySelector(".lp-guru-timeline-scroll")?.scrollTop || 0;
    const focus = document.activeElement?.closest?.("[data-action]");
    const oldAction = focus && surface.contains(focus) ? focus.dataset : null;
    root.lang = data.preferences.locale === "zh" ? "zh-CN" : "en";
    let markup = "";
    if (route === "welcome") markup = V.welcome();
    else if (route === "setup") markup = V.setup();
    else if (route === "generating") markup = V.generating(ready);
    else markup = V.dashboard(filter);
    surface.innerHTML = `${storageFault
      ? `<p class="lp-storage-warning" role="alert">${t("Browser storage is unavailable. Changes may be lost after reload.", "浏览器存储不可用，刷新后可能丢失更改。")}</p>` : ""}${markup}`;

    const nextGrid = surface.querySelector(".lp-calendar-scroll");
    if (nextGrid) {
      nextGrid.scrollLeft = scroll?.[0] || 0;
      nextGrid.scrollTop = scroll?.[1] ?? (6 * parseFloat(getComputedStyle(root).getPropertyValue("--hour")));
    }
    const bar = surface.querySelector(".lp-progress span");
    if (bar && oldProgress && oldProgress !== bar.style.width && !matchMedia("(prefers-reduced-motion: reduce)").matches) {
      bar.animate([{ width: oldProgress }, { width: bar.style.width }], { duration: 400, easing: "ease-out" });
    }
    const timeline = surface.querySelector(".lp-guru-timeline-scroll");
    if (timeline) {
      timeline.scrollTop = lastRoutineScroll;
      const active = timeline.querySelector('[aria-current="step"]');
      if (active && active.offsetTop + active.offsetHeight > timeline.scrollTop + timeline.clientHeight) {
        timeline.scrollTop = active.offsetTop - 12;
      }
    }
    if (oldAction) {
      const replacement = Array.from(surface.querySelectorAll("[data-action]")).find((el) =>
        Object.entries(oldAction).every(([name, value]) => el.dataset[name] === value));
      replacement?.focus({ preventScroll: true });
    }
    updateCat();
    syncTimer();
  }

  function navigate(nextRoute) {
    const changedRoute = route !== nextRoute;
    if (changedRoute) {
      clearToasts();
      catOpen = false;
      if (route === "guru") stopGuruVoice();
    }
    route = nextRoute;
    if (route === "calendar") {
      if (changedRoute || !promotionAfter) promotionAfter = Date.now() + 3500;
      change(M.openDashboard, { redraw: false });
    }
    render({ resetScroll: true });
    if (changedRoute) surface.scrollIntoView({ block: "start" });
  }

  function showDialog(title, content) {
    dialogue.innerHTML = `<div class="lp-dialog-heading"><h2 id="lp-experience-dialog-title">${V.e(title)}</h2>
      ${V.button(V.icon("close"), "close-dialog", "lp-subtle lp-icon-button", `aria-label="${t("Close dialog", "关闭对话框")}"`)}</div>${content}`;
    if (!dialogue.open) dialogue.showModal();
    dialogue.querySelector("[autofocus]")?.focus();
  }

  function confirm(title, message, action, details = "") {
    showDialog(title, `<p class="lp-confirm-copy">${V.e(message)}</p>
      <div class="lp-actions">${V.button(t("Cancel", "取消"), "close-dialog", "lp-subtle")}
      ${V.button(V.e(title), action, "lp-danger", details)}</div>`);
  }

  function showCoursePromotion(id, fromFreePlan = false) {
    const template = G.TEMPLATES[id];
    const copy = G.COURSE_PROMOTIONS[id];
    if (!template || !copy) return;
    const title = fromFreePlan ? t("Free plan ad · Demo", "免费版广告 · 演示") : t("Course promotion · Demo", "课程推广 · 演示");
    showDialog(title, `<div class="lp-course-promotion">
      <p class="lp-course-guru">${V.e(t(...template.guru))}</p>
      <h3>${V.e(t(...template.title))}</h3>
      <p>${V.e(t(...copy))}</p>
      <strong class="lp-course-price">${V.e(t(...template.price))}</strong>
    </div><div class="lp-actions">
      ${V.button(t("Maybe later", "以后再说"), "close-dialog", "lp-subtle")}
      ${V.button(t("View course", "查看课程"), "guru-ad-details", "lp-primary", `data-template="${id}"`)}
    </div>`);
  }

  function showNextCoursePromotion(day) {
    const result = change((state) => G.takeCoursePromotion(state, day), { redraw: false });
    if (result.course) showCoursePromotion(result.course);
  }

  function openGuruTemplate(id) {
    if (!Object.hasOwn(G.TEMPLATES, id)) return;
    if (dialogue.open) dialogue.close();
    stopGuruVoice();
    clearToasts();
    guruSelection = id;
    navigate("guru");
  }

  function editTask(id, day) {
    const task = data.tasks.find((item) => item.id === id);
    if (id && !task) return;
    const today = M.localDate(new Date());
    const suggestedDate = route !== "setup" && M.monday(today) === week ? today : week;
    showDialog(V.editTitle(task), V.taskDialog(task, day || task?.date, suggestedDate));
  }

  function showError(error, owner = surface) {
    const line = owner.querySelector(".lp-form-error");
    if (!line) return;
    line.textContent = V.errorText(error);
    line.hidden = false;
  }

  function goalDraft(values) {
    return { goal: values.goal.trim(), targetHours: values.target === "" ? null : Number(values.target) };
  }

  function saveSetupDraft() {
    const form = surface.querySelector("[data-form=routine], [data-form=goal]");
    if (!form) return;
    const values = Object.fromEntries(new FormData(form));
    const routine = form.dataset.form === "routine";
    if (routine && M.routineError(values)) return;
    change((state) => {
      Object.assign(state.user, routine ? { routine: values } : goalDraft(values));
      return { updated: true };
    }, { redraw: false });
  }

  function openSetupStep(number) {
    step = number;
    navigate("setup");
    surface.querySelector(".lp-setup-step-heading h2").focus({ preventScroll: true });
  }

  function clearGeneration() {
    generationTimers.forEach(window.clearTimeout);
    generationTimers = [];
    ready = false;
  }

  function stopGuruVoice(status = "") {
    if (audio.hasAttribute("src")) {
      audio.pause();
      audio.removeAttribute("src");
      audio.load();
    }
    guruAudioStatus = status;
  }

  function playGuruVoice() {
    const voice = window.LifePilotGuruMedia.sleep[data.preferences.locale === "zh" ? "zh" : "en"];
    stopGuruVoice();
    audio.src = voice;
    guruAudioStatus = "playing";
    render();
    audio.play().catch(() => {
      if (audio.getAttribute("src") !== voice || guruAudioStatus !== "playing") return;
      guruAudioStatus = "blocked";
      render();
    });
  }

  audio.addEventListener("ended", () => {
    guruAudioStatus = "ended";
    if (route === "guru") render();
  }, { signal });

  function guruAction(action) {
    if (!guruSelection) return;
    if (action === "ask-unlock") {
      const premium = guruSelection === "hyper";
      confirm(premium ? t("Activate demo Premium?", "启用演示 Premium？") : t("Unlock demo tips?", "解锁演示技巧？"),
        premium
          ? t("The listed ¥199/month price is fictional. This button unlocks the routine inside the demo.", "¥199／月是演示定价。按钮只解锁这里的模板。")
          : t("This button simulates a paid unlock inside LifePilot.", "该按钮在 LifePilot 站内模拟付费解锁。"),
        "guru-unlock");
      return;
    }
    const outcome = change((state, now) => {
      const result = G.update(state, guruSelection, action);
      for (const item of result.guruAlerts || []) M.notify(state, item.type, item.title, item.message, "guru", now, true);
      return result;
    });
    if (outcome.guruStopVoice) {
      stopGuruVoice();
      render();
    }
    if (outcome.guruAd) showCoursePromotion("hyper", true);
    if (outcome.guruVoice) playGuruVoice();
  }

  function reset() {
    dialogue.close();
    clearGeneration();
    clearToasts();
    stopGuruVoice();
    guruSelection = null;
    const next = M.newState();
    next.preferences.locale = data.preferences.locale;
    save(next);
    catOpen = false;
    catText = null;
    flash.replaceChildren();
    week = M.monday(M.localDate(new Date()));
    step = 1;
    filter = "all";
    navigate("welcome");
  }

  function beginGeneration() {
    route = "generating";
    render();
    const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
    generationTimers.push(window.setTimeout(() => {
      ready = true;
      render();
    }, reduced ? 40 : 850));
    generationTimers.push(window.setTimeout(() => {
      clearGeneration();
      navigate("calendar");
    }, reduced ? 250 : 1550));
  }

  function toastClicked(id) {
    const item = data.notifications.find((notice) => notice.id === id);
    if (!item) return;
    readNotice(id);
    dismissToast(id);
    if (item.route === "points") showDialog(t("Points History", "积分记录"), V.pointsHistory());
    else navigate(item.route);
  }

  function readNotice(id) {
    change((state) => {
      state.notifications.forEach((item) => {
        if (!id || item.id === id) item.isRead = true;
      });
      return { updated: true };
    });
  }

  root.addEventListener("submit", (event) => {
    const form = event.target;
    if (!form.dataset.form) return;
    event.preventDefault();
    const values = Object.fromEntries(new FormData(form));
    const type = form.dataset.form;
    if (type === "sign-in") {
      const name = values.name.trim();
      if (!name) return showError({ code: "displayName" }, form);
      change((state) => {
        state.user.name = name;
        return { updated: true };
      }, { redraw: false });
      if (data.user.onboardingCompleted) navigate("calendar");
      else openSetupStep(1);
    }

    if (type === "routine") {
      if (M.routineError(values)) return showError({ code: "routine" }, form);
      change((state) => {
        state.user.routine = values;
        return { updated: true };
      }, { redraw: false });
      openSetupStep(2);
    }

    if (type === "task") {
      const result = change((state, now) => M.saveTask(state, {
        ...values, id: form.dataset.id, repeatWeekly: values.repeatWeekly === "on",
      }, now));
      if (result.error) return showError(result.error, form);
      dialogue.close();
    }

    if (type === "goal") {
      const result = change((state) => {
        const user = { ...state.user, ...goalDraft(values) };
        const error = M.scheduleError(state, user);
        if (error) return { error };
        state.user = { ...user, onboardingCompleted: true };
        return { updated: true };
      }, { redraw: false });
      if (result.error) return showError(result.error, form);
      beginGeneration();
    }

    if (type === "profile") {
      change((state) => {
        state.user.name = values.name.trim();
        return { updated: true };
      });
    }
  }, { signal });

  root.addEventListener("click", (event) => {
    const control = event.target.closest("[data-action]");
    if (!control || control.disabled) return;
    const values = control.dataset;
    switch (values.action) {
      case "language":
        clearToasts();
        if (route === "setup") saveSetupDraft();
        if (route === "guru") stopGuruVoice();
        change((state) => {
          state.preferences.locale = state.preferences.locale === "zh" ? "en" : "zh";
          return { updated: true };
        });
        break;
      case "cat-jump": {
        if (!matchMedia("(prefers-reduced-motion: reduce)").matches) {
          control.querySelector("svg").animate(
            [{ transform: "translateY(0)" }, { transform: "translateY(-20px) rotate(-5deg)" }, { transform: "translateY(0)" }],
            { duration: 415, easing: "ease-out" },
          );
        }
        const bubble = surface.querySelector(".lp-welcome-bubble");
        bubble.textContent = t("Ready when you are!", "准备好了就开始吧！");
        break;
      }
      case "cat-toggle":
        catOpen = !catOpen;
        updateCat();
        catLayer.querySelector("button")?.focus({ preventScroll: true });
        break;
      case "setup-back":
        saveSetupDraft();
        if (step === 1) navigate("welcome");
        else openSetupStep(step - 1);
        break;
      case "setup-next":
        if (!data.tasks.length) return showError({ code: "noTasks" });
        openSetupStep(3);
        break;
      case "add-task":
      case "edit-task":
        editTask(values.id, values.date);
        break;
      case "complete":
        change((state, now) => M.setCompletion(state, values.id, values.date, values.completed === "true", now));
        if (dialogue.open) dialogue.close();
        break;
      case "ask-delete":
        confirm(t("Delete task?", "删除任务？"), t("This removes the task from your schedule.", "这会把任务从日程中移除。"),
          "delete-task", `data-id="${V.e(values.id)}"`);
        break;
      case "delete-task":
        change((state, now) => M.deleteTask(state, values.id, now));
        dialogue.close();
        break;
      case "navigate":
        if (values.route === "guru") {
          stopGuruVoice();
          clearToasts();
          guruSelection = null;
        }
        navigate(values.route);
        break;
      case "guru-open":
      case "guru-ad-details":
        openGuruTemplate(values.template);
        break;
      case "guru-preview-ad":
        showNextCoursePromotion();
        break;
      case "guru-gallery":
        stopGuruVoice();
        clearToasts();
        guruSelection = null;
        render();
        break;
      case "guru-action":
        guruAction(values.guruAction);
        break;
      case "guru-unlock":
        dialogue.close();
        guruAction("unlock");
        break;
      case "guru-play":
        playGuruVoice();
        break;
      case "guru-stop":
        stopGuruVoice("stopped");
        render();
        break;
      case "prev-week":
      case "next-week":
      case "today":
        week = values.action === "today" ? M.monday(M.localDate(new Date())) : M.addDays(week, values.action === "prev-week" ? -7 : 7);
        render({ resetScroll: true });
        break;
      case "points-history":
        showDialog(t("Points History", "积分记录"), V.pointsHistory());
        break;
      case "close-dialog":
        dialogue.close();
        break;
      case "start-demo":
        if (data.preferences.paused || !data.preferences.optional) {
          showDialog(t("Notification settings", "通知设置"),
            `<p class="lp-confirm-copy">${t("Resume notifications and enable optional reminders to play the demo.", "请恢复通知并启用非必要提醒，再播放通知演示。")}</p>
             <div class="lp-actions">${V.button(t("Open Settings", "打开设置"), "open-settings", "lp-primary")}</div>`);
          break;
        }
        clearToasts();
        change(M.startDemo);
        if (route !== "calendar") navigate("calendar");
        break;
      case "open-settings":
        dialogue.close();
        navigate("settings");
        break;
      case "stop-demo":
        clearToasts();
        change((state) => {
          state.demo.enabled = false;
          state.demo.nextAt = null;
          return { updated: true };
        });
        break;
      case "filter-notices":
        filter = values.filter;
        render();
        break;
      case "read-notice":
        readNotice(values.id);
        break;
      case "read-all":
        readNotice();
        break;
      case "ask-clear":
        confirm(t("Clear notifications?", "清空通知？"), t("This removes all items from your notification history.", "这会清空通知历史。"), "clear-notices");
        break;
      case "clear-notices":
        clearToasts();
        change((state) => {
          state.notifications = [];
          return { updated: true };
        });
        dialogue.close();
        break;
      case "notice-target":
        toastClicked(values.id);
        break;
      case "dismiss-toast":
        dismissToast(values.id);
        break;
      case "ask-reset":
        confirm(t("Reset Demo?", "重置演示？"),
          t("This deletes your local schedule, points, rankings, and notifications and returns to the welcome page.",
            "这会清除当前浏览器的日程、积分、排名和通知，并回到欢迎页。"), "reset");
        break;
      case "reset":
        reset();
        break;
    }
  }, { signal });

  root.addEventListener("change", (event) => {
    const input = event.target;
    if (!input.dataset.pref) return;
    const preference = input.dataset.pref;
    const selected = input.checked;
    if ((preference === "paused" && selected) || (preference === "optional" && !selected)) clearToasts();
    change((state, now) => {
      state.preferences[preference] = selected;
      if (state.demo.enabled) state.demo.nextAt = now.getTime() + M.DEMO_GAP;
      return { updated: true };
    });
  }, { signal });

  window.addEventListener("storage", (event) => {
    if (event.key !== key) return;
    const fresh = read() || M.newState();
    data = fresh;
    if (route === "welcome") return;
    if (!fresh.user.onboardingCompleted && initializedRoute()) {
      clearGeneration();
      dialogue.close();
      navigate("welcome");
    } else if (fresh.user.onboardingCompleted && route === "setup") {
      dialogue.close();
      navigate("calendar");
    } else {
      if (fresh.preferences.paused) clearToasts();
      render();
    }
  }, { signal });

  function initializedRoute() {
    return !["welcome", "setup"].includes(route);
  }

  document.addEventListener("visibilitychange", syncTimer, { signal });
  window.addEventListener("pageshow", (event) => {
    if (!event.persisted) return;
    data = read() || data;
    dialogue.close();
    clearGeneration();
    navigate("welcome");
  }, { signal });
  navigate(route);
  return () => {
    clearGeneration();
    clearToasts();
    stopGuruVoice();
    abort.abort();
    if (ticking !== null) window.clearInterval(ticking);
    delete root.dataset.mounted;
  };
}
