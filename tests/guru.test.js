const assert = require("node:assert/strict");
const { test } = require("node:test");
const G = require("../ui/experience/guru.js");
const M = require("../ui/experience/model.js");

test("the HYPER daytime has 75 consecutive slots and meets the 23:45 sleep boundary", () => {
  const blocks = G.TEMPLATES.hyper.blocks;
  assert.equal(blocks[0].start, 300);
  assert.equal(blocks.length, 76);
  assert.equal(blocks.at(-1).start, 1425);
  assert.equal(G.clock(blocks.at(-1).end), "05:00");
  assert.ok(blocks.slice(0, -1).every((slot, index) =>
    slot.end - slot.start === 15 && blocks[index + 1].start === slot.end));
});

test("the free mountain demo triggers an ad, an offline conflict, a penalty and sleep warnings", () => {
  const state = M.newState();
  assert.ok(G.update(state, "mountain", "start").guruAd);
  const run = state.guru.mountain;
  assert.equal(run.offline, true);
  assert.equal(G.update(state, "mountain", "meditate").guruAlerts[0].title[0], "Check-in blocked");
  assert.equal(run.checkedIn, false);
  G.update(state, "mountain", "next");
  assert.equal(run.efficiency, 90);
  assert.equal(G.update(state, "mountain", "break").guruAlerts[0].title[0], "Break denied");
  for (let i = 0; i < 3; i++) G.update(state, "mountain", "next");
  for (let i = 0; i < 2; i++) assert.deepEqual(G.update(state, "mountain", "turn").guruAlerts, []);
  assert.equal(G.update(state, "mountain", "turn").guruAlerts[0].title[0], "Sleep discipline warning");
  assert.equal(run.turns, 3);
  assert.equal(M.totalXP(state), 0);
  assert.deepEqual(state.tasks, []);
});

test("simulated reconnect enables the App check-in and warns about the guru's offline rule", () => {
  const state = M.newState();
  G.update(state, "mountain", "start");
  assert.ok(G.update(state, "mountain", "network").guruAlerts.length);
  G.update(state, "mountain", "meditate");
  G.update(state, "mountain", "next");
  assert.equal(state.guru.mountain.checkedIn, true);
  assert.equal(state.guru.mountain.efficiency, 100);
});

test("simulated Premium unlock gates HYPER; playback starts on entering sleep and stops at the end", () => {
  const state = M.newState();
  assert.deepEqual(G.update(state, "hyper", "start"), {});
  G.update(state, "hyper", "unlock");
  G.update(state, "hyper", "start");
  for (let i = 0; i < 49; i++) G.update(state, "hyper", "next");
  assert.equal(G.update(state, "hyper", "next").guruAlerts[0].title[0], "50 task switches logged");
  assert.ok(G.update(state, "hyper", "sleep").guruVoice);
  assert.deepEqual(G.update(state, "hyper", "sleep"), {});
  assert.ok(G.update(state, "hyper", "next").guruStopVoice);
  assert.equal(state.guru.hyper.done, true);
});

test("the slacking sprint crosses its deadline and queues one alert per overdue task", () => {
  const state = M.newState();
  G.update(state, "slack", "unlock");
  G.update(state, "slack", "start");
  assert.equal(state.guru.slack.unlocked, true);
  for (let i = 0; i < 3; i++) G.update(state, "slack", "next");
  assert.equal(G.update(state, "slack", "next").guruAlerts[0].title[0], "Deadline approaching");
  const result = G.update(state, "slack", "next");
  assert.equal(result.guruAlerts.length, G.SLACK_TASKS.length);
  assert.equal(state.guru.slack.overdue, true);
  assert.deepEqual(G.update(state, "slack", "next"), {});
  for (const alert of result.guruAlerts) M.notify(state, alert.type, alert.title, alert.message, "guru", new Date(), true);
  assert.equal(state.notifications.length, 3);
  state.preferences.paused = true;
  M.notify(state, "task", ["Task overdue", "任务逾期"], ["Test", "测试"], "guru", new Date(), true);
  assert.equal(state.notifications.length, 3);
});

test("automatic course offers respect onboarding, reminders and the saved day", () => {
  let state = M.newState();
  const day = "2026-11-21";
  assert.deepEqual(G.takeCoursePromotion(state, day), {});
  state.user.onboardingCompleted = true;
  state.preferences.paused = true;
  assert.deepEqual(G.takeCoursePromotion(state, day), {});
  state.preferences.paused = false;
  state.preferences.optional = false;
  assert.deepEqual(G.takeCoursePromotion(state, day), {});
  state.preferences.optional = true;
  assert.equal(G.takeCoursePromotion(state, day).course, "hyper");
  state = JSON.parse(JSON.stringify(state));
  assert.deepEqual(G.takeCoursePromotion(state, day), {});
  assert.equal(G.takeCoursePromotion(state).course, "mountain");
  assert.deepEqual(G.takeCoursePromotion(state, day), {});
  assert.equal(G.takeCoursePromotion(state, "2026-11-22").course, "slack");
});
