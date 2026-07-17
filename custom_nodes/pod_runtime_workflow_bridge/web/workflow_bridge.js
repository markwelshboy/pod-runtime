import { app } from "../../../scripts/app.js";
import { api } from "../../../scripts/api.js";

const ENDPOINT = "/pod_runtime/workflow_bridge/current";
const CLIENT_KEY = "pod-runtime-workflow-bridge-client-id";
const INTERVAL_MS = 1500;

function clientId() {
  let value = localStorage.getItem(CLIENT_KEY);
  if (!value) {
    value = globalThis.crypto?.randomUUID?.() || `client-${Date.now()}-${Math.random()}`;
    localStorage.setItem(CLIENT_KEY, value);
  }
  return value;
}

async function publishActiveWorkflow() {
  if (document.visibilityState !== "visible") return;
  if (!app?.graph || typeof app.graph.serialize !== "function") return;

  try {
    const workflow = app.graph.serialize();
    const activeWorkflow = app?.workflowManager?.activeWorkflow;
    const title = activeWorkflow?.name || activeWorkflow?.path || document.title || "active workflow";

    await api.fetchApi(ENDPOINT, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        workflow,
        client_id: clientId(),
        title,
        browser_url: window.location.href,
        published_at: new Date().toISOString(),
      }),
    });
  } catch (error) {
    console.debug("[pod-runtime workflow bridge] publish failed", error);
  }
}

app.registerExtension({
  name: "pod-runtime.workflow-bridge",
  async setup() {
    publishActiveWorkflow();
    window.setInterval(publishActiveWorkflow, INTERVAL_MS);
    window.addEventListener("focus", publishActiveWorkflow);
    document.addEventListener("visibilitychange", publishActiveWorkflow);
  },
});
