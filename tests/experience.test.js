const assert = require("node:assert/strict");
const { test } = require("node:test");
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
  assert.equal(M.openDashboard(state, NOW).checkXP, 2);
  assert.deepEqual(M.openDashboard(state, plus(1)), {});
  assert.equal(M.setCompletion(state, "Normal", MON, true, NOW).taskXP, 10);
  assert.deepEqual(M.setCompletion(state, "Normal", MON, true, NOW), {});
  let result = M.setCompletion(state, "High", MON, true, NOW);
  assert.equal(result.taskXP, 20);
  assert.equal(result.dayXP, 30);
  assert.equal(result.weekXP, 0);
  result = M.setCompletion(state, "Midweek", WED, true, NOW);
  assert.equal(result.dayXP, 30);
  assert.equal(result.weekXP, 100);
  assert.equal(M.totalXP(state), 202);
  assert.equal(M.level(M.totalXP(state)), 2);
  assert.equal(M.progress(M.totalXP(state)), 2);
  assert.ok(state.notifications.some((item) => item.title[0] === "Wow! You’re leveling up!"));
  state = JSON.parse(JSON.stringify(state));
  M.setCompletion(state, "Midweek", WED, false, NOW);
  M.setCompletion(state, "Midweek", WED, true, NOW);
  assert.equal(M.totalXP(state), 202);
  assert.equal(new Set(state.points.map((row) => row.uniqueRewardKey)).size, state.points.length);
  assert.equal(M.openDashboard(state, new Date("2026-11-17T08:00:00")).checkXP, 2);
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

test("notification playback paces the queue, respects preferences and emits all five types", () => {
  const state = onboarded();
  M.startDemo(state, NOW);
  assert.deepEqual(M.tick(state, plus(5)), {});
  assert.ok(M.tick(state, plus(6)).updated);
  assert.deepEqual(M.tick(state, plus(6)), {});
  state.preferences.paused = true;
  assert.deepEqual(M.tick(state, plus(12)), {});
  state.preferences.paused = false;
  state.preferences.optional = false;
  assert.deepEqual(M.tick(state, plus(18)), {});
  assert.equal(state.demo.index, 1);
  state.preferences.optional = true;
  for (let i = 2; i <= 8; i++) assert.ok(M.tick(state, plus(i * 6 + 6)).updated);
  assert.equal(state.notifications.length, 8);
  assert.equal(state.notifications.filter((row) => !row.isRead).length, 8);
  assert.deepEqual([...new Set(state.notifications.map((row) => row.type))].sort(), ["cat", "pressure", "rank", "task", "xp"]);
  assert.ok(state.notifications.some((row) => row.title[0] === "Schedule optimization"));
  assert.deepEqual(M.tick(state, plus(100)), {});
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
