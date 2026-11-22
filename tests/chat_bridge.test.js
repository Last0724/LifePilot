const assert = require("node:assert/strict");
const { test } = require("node:test");
const createRenderer = require("../ui/experience/chat_bridge.js");

function setup() {
  const root = {};
  const sent = [];
  let adapter;
  let mounts = 0;
  let unmounts = 0;
  const render = createRenderer({
    rootSelector: "[data-test-root]",
    mount(element, { chatAdapter }) {
      assert.equal(element, root);
      adapter = chatAdapter;
      mounts += 1;
      return () => { unmounts += 1; };
    },
  });
  return {
    get adapter() { return adapter; },
    counts: () => ({ mounts, unmounts }),
    sent,
    refresh: (chatResponse = null) => render({
      parentElement: { querySelector: () => root },
      data: { chatResponse },
      setTriggerValue(key, request) { sent.push({ key, request }); },
    }),
  };
}

test("only the matching response settles its request and rerenders retain the same cleanup", async () => {
  const bridge = setup();
  const cleanup = bridge.refresh();
  const first = bridge.adapter.handle_chat_message("first", null);
  assert.equal(bridge.sent[0].key, "chat_request");
  const sentFirst = bridge.sent[0].request;
  assert.deepEqual(sentFirst, {
    requestId: sentFirst.requestId, operation: "handle_chat_message", payload: { message: "first", state: null },
  });

  const firstResult = { reply: "Echo 1: first", state: { turn: 1 }, ready: false };
  const firstResponse = { requestId: sentFirst.requestId, ok: true, result: firstResult };
  assert.equal(bridge.refresh(firstResponse), cleanup);
  assert.deepEqual(await first, firstResult);

  const second = bridge.adapter.handle_chat_message("second", firstResult.state);
  const sentSecond = bridge.sent[1].request;
  assert.notEqual(sentSecond.requestId, sentFirst.requestId);
  assert.deepEqual(sentSecond.payload, { message: "second", state: firstResult.state });
  assert.equal(bridge.refresh(firstResponse), cleanup);
  const secondResult = { reply: "Echo 2: second", state: { turn: 2 }, ready: false };
  assert.equal(bridge.refresh({ requestId: sentSecond.requestId, ok: true, result: secondResult }), cleanup);
  assert.deepEqual(await second, secondResult);
  assert.deepEqual(bridge.counts(), { mounts: 1, unmounts: 0 });
  cleanup();
  cleanup();
  assert.deepEqual(bridge.counts(), { mounts: 1, unmounts: 1 });
});

test("an error rejects the matching Promise and a retry sends a new request", async () => {
  const bridge = setup();
  const cleanup = bridge.refresh();
  const first = bridge.adapter.handle_chat_message("/echo-error", null);
  const firstId = bridge.sent[0].request.requestId;
  bridge.refresh({ requestId: firstId, ok: false, error: "Echo failure" });
  await assert.rejects(first, /Echo failure/);

  const retry = bridge.adapter.handle_chat_message("/echo-error", null);
  const retryId = bridge.sent[1].request.requestId;
  assert.notEqual(retryId, firstId);
  const retryResult = { reply: "Echo 1: /echo-error", state: { turn: 1 }, ready: false };
  bridge.refresh({ requestId: retryId, ok: true, result: retryResult });
  assert.equal(await retry, retryResult);

  const confirmed = { goal: "A test goal" };
  const schedule = bridge.adapter.build_confirmed_schedule(retryResult.state, confirmed);
  assert.deepEqual(bridge.sent[2].request.payload, { state: retryResult.state, confirmed_fields: confirmed });
  assert.equal(bridge.sent[2].request.operation, "build_confirmed_schedule");
  cleanup();
  await assert.rejects(schedule, /component was closed/);
});
