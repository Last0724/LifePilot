(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory;
  else root.createLifePilotChatBridgeRenderer = factory;
})(globalThis, function createChatBridgeRenderer(options) {
  "use strict";

  const { rootSelector, mount, timeoutMs = 30000 } = options;
  const instances = new WeakMap();
  let nextRequest = 0;
  const requestPrefix = globalThis.crypto?.randomUUID?.() ?? Math.random().toString(36).slice(2);

  function createInstance(root, component) {
    let sendTrigger = component.setTriggerValue;
    let pending = null;

    function takeRequest(requestId) {
      if (!pending || pending.requestId !== requestId) return;
      const request = pending;
      pending = null;
      clearTimeout(request.timer);
      return request;
    }

    function request(operation, payload) {
      if (pending) return Promise.reject(new Error("A chat request is already pending."));
      const requestId = `${requestPrefix}:${++nextRequest}`;
      return new Promise((resolve, reject) => {
        const timer = setTimeout(() => {
          takeRequest(requestId)?.reject(new Error("The chat request timed out."));
        }, timeoutMs);
        pending = { requestId, resolve, reject, timer };
        try {
          sendTrigger("chat_request", { requestId, operation, payload });
        } catch (error) {
          takeRequest(requestId)?.reject(error);
        }
      });
    }

    const chatAdapter = {
      handle_chat_message: (message, state) => request("handle_chat_message", { message, state }),
      build_confirmed_schedule: (state, confirmed_fields) =>
        request("build_confirmed_schedule", { state, confirmed_fields }),
    };
    const unmount = mount(root, { chatAdapter });

    function update({ data, setTriggerValue }) {
      sendTrigger = setTriggerValue;
      if (!data?.chatResponse) return;
      const response = data.chatResponse;
      const request = takeRequest(response.requestId);
      if (!request) return;
      if (response.ok === true) request.resolve(response.result);
      else request.reject(new Error(response.error || "The chat request failed."));
    }

    function cleanup() {
      if (instances.get(root)?.cleanup !== cleanup) return;
      instances.delete(root);
      if (pending) takeRequest(pending.requestId).reject(new Error("The chat component was closed."));
      unmount();
    }

    return { update, cleanup };
  }

  return function render(component) {
    const root = component.parentElement.querySelector(rootSelector);
    let instance = instances.get(root);
    if (!instance) {
      instance = createInstance(root, component);
      instances.set(root, instance);
    }
    instance.update(component);
    return instance.cleanup;
  };
});
