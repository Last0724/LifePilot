const assert = require("node:assert/strict");
const { test } = require("node:test");
const M = require("../ui/experience/model.js");
const chat = require("../ui/experience/chat.js");
const createMock = require("./chat_mock.js");

const week = "2026-11-23";
const now = new Date("2026-11-22T09:00:00");
const mock = createMock({ t: (en) => en, weekStart: () => week, addDays: M.addDays });

async function throughConfirmation() {
  const first = await mock.handle_chat_message("I want to work on my slides before Thursday.", null);
  const second = await mock.handle_chat_message("Wednesday afternoon is booked.", first.state);
  const third = await mock.handle_chat_message("I usually wake around half past seven and take a lunch break.", second.state);
  return [first, second, third];
}

test("the chat fixture returns one reply per turn and exposes confirmation only after the follow-ups", async () => {
  const [first, second, third] = await throughConfirmation();
  assert.deepEqual([first.ready, second.ready, third.ready], [false, false, true]);
  assert.equal(new Set([first.reply, second.reply, third.reply]).size, 3);
  assert.equal(first.fields.commitments, undefined);
  assert.equal(second.fields.commitments[0].date, "2026-11-25");
  assert.equal(third.fields.wake, "07:30");
  assert.equal(typeof third.fields.rest, "string");
  const extra = await mock.handle_chat_message("I'd also like to leave my evenings free.", third.state);
  assert.equal(extra.ready, true);
  assert.equal(extra.fields, undefined);
  await assert.rejects(mock.build_confirmed_schedule(second.state, third.fields));
});

test("edited confirmation fields reach the fixture and import into the existing weekly planner", async () => {
  const [, , { fields, state }] = await throughConfirmation();
  fields.goal = "Prepare for demo day";
  fields.tasks[0].title = "Polish the edited slides";
  fields.commitments[0].startTime = "15:00";
  fields.commitments[0].endTime = "15:30";
  fields.wake = "08:00";
  const result = await mock.build_confirmed_schedule(state, fields);
  const planner = M.newState();
  planner.user.name = "Jamie";
  const imported = chat.importSchedule(M, planner, fields, result, now);
  assert.deepEqual(imported, { updated: true, firstDate: week });
  assert.equal(planner.user.name, "Jamie");
  assert.equal(planner.user.onboardingCompleted, true);
  assert.equal(planner.user.goal, "Prepare for demo day");
  assert.equal(planner.user.chatPlanWeek, week);
  assert.equal(planner.user.routine.wake, "08:00");
  const entries = M.occurrences(planner, M.weekDays(week));
  assert.equal(entries[0].title, "Polish the edited slides");
  assert.equal(entries[2].startTime, "15:00");
});

test("a conflicting plan is rejected atomically while a valid one preserves existing tasks and XP", async () => {
  const [, , { fields, state }] = await throughConfirmation();
  const planner = M.newState();
  planner.user.onboardingCompleted = true;
  M.openDashboard(planner, now);
  const existing = {
    title: "Existing commitment", date: week, startTime: "09:15", endTime: "10:00",
    category: "Work", priority: "High",
  };
  M.saveTask(planner, existing, now);
  const before = structuredClone(planner);
  const conflicting = await mock.build_confirmed_schedule(state, fields);
  assert.deepEqual(chat.importSchedule(M, planner, fields, conflicting, now), {
    error: { code: "overlap", title: "Existing commitment" },
  });
  assert.deepEqual(planner, before);
  const accepted = await mock.build_confirmed_schedule({ ...state, week: M.addDays(week, 7) }, { ...fields, commitments: [] });
  assert.equal(chat.importSchedule(M, planner, fields, accepted, now).updated, true);
  assert.deepEqual(planner.tasks[0], before.tasks[0]);
  assert.deepEqual(planner.points, before.points);
  assert.deepEqual(planner.competitors, before.competitors);
});

test("failed replies can be retried without duplicating messages, and generation errors keep edits", async () => {
  const log = { scrollTop: 0, scrollHeight: 0 };
  const panel = { isConnected: true, querySelector: (selector) => selector === "[data-chat-log]" ? log : null };
  const attempts = [];
  const received = [];
  const backendState = { sessionId: "opaque-token" };
  const instance = chat.create({
    adapter: {
      async handle_chat_message(message, state) {
        attempts.push({ message, state });
        if (attempts.length === 1) throw new Error("Connection closed.");
        return { reply: "The plan is ready to review.", state: backendState, ready: true, fields: { goal: "Goal" } };
      },
      async build_confirmed_schedule(state, fields) {
        received.push({ state, fields });
        if (received.length === 1) throw new Error("Backend unavailable.");
        return { entries: [] };
      },
    },
    t: (en) => en,
    e: (value) => String(value ?? ""),
    onPlan: () => "",
  });
  const submit = (kind, value) => panel.onsubmit({
    preventDefault() {},
    target: { dataset: { chatForm: kind }, elements: { message: { value } } },
  });
  instance.mount(panel);
  await submit("message", "I have a planning request.");
  assert.match(panel.innerHTML, /LifePilot couldn’t reply/);
  await panel.onclick({ target: { closest: () => ({ dataset: { chatAction: "retry" } }) } });
  assert.equal(panel.innerHTML.match(/I have a planning request\./g).length, 1);
  assert.equal(panel.innerHTML.match(/The plan is ready to review\./g).length, 1);
  assert.deepEqual(attempts, [
    { message: "I have a planning request.", state: null },
    { message: "I have a planning request.", state: null },
  ]);
  panel.oninput({ target: { name: "goal", value: "Edited goal", dataset: { chatField: "goal" } } });
  await submit("confirm");
  assert.match(panel.innerHTML, /Couldn’t generate your week/);
  assert.match(panel.innerHTML, /value="Edited goal"/);
  await submit("confirm");
  assert.deepEqual(received, [
    { state: backendState, fields: { goal: "Edited goal" } },
    { state: backendState, fields: { goal: "Edited goal" } },
  ]);
  assert.doesNotMatch(panel.innerHTML, /Couldn’t generate your week/);
});
