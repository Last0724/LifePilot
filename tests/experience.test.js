const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const { test } = require("node:test");
const { createContext, runInContext } = require("node:vm");
const M = require("../ui/experience/model.js");

const MON = "2026-11-16";
const WED = "2026-11-18";
const NOW = new Date("2026-11-16T08:15:00");
const plus = (sec) => new Date(NOW.getTime() + sec * 1000);

function task(id, date = MON, startTime = "09:00", endTime = "10:00", other = {}) {
  return { id, title: id, date, startTime, endTime, category: "Study", priority: "Medium", repeatWeekly: false, ...other };
}

function onboarded() {
  const state = M.newState();
  state.user.goal = "Prepare a presentation";
  state.user.onboardingCompleted = true;
  return state;
}

test("week dates use local Monday and preserve the calendar day", () => {
  assert.equal(M.monday("2026-11-22"), MON);
  assert.deepEqual(M.weekDays(WED), [
    MON, "2026-11-17", WED, "2026-11-19", "2026-11-20", "2026-11-21", "2026-11-22",
  ]);
  assert.equal(M.addDays("2026-03-08", 1), "2026-03-09");
  assert.equal(M.localDate(NOW), MON);
});

test("setup requires a real activity and rejects reversed, impossible and overlapping slots", () => {
  const state = M.newState();
  const profile = { ...state.user, goal: "Prepare a presentation" };
  assert.equal(M.scheduleError(state, profile).code, "noTasks");
  assert.equal(M.saveTask(state, task("Invalid", MON, "11:00", "10:00"), NOW).error.code, "times");
  assert.equal(M.saveTask(state, task("Impossible", "2026-02-31"), NOW).error.code, "date");
  assert.ok(M.saveTask(state, task("Recurring", MON, "09:00", "10:00", { repeatWeekly: true }), NOW).updated);
  assert.equal(M.saveTask(state, task("Conflict", "2026-11-23", "09:45", "10:30"), NOW).error.title, "Recurring");
  assert.ok(M.saveTask(state, task("Adjacent", MON, "10:00", "10:30"), NOW).updated);
  assert.equal(M.scheduleError(state, profile), null);
  assert.equal(M.scheduleError(state, { ...profile, goal: "" }).code, "goal");
  assert.equal(M.scheduleError(state, { ...profile, targetHours: 169 }).code, "target");
  assert.equal(state.tasks.length, 2);
});

test("completion applies the base, day and week awards once and keeps the ledger on reopen", () => {
  let state = onboarded();
  M.saveTask(state, task("Normal"), NOW);
  M.saveTask(state, task("High", MON, "10:00", "11:00", { priority: "High" }), NOW);
  M.saveTask(state, task("Midweek", WED), NOW);
  assert.equal(M.setCompletion(state, "Normal", MON, true, NOW).taskXP, 10);
  assert.deepEqual(M.setCompletion(state, "Normal", MON, true, NOW), {});
  let result = M.setCompletion(state, "High", MON, true, NOW);
  assert.equal(result.taskXP, 20);
  assert.equal(result.dayXP, 30);
  assert.equal(result.weekXP, 0);
  result = M.setCompletion(state, "Midweek", WED, true, NOW);
  assert.equal(result.dayXP, 30);
  assert.equal(result.weekXP, 100);
  assert.equal(M.totalXP(state), 200);
  assert.equal(M.level(M.totalXP(state)), 2);
  assert.equal(M.progress(M.totalXP(state)), 0);
  assert.ok(state.notifications.some((item) => item.title[0] === "Wow! You’re leveling up!"));
  state = JSON.parse(JSON.stringify(state));
  M.setCompletion(state, "Midweek", WED, false, NOW);
  M.setCompletion(state, "Midweek", WED, true, NOW);
  assert.equal(M.totalXP(state), 200);
  assert.equal(new Set(state.points.map((row) => row.uniqueRewardKey)).size, state.points.length);
});

