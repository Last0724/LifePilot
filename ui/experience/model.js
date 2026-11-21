(function (root, factory) {
  const model = factory();
  if (typeof module === "object" && module.exports) module.exports = model;
  else root.LifePilotModel = model;
})(globalThis, function () {
  "use strict";

  const DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
  const CATEGORIES = ["Study", "Work", "Exercise", "Personal", "Rest", "Other"];
  const PRIORITIES = ["High", "Medium", "Low"];
  const DEMO_GAP = 6000;
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
  const level = (xp) => 1 + Math.floor(xp / 200);
  const progress = (xp) => xp % 200;
  const hasReward = (state, key) => state.points.some((event) => event.uniqueRewardKey === key);

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
    state.notifications.unshift({
      id: uniqueId(), type, title, message, route, timestamp: now.toISOString(), isRead: false, optional,
    });
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
      case "XP_EARNED":
        notify(state, "xp", [`You earned ${data.points} XP!`, `你获得了 ${data.points} XP！`],
          [`Only ${200 - progress(totalXP(state))} XP until your next level.`, `距离下一级还差 ${200 - progress(totalXP(state))} XP。`],
          "points", now);
        break;
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

  function reward(state, actionType, points, key, now, task = null) {
    if (hasReward(state, key)) return 0;
    state.points.push({
      id: uniqueId(), userId: state.user.id, actionType, points,
      taskId: task?.id || null, taskTitle: task?.title || "", timestamp: now.toISOString(), uniqueRewardKey: key,
    });
    return points;
  }

  function rankChanged(state, before, now) {
    const previous = new Map(before.map((entry) => [entry.id, entry.rank]));
    const shifts = Object.fromEntries(ranking(state).map((entry) => [entry.id, previous.get(entry.id) - entry.rank]));
    if (Object.values(shifts).some(Boolean)) state.rankChanges = shifts;
    const delta = shifts[state.user.id];
    if (delta) event(state, "RANK_CHANGED", { delta }, now);
    return delta;
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
    const taskXP = reward(state, task.priority === "High" ? "high" : "task",
      task.priority === "High" ? 20 : 10, `task:${key}`, now, task);
    const daily = occurrences(state, [day]);
    const weekly = occurrences(state, weekDays(day));
    const dayXP = daily.length && daily.every((item) => item.completed) ? reward(state, "day", 30, `day:${day}`, now) : 0;
    const weekXP = weekly.length && weekly.every((item) => item.completed)
      ? reward(state, "week", 100, `week:${monday(day)}`, now) : 0;
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
    const before = ranking(state);
    const priorLevel = level(totalXP(state));
    const points = reward(state, "check", 2, `check:${today}`, now);
    if (points) {
      event(state, "DASHBOARD_OPENED", {}, now);
      event(state, "XP_EARNED", { points }, now);
      const next = level(totalXP(state));
      const levelUp = next > priorLevel;
      if (levelUp) event(state, "LEVEL_UP", { level: next }, now);
      return { updated: true, checkXP: points, levelUp, rankDelta: rankChanged(state, before, now) };
    }
    return {};
  }

  const DEMO_NOTICES = [
    ["cat", ["Welcome back!", "欢迎回来！"], ["Let’s check how productive you’ve been.", "来看看你有多高效。"], "calendar"],
    ["task", ["Task reminder", "任务提醒"], ["Your weekly calendar is waiting for you.", "你的周历在等你。"], "tasks"],
    ["pressure", ["Don’t lose momentum", "别失去效率势头"], ["You haven’t checked your progress recently.", "你好一会儿没查看进度了。"], "points"],
    ["xp", ["XP opportunity", "积分机会"], ["Finish a task to add to your productivity score.", "完成任务，为你的效率积分加分。"], "points"],
    ["rank", ["Leaderboard update", "排行榜更新"], ["Simulated competitors are checking their progress.", "模拟竞争者也在查看他们的进度。"], "leaderboard"],
    ["rank", ["The competition is heating up", "竞争越来越激烈"], ["Your rank can change while you plan your week.", "你规划一周的同时，名次还在变。"], "leaderboard"],
    ["pressure", ["Schedule optimization", "日程优化提醒"], ["Could this week be just a little more efficient?", "这一周还能再高效一点吗？"], "calendar"],
    ["cat", ["A nudge from your cat", "小猫轻轻提醒"], ["So many things to keep up with!", "要关注的事可真多！"], "notifications"],
  ];

  function startDemo(state, now) {
    state.demo = { enabled: true, index: 0, nextAt: now.getTime() + DEMO_GAP, surged: false };
    return { updated: true };
  }

  function tick(state, now) {
    if (!state.user.onboardingCompleted || state.preferences.paused) return {};
    if (state.preferences.optional && state.demo.enabled && state.demo.index < DEMO_NOTICES.length) {
      if (state.demo.nextAt > now.getTime()) return {};
      const step = state.demo.index;
      state.demo.index += 1;
      state.demo.nextAt = now.getTime() + DEMO_GAP;
      if (step === 4) {
        const before = ranking(state);
        if (surgeCompetitors(state, before)) {
          return { updated: true, rankDelta: rankChanged(state, before, now) };
        }
      }
      notify(state, ...DEMO_NOTICES[step], now, true);
      return { updated: true, catNudge: step === 0 || step === 7 };
    }

    if (state.demo.enabled) return {};
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
    DAYS, CATEGORIES, PRIORITIES, DEMO_GAP, DEMO_NOTICES, newState, localDate, addDays, weekday, monday, weekDays,
    dateAt, minutes, routineError, scheduleError, occurrences, totalXP, level, progress, ranking, saveTask, deleteTask,
    setCompletion, openDashboard, startDemo, tick, notify,
  };
});
