(function (root, factory) {
  const model = factory();
  if (typeof module === "object" && module.exports) module.exports = model;
  else root.LifePilotModel = model;
})(globalThis, function () {
  "use strict";

  const DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
  const CATEGORIES = ["Study", "Work", "Exercise", "Personal", "Rest", "Other"];
  const PRIORITIES = ["High", "Medium", "Low"];
  const XP_REWARDS = Object.freeze({ login: 10, checkIn: 10, task: 10, high: 20, day: 30, week: 100 });
  const XP_PER_LEVEL = 200;
  const DEMO_GAP = 10000;
  const DEMO_HISTORY_LIMIT = 100;
  const REMINDER_COOLDOWN = 15 * 60 * 1000;
  const DEFAULT_ROUTINE = { wake: "07:00", bed: "23:00", workStart: "09:00", workEnd: "17:00" };
  const NAMES = ["Alex", "Sophia", "Daniel", "Avery", "Emilia", "Arjun", "Maya", "Kai",
    "Sam", "Lina", "Noah", "Riley", "Hana", "Theo", "Zoe", "Jules", "Eli", "Mina",
    "Sol", "Ren", "Ari", "Bea", "Cam", "Dee"];
  const STARTING_XP = [480, 455, 430, 406, 388, 375, 352, 325, 304, 275, 240, 218,
    189, 160, 136, 110, 90, 67, 41, 17, 0, 0, 0, 0];

  const pad = (value) => String(value).padStart(2, "0");
  const localDate = (date) => `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
  const dateAt = (day) => new Date(day + "T12:00:00");
  const addDays = (day, count) => {
    const date = dateAt(day);
    date.setDate(date.getDate() + count);
    return localDate(date);
  };
  const weekday = (day) => (dateAt(day).getDay() + 6) % 7;
  const monday = (day) => addDays(day, -weekday(day));
  const weekDays = (day) => DAYS.map((_, i) => addDays(monday(day), i));
  const minutes = (value) => {
    if (!/^(?:[01][0-9]|2[0-3]):[0-5][0-9]$/.test(value || "")) return NaN;
    const [hour, minute] = value.split(":").map(Number);
    return hour * 60 + minute;
  };
  const validDate = (day) => /^\d{4}-\d{2}-\d{2}$/.test(day || "") && localDate(dateAt(day)) === day;
  const uniqueId = () => globalThis.crypto?.randomUUID?.() || Math.random().toString(36).slice(2);

  function newState() {
    return {
      version: 1,
      user: { id: "player", name: "", onboardingCompleted: false, routine: { ...DEFAULT_ROUTINE }, goal: "", targetHours: null },
      tasks: [],
      completions: {},
      points: [],
      competitors: NAMES.map((name, i) => ({
        id: `sim-${pad(i + 1)}`, name, xp: STARTING_XP[i],
        completedTasks: Math.floor(STARTING_XP[i] / 18), simulated: true,
      })),
      rankChanges: {},
      notifications: [],
      preferences: { paused: false, optional: true },
      demo: { enabled: false, index: 0, nextAt: null, surged: false },
      reminders: {},
      lastReminderAt: null,
    };
  }

  function routineError(routine) {
    const values = [routine.wake, routine.bed, routine.workStart, routine.workEnd].map(minutes);
    if (values.some(Number.isNaN) || values[0] === values[1] || values[2] >= values[3]) return "routine";
    return "";
  }

  function overlaps(a, b) {
    if (weekday(a.date) !== weekday(b.date)) return false;
    if (!(minutes(a.startTime) < minutes(b.endTime) && minutes(b.startTime) < minutes(a.endTime))) return false;
    if (a.date === b.date) return true;
    return a.date < b.date ? a.repeatWeekly : b.repeatWeekly;
  }

  function taskError(tasks, item) {
    if (!item.title || item.title.length > 90) return { code: "title" };
    if (!CATEGORIES.includes(item.category) || !PRIORITIES.includes(item.priority)) return { code: "choices" };
    if (!validDate(item.date)) return { code: "date" };
    if (!(minutes(item.startTime) < minutes(item.endTime))) return { code: "times" };
    const conflict = tasks.find((task) => task.id !== item.id && overlaps(task, item));
    return conflict ? { code: "overlap", title: conflict.title } : null;
  }

  function occurs(task, day) {
    return task.date === day || (task.repeatWeekly && day > task.date && weekday(task.date) === weekday(day));
  }

  function taskKey(task, day) {
    return day === task.date ? task.id : `${task.id}@${day}`;
  }

  function occurrences(state, days) {
    return days.flatMap((day) => state.tasks.filter((task) => occurs(task, day)).map((task) => {
      const key = taskKey(task, day);
      return { ...task, originalDate: task.date, date: day, key, completed: Boolean(state.completions[key]) };
    })).sort((a, b) => a.date.localeCompare(b.date) || a.startTime.localeCompare(b.startTime));
  }

  const totalXP = (state) => state.points.reduce((sum, entry) => sum + entry.points, 0);
  const level = (xp) => 1 + Math.floor(xp / XP_PER_LEVEL);
  const progress = (xp) => xp % XP_PER_LEVEL;
  const hasReward = (state, key) => state.points.some((event) => event.uniqueRewardKey === key);
  const checkInKey = (now) => `check-in:${localDate(now)}`;
  const hasCheckedIn = (state, now) => hasReward(state, checkInKey(now));

  function ranking(state) {
    const local = {
      id: state.user.id, name: state.user.name, xp: totalXP(state),
      completedTasks: Object.keys(state.completions).length, simulated: false,
    };
    return [...state.competitors, local]
      .sort((a, b) => b.xp - a.xp || (a.id < b.id ? -1 : 1))
      .map((entry, index) => ({ ...entry, rank: index + 1, change: state.rankChanges[entry.id] || 0 }));
  }

  function notify(state, type, title, message, route, now, optional = false) {
    if (state.preferences.paused || (optional && !state.preferences.optional)) return;
    const notice = {
      id: uniqueId(), type, title, message, route, timestamp: now.toISOString(), isRead: false, optional,
    };
    state.notifications.unshift(notice);
    return notice;
  }

  function event(state, action, data, now) {
    switch (action) {
      case "TASK_CREATED":
        notify(state, "task", ["Task added", "已添加任务"], [data.title, data.title], "tasks", now);
        break;
      case "TASK_UPDATED":
        notify(state, "task", ["Task updated", "任务已更新"], [data.title, data.title], "tasks", now);
        break;
      case "TASK_COMPLETED":
        notify(state, "task", ["Task completed", "任务已完成"], [data.title, data.title], "tasks", now);
        break;
      case "XP_EARNED": {
        const remaining = XP_PER_LEVEL - progress(totalXP(state));
        notify(state, "xp", [`You earned ${data.points} XP!`, `你获得了 ${data.points} XP！`],
          [`Only ${remaining} XP until your next level.`, `距离下一级还差 ${remaining} XP。`], "points", now);
        break;
      }
      case "LEVEL_UP":
        notify(state, "cat", ["Wow! You’re leveling up!", "太棒了，你升级了！"],
          [`You reached Level ${data.level}.`, `你已达到 ${data.level} 级。`], "points", now);
        break;
      case "RANK_CHANGED":
        notify(state, "rank",
          data.delta < 0 ? [`Your rank dropped by ${-data.delta} places.`, `你的排名下降了 ${-data.delta} 位。`]
            : [`Your rank rose by ${data.delta} places.`, `你的排名上升了 ${data.delta} 位。`],
          data.delta < 0 ? ["Simulated competitors earned more points.", "模拟竞争者获得了更多积分。"]
            : ["See where you stand among simulated competitors.", "查看你在模拟排行榜中的位置。"],
          "leaderboard", now);
        break;
      case "DASHBOARD_OPENED":
        notify(state, "task", ["Welcome back", "欢迎回来"], ["Your week is ready to view.", "你的周计划已就绪。"],
          "calendar", now, true);
        break;
    }
  }

  function reward(state, actionType, key, now, task = null) {
    if (hasReward(state, key)) return 0;
    const points = XP_REWARDS[actionType];
    state.points.push({
      id: uniqueId(), userId: state.user.id, actionType, points,
      taskId: task?.id || null, taskTitle: task?.title || "", timestamp: now.toISOString(), uniqueRewardKey: key,
    });
    return points;
  }

  function rankChanged(state, before, now, { announce = true } = {}) {
    const previous = new Map(before.map((entry) => [entry.id, entry.rank]));
    const shifts = Object.fromEntries(ranking(state).map((entry) => [entry.id, previous.get(entry.id) - entry.rank]));
    if (Object.values(shifts).some(Boolean)) state.rankChanges = shifts;
    const delta = shifts[state.user.id];
    if (delta && announce) event(state, "RANK_CHANGED", { delta }, now);
    return delta;
  }

  function activityReward(state, action, key, now) {
    const before = ranking(state);
    const previousLevel = level(totalXP(state));
    const points = reward(state, action, key, now);
    const currentLevel = level(totalXP(state));
    const levelUp = currentLevel > previousLevel;
    event(state, "XP_EARNED", { points }, now);
    if (levelUp) event(state, "LEVEL_UP", { level: currentLevel }, now);
    return { updated: true, [action + "XP"]: points, levelUp, rankDelta: rankChanged(state, before, now) };
  }

  function signIn(state, displayName, now) {
    const name = displayName.trim();
    if (!name) return {};
    state.user.name = name;
    return activityReward(state, "login", `login:${uniqueId()}`, now);
  }

  function checkIn(state, now) {
    if (!state.user.onboardingCompleted || hasCheckedIn(state, now)) return {};
    return activityReward(state, "checkIn", checkInKey(now), now);
  }

  function surgeCompetitors(state, before) {
    if (!state.demo.enabled || state.demo.surged) return false;
    const ownRank = before.find((entry) => entry.id === state.user.id).rank;
    const challengers = before.filter((entry) => entry.simulated && entry.rank > ownRank).slice(0, 2);
    if (!challengers.length) return false;
    const challengersIds = new Set(challengers.map((entry) => entry.id));
    const xp = totalXP(state);
    for (const prior of before.filter((row) => row.simulated)) {
      if (challengersIds.has(prior.id) || (prior.rank < ownRank && prior.xp <= xp)) {
        const row = state.competitors.find((entry) => entry.id === prior.id);
        const target = xp + (challengersIds.has(row.id) ? 4 : 2);
        const gained = Math.max(0, target - row.xp);
        row.xp += gained;
        row.completedTasks += Math.ceil(gained / 20);
      }
    }
    state.demo.surged = true;
    return true;
  }

  function saveTask(state, item, now) {
    const task = { ...item, title: String(item.title || "").trim(), repeatWeekly: Boolean(item.repeatWeekly) };
    task.id ||= uniqueId();
    const error = taskError(state.tasks, task);
    if (error) return { error };
    const index = state.tasks.findIndex((entry) => entry.id === task.id);
    if (index === -1) state.tasks.push(task);
    else {
      const old = state.tasks[index];
      state.tasks[index] = task;
      if (old.repeatWeekly && (!task.repeatWeekly || weekday(task.date) !== weekday(old.date))) {
        for (const key of Object.keys(state.completions)) {
          if (key.startsWith(task.id + "@")) delete state.completions[key];
        }
      }
    }
    if (state.user.onboardingCompleted) event(state, index === -1 ? "TASK_CREATED" : "TASK_UPDATED", task, now);
    return { updated: true };
  }

  function deleteTask(state, id, now) {
    const task = state.tasks.find((entry) => entry.id === id);
    if (!task) return {};
    state.tasks = state.tasks.filter((entry) => entry.id !== id);
    for (const key of Object.keys(state.completions)) {
      if (key === id || key.startsWith(id + "@")) delete state.completions[key];
    }
    if (state.user.onboardingCompleted) {
      notify(state, "task", ["Task removed", "任务已删除"], [task.title, task.title], "tasks", now);
    }
    return { updated: true };
  }

  function setCompletion(state, id, day, completed, now) {
    const task = state.tasks.find((entry) => entry.id === id);
    if (!task || !validDate(day) || !occurs(task, day)) return {};
    const key = taskKey(task, day);
    if (Boolean(state.completions[key]) === completed) return {};
    if (!completed) {
      delete state.completions[key];
      event(state, "TASK_UPDATED", task, now);
      return { updated: true };
    }

    const before = ranking(state);
    const previousLevel = level(totalXP(state));
    state.completions[key] = now.toISOString();
    event(state, "TASK_COMPLETED", task, now);
    const taskXP = reward(state, task.priority === "High" ? "high" : "task", `task:${key}`, now, task);
    const daily = occurrences(state, [day]);
    const weekly = occurrences(state, weekDays(day));
    const dayXP = daily.length && daily.every((item) => item.completed) ? reward(state, "day", `day:${day}`, now) : 0;
    const weekXP = weekly.length && weekly.every((item) => item.completed)
      ? reward(state, "week", `week:${monday(day)}`, now) : 0;
    const added = taskXP + dayXP + weekXP;
    const currentLevel = level(totalXP(state));
    if (added) event(state, "XP_EARNED", { points: added }, now);
    if (currentLevel > previousLevel) event(state, "LEVEL_UP", { level: currentLevel }, now);
    if (added) surgeCompetitors(state, before);
    return { updated: true, taskXP, dayXP, weekXP, levelUp: currentLevel > previousLevel, rankDelta: rankChanged(state, before, now), completed: true };
  }

  function openDashboard(state, now) {
    if (!state.user.onboardingCompleted) return {};
    const today = localDate(now);
    if (state.lastDashboardOpenedOn === today || hasReward(state, `check:${today}`)) return {};
    state.lastDashboardOpenedOn = today;
    event(state, "DASHBOARD_OPENED", {}, now);
    return { updated: true };
  }

  const MOTIVATION = [
    ["Do something your future self can check off.", "做一件未来的你能打勾的事。"],
    ["Start before you feel ready. The clock already did.", "别等准备好，时钟可早就开始了。"],
    ["One small win now beats a perfect plan later.", "现在完成一小步，比晚点做出完美计划更管用。"],
    ["Someone else just found five minutes. Can you?", "别人又挤出了五分钟。你呢？"],
    ["Your to-do list won’t get shorter while you look at it.", "光盯着待办看，它可不会自己变短。"],
    ["Don’t let “later” become your busiest time slot.", "别让「等一下」占满你的一整天。"],
  ];

  function startDemo(state, now) {
    state.demo = { enabled: true, index: 0, nextAt: now.getTime() + DEMO_GAP, surged: false };
    return { updated: true };
  }

  function demoNotice(state, now) {
    switch (state.demo.index % 4) {
      case 0: {
        const before = ranking(state);
        const delta = surgeCompetitors(state, before) ? rankChanged(state, before, now, { announce: false }) : 0;
        const { rank } = ranking(state).find((entry) => !entry.simulated);
        const title = delta < 0
          ? [`You were overtaken · down ${-delta}`, `你的排名被超过了 · 下降 ${-delta} 名`]
          : ["Your rivals are catching up", "对手正在赶上来"];
        const message = [`You’re #${rank} among simulated competitors. Check who’s ahead.`, `你在模拟积分榜排第 ${rank} 名。看看谁在你前面。`];
        return ["rank", title, message, "leaderboard"];
      }
      case 1: {
        const today = localDate(now);
        const tasks = occurrences(state, weekDays(today));
        const plannedWeek = state.user.chatPlanWeek;
        const next = tasks.find((task) => !task.completed && task.date >= today)
          || (plannedWeek > today && occurrences(state, weekDays(plannedWeek)).find((task) => !task.completed))
          || tasks.find((task) => !task.completed);
        const title = next ? ["Still on your list", "任务还没完成"] : ["What’s next?", "接下来做什么？"];
        const message = next ? [`“${next.title}” is still pending. Open your list and get started.`, `「${next.title}」还没打勾。打开任务清单，快开始吧。`]
          : ["Your list is clear. Schedule a new task to keep moving.", "清单空了。趁现在再安排一个新任务。"];
        return ["task", title, message, next ? "tasks" : "calendar"];
      }
      case 2: {
        const choices = MOTIVATION.filter((_, index) => index !== state.demo.lastMotivation);
        const message = choices[Math.floor(Math.random() * choices.length)];
        state.demo.lastMotivation = MOTIVATION.indexOf(message);
        return ["pressure", ["A word from your cat", "小黑猫催你一句"], message, "tasks"];
      }
      default:
        return ["cat", ["Your next slot is waiting", "还有时间没排上"],
          ["Open your calendar and plan one more task before the next reminder.", "打开周历，赶在下一条提醒前再排一个任务。"], "calendar"];
    }
  }

  function tick(state, now) {
    if (!state.user.onboardingCompleted || state.preferences.paused) return {};
    if (state.preferences.optional && state.demo.enabled) {
      if (state.demo.nextAt > now.getTime()) return {};
      const previousRanks = state.rankChanges;
      const notice = notify(state, ...demoNotice(state, now), now, true);
      notice.animatedCat = true;
      let count = 0;
      state.notifications = state.notifications.filter((item) => !item.animatedCat || ++count <= DEMO_HISTORY_LIMIT);
      state.demo.index += 1;
      state.demo.nextAt = now.getTime() + DEMO_GAP;
      return { updated: true, rankingsChanged: previousRanks !== state.rankChanges };
    }

    if (state.lastReminderAt && now.getTime() - state.lastReminderAt < REMINDER_COOLDOWN) return {};
    const actualMinutes = now.getHours() * 60 + now.getMinutes();
    const next = occurrences(state, [localDate(now)]).find((item) => {
      const wait = minutes(item.startTime) - actualMinutes;
      return !item.completed && wait >= 0 && wait <= 20 && !state.reminders[item.key + "@" + item.date];
    });
    if (!next) return {};
    state.reminders[next.key + "@" + next.date] = true;
    state.lastReminderAt = now.getTime();
    notify(state, "task", ["Your next task starts soon", "下一项任务即将开始"], [next.title, next.title], "tasks", now);
    return { updated: true };
  }

  function scheduleError(state, user) {
    if (routineError(user.routine)) return { code: "routine" };
    if (!state.tasks.length) return { code: "noTasks" };
    if (!String(user.goal || "").trim()) return { code: "goal" };
    if (user.targetHours !== null && (!Number.isFinite(user.targetHours) || user.targetHours < 0 || user.targetHours > 168)) {
      return { code: "target" };
    }
    return state.tasks.map((task) => taskError(state.tasks, task)).find(Boolean) || null;
  }

  return {
    DAYS, CATEGORIES, PRIORITIES, XP_REWARDS, XP_PER_LEVEL, DEMO_GAP, newState, localDate, addDays, weekday, monday, weekDays,
    dateAt, minutes, routineError, scheduleError, occurrences, totalXP, level, progress, ranking, saveTask, deleteTask,
    setCompletion, signIn, checkIn, hasCheckedIn, openDashboard, startDemo, tick, notify,
  };
});