test("manual sign-in pays 10 XP every time, while calendar visits award no XP", () => {
  const state = M.newState();
  assert.deepEqual(M.signIn(state, "  ", NOW), {});
  assert.equal(M.signIn(state, "  Demo  ", NOW).loginXP, 10);
  assert.equal(state.user.name, "Demo");
  state.user.onboardingCompleted = true;
  assert.ok(M.openDashboard(state, NOW).updated);
  assert.deepEqual(M.openDashboard(state, plus(1)), {});
  assert.equal(M.totalXP(state), 10);
  assert.equal(M.signIn(state, "Demo", plus(2)).loginXP, 10);
  assert.equal(M.totalXP(state), 20);
  assert.notEqual(state.points[0].uniqueRewardKey, state.points[1].uniqueRewardKey);
});

test("a daily check-in moves the player's real rank and pays once across reloads", () => {
  const state = M.newState();
  assert.deepEqual(M.checkIn(state, NOW), {});
  state.user.onboardingCompleted = true;
  M.signIn(state, "Demo", NOW);
  const before = M.ranking(state).find((row) => !row.simulated);
  assert.equal(before.rank, 21);
  const result = M.checkIn(state, plus(1));
  assert.equal(result.checkInXP, 10);
  assert.equal(result.rankDelta, 1);
  const saved = JSON.parse(JSON.stringify(state));
  assert.ok(M.hasCheckedIn(saved, plus(2)));
  assert.deepEqual(M.checkIn(saved, plus(2)), {});
  const player = M.ranking(saved).find((row) => !row.simulated);
  assert.equal(player.xp, 20);
  assert.equal(player.rank, 20);
  assert.equal(player.change, 1);
  const tomorrow = new Date("2026-11-17T08:00:00");
  assert.equal(M.checkIn(saved, tomorrow).checkInXP, 10);
  assert.equal(M.totalXP(saved), 30);
});

test("each recurring occurrence completes independently, and updating a one-off never dupes XP", () => {
  const state = onboarded();
  M.saveTask(state, task("Series", MON, "09:00", "10:00", { repeatWeekly: true }), NOW);
  M.saveTask(state, task("One-off", WED), NOW);
  const future = M.addDays(MON, 7);
  M.setCompletion(state, "Series", MON, true, NOW);
  assert.ok(M.occurrences(state, [MON])[0].completed);
  assert.equal(M.occurrences(state, [future])[0].completed, false);
  assert.equal(M.setCompletion(state, "Series", future, true, NOW).taskXP, 10);
  M.setCompletion(state, "One-off", WED, true, NOW);
  const xp = M.totalXP(state);
  const next = M.addDays(WED, 1);
  M.saveTask(state, task("One-off", next, "11:00", "12:00"), NOW);
  assert.ok(M.occurrences(state, [next])[0].completed);
  assert.deepEqual(M.setCompletion(state, "One-off", next, true, NOW), {});
  M.deleteTask(state, "One-off", NOW);
  assert.equal(M.occurrences(state, [next]).length, 0);
  assert.equal(M.totalXP(state), xp);
});

test("the bilingual XP table reflects the active rules and preserves historical amounts", () => {
  const state = onboarded();
  state.points.push({ actionType: "task", points: 7, taskTitle: "Historical task", timestamp: NOW.toISOString() });
  state.points.push({ actionType: "check", points: 2, uniqueRewardKey: `check:${MON}`, timestamp: NOW.toISOString() });
  assert.deepEqual(M.openDashboard(state, NOW), {});
  const window = { LifePilotModel: M, LifePilotGuruView: () => () => "" };
  const context = createContext({ window });
  runInContext(readFileSync(require.resolve("../ui/experience/view.js"), "utf8"), context);

  for (const [locale, caption] of [["en", "How you earn XP"], ["zh", "积分发放规则"]]) {
    state.preferences.locale = locale;
    const view = window.LifePilotViews({ state: () => state, t: (en, zh) => locale === "zh" ? zh : en });
    const markup = view.pointsHistory();
    const tableAmounts = [...markup.matchAll(/class="lp-rule-xp">\+(\d+)</g)].map(([, value]) => Number(value));
    assert.deepEqual(tableAmounts.sort((a, b) => a - b), Object.values(M.XP_REWARDS).sort((a, b) => a - b));
    assert.ok(markup.includes(caption));
    assert.match(markup, /Historical task<\/span><b>\+7 XP/);
    assert.match(markup, /<b>\+2 XP<\/b>/);
  }
});

test("demo competition moves real points and rank after a user's XP gain", () => {
  const state = onboarded();
  M.saveTask(state, task("One"), NOW);
  M.saveTask(state, task("Two", MON, "10:00", "11:00"), NOW);
  M.openDashboard(state, NOW);
  M.startDemo(state, NOW);
  const initial = M.ranking(state).find((row) => !row.simulated);
  const before = state.competitors.map((row) => row.xp);
  const outcome = M.setCompletion(state, "One", MON, true, NOW);
  const current = M.ranking(state).find((row) => !row.simulated);
  assert.equal(current.xp, initial.xp + 10);
  assert.equal(current.rank, initial.rank + 2);
  assert.equal(outcome.rankDelta, -2);
  assert.equal(state.competitors.filter((row, i) => row.xp > before[i]).length, 2);
  assert.ok(state.notifications.some((row) => row.title[0] === "Your rank dropped by 2 places."));
  const sorted = M.ranking(state);
  assert.equal(sorted.length, 25);
  assert.equal(sorted.filter((row) => row.simulated).length, 24);
  assert.ok(sorted.every((row, index) => row.rank === index + 1));
});

test("the cat delivers one bilingual nudge every ten seconds, continuing after a full rotation", () => {
  const state = onboarded();
  state.user.chatPlanWeek = M.addDays(MON, 7);
  M.saveTask(state, task("Review slides", state.user.chatPlanWeek), NOW);
  state.notifications = [];
  const tasks = structuredClone(state.tasks);
  M.startDemo(state, NOW);
  const rank = M.ranking(state).find((row) => !row.simulated).rank;
  assert.deepEqual(M.tick(state, plus(9)), {});
  assert.ok(M.tick(state, plus(10)).updated);
  assert.equal(M.ranking(state).find((row) => !row.simulated).rank, rank + 2);
  assert.match(state.notifications[0].title[1], /被超过了/);
  assert.deepEqual(M.tick(state, plus(10)), {});
  state.preferences.paused = true;
  assert.deepEqual(M.tick(state, plus(20)), {});
  state.preferences.paused = false;
  state.preferences.optional = false;
  assert.deepEqual(M.tick(state, plus(30)), {});
  assert.equal(state.demo.index, 1);
  state.preferences.optional = true;
  for (let i = 4; i <= 11; i++) {
    assert.ok(M.tick(state, plus(i * 10)).updated);
    assert.deepEqual(M.tick(state, plus(i * 10 + 9)), {});
  }
  const notices = [...state.notifications].reverse();
  assert.deepEqual(notices.map((row) => row.type), ["rank", "task", "pressure", "cat", "rank", "task", "pressure", "cat", "rank"]);
  assert.ok(notices.every((row) => row.animatedCat && row.optional && !row.isRead && row.message.length === 2));
  assert.match(notices[1].message[0], /Review slides/);
  assert.notDeepEqual(notices[2].message, notices[6].message);
  assert.deepEqual(state.tasks, tasks);
  assert.equal(M.totalXP(state), 0);
});

test("normal reminders are limited to the period just ahead of a scheduled task", () => {
  const state = onboarded();
  M.saveTask(state, task("Morning", MON, "09:00", "09:02"), NOW);
  M.saveTask(state, task("Second", MON, "09:03", "10:00"), NOW);
  assert.deepEqual(M.tick(state, NOW), {});
  const soon = new Date("2026-11-16T08:45:00");
  assert.ok(M.tick(state, soon).updated);
  assert.deepEqual(M.tick(state, soon), {});
  assert.equal(state.notifications.filter((row) => row.title[0] === "Your next task starts soon").length, 1);
  assert.ok(M.tick(state, new Date("2026-11-16T09:00:00")).updated);
});
