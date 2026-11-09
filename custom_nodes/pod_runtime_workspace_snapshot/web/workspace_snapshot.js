import { app } from "../../../scripts/app.js";
import { api } from "../../../scripts/api.js";

// Captures live tabs BEFORE starting an HFF archive. Tab Manager owns its layout;
// this extension only backs up workflow graph contents and the existing settings.
const PREFIX = "/pod_runtime/workspace_snapshot";
const TOKEN_KEY = "pod-runtime-workspace-snapshot-token";
let opened = false;
let busy = false;

function store() {
  return app.extensionManager?.workflow ?? app.workflowManager ?? null;
}

function notify(kind, detail) {
  try {
    app.extensionManager?.toast?.add({
      severity: kind,
      summary: "Workspace Snapshots",
      detail: String(detail),
      life: 7000,
    });
  } catch {
    console.log("[Workspace Snapshots]", detail);
  }
}

function getToken() {
  let token = sessionStorage.getItem(TOKEN_KEY);
  if (!token) {
    token = window.prompt(
      "Workspace Snapshot access token\n\nRun this on the pod:\n" +
      "cat /workspace/.pod-state/workspace-snapshot/auth-token\n\n" +
      "Paste the token here (held in this browser tab only)."
    );
    if (!token) throw new Error("Snapshot token is required");
    token = token.trim();
    sessionStorage.setItem(TOKEN_KEY, token);
  }
  return token;
}

async function requestJson(path, options = {}) {
  const token = getToken();
  const response = await api.fetchApi(PREFIX + path, {
    ...options,
    headers: {
      "X-Workspace-Snapshot-Token": token,
      ...(options.headers || {}),
    },
    cache: "no-store",
  });
  let result;
  try {
    result = await response.json();
  } catch {
    throw new Error("The snapshot backend returned an invalid response");
  }
  if (!response.ok) {
    if (response.status === 401) sessionStorage.removeItem(TOKEN_KEY);
    throw new Error(result.error || "HTTP " + response.status);
  }
  return result;
}

function graphNow() {
  const graph = app.rootGraph ?? app.graph;
  const data = graph?.serialize?.();
  if (!data || !Array.isArray(data.nodes)) {
    throw new Error("Unable to serialize the current graph");
  }
  return JSON.parse(JSON.stringify(data));
}

function workflowName(workflow, index) {
  return String(workflow?.name || workflow?.filename || workflow?.path ||
    ("Untitled " + (index + 1))).replace(/^.*[\\/]/, "").replace(/\.json$/i, "");
}

async function captureOpenTabs(status) {
  const ws = store();
  const workflows = Array.from(ws?.openWorkflows ?? ws?.workflows ?? []);
  if (!ws || typeof ws.openWorkflow !== "function" || !workflows.length) {
    throw new Error("No available ComfyUI workflow tabs. Open a workflow and retry.");
  }

  const original = ws.activeWorkflow;
  const activeIndex = Math.max(0, workflows.indexOf(original));
  const tabs = [];
  const originalGraph = graphNow();

  // Switching tabs is sequential: ComfyUI has only one active graph canvas.
  // We preserve the current graph before any switch to protect unsaved edits.
  try {
    for (let i = 0; i < workflows.length; i++) {
      const workflow = workflows[i];
      status("Capturing tab " + (i + 1) + " of " + workflows.length);
      let graph;
      if (workflow === original) {
        graph = originalGraph;
      } else {
        const loaded = await ws.openWorkflow(workflow);
        if (loaded === false) throw new Error("ComfyUI could not open tab " + (i + 1));
        graph = graphNow();
      }
      tabs.push({
        name: workflowName(workflow, i),
        path: String(workflow?.path || ""),
        modified: Boolean(workflow?.isModified || workflow?.isTemporary),
        graph,
      });
    }
  } finally {
    if (original && ws.activeWorkflow !== original) {
      try {
        await ws.openWorkflow(original);
      } catch (error) {
        console.error("[Workspace Snapshots] Could not restore original tab", error);
        notify("warn", "Original active tab could not be automatically reselected.");
      }
    }
  }
  if (tabs.length !== workflows.length) {
    throw new Error("Not all tabs could be captured; no snapshot was started.");
  }
  return { tabs, activeIndex };
}

function make(tag, text, cls = "") {
  const el = document.createElement(tag);
  el.className = cls;
  el.textContent = text;
  return el;
}

function inputRow(label, value) {
  const wrap = make("label", "", "ws-field");
  const heading = make("span", label);
  const inp = document.createElement("input");
  inp.value = value;
  inp.autocomplete = "off";
  wrap.append(heading, inp);
  return { wrap, inp };
}

function checkRow(label, selected) {
  const wrap = make("label", "", "ws-check");
  const inp = document.createElement("input");
  inp.type = "checkbox";
  inp.checked = selected;
  wrap.append(inp, make("span", label));
  return { wrap, inp };
}

function addStyles() {
  if (document.getElementById("pod-workspace-snapshot-style")) return;
  const style = document.createElement("style");
  style.id = "pod-workspace-snapshot-style";
  style.textContent = [
    ".ws-snapshot-launcher{position:fixed;bottom:18px;right:18px;z-index:990;background:#344967;color:#fff;border:1px solid #7086ac;border-radius:22px;padding:9px 13px;cursor:pointer;font-size:12px;box-shadow:0 3px 12px #0005}",
    ".ws-snapshot-overlay{position:fixed;inset:0;z-index:99999;background:#0009;display:flex;align-items:center;justify-content:center;padding:16px;box-sizing:border-box}",
    ".ws-snapshot-panel{font-family:system-ui,sans-serif;box-sizing:border-box;width:min(500px,96vw);max-height:90vh;overflow:auto;background:#20242d;color:#f3f4f7;border:1px solid #606a7c;border-radius:12px;padding:20px;box-shadow:0 20px 60px #0009}",
    ".ws-snapshot-panel h2{margin:0 0 8px;font-size:20px}.ws-snapshot-panel p{font-size:12px;color:#acb6c8;margin:5px 0 14px}",
    ".ws-field{display:flex;flex-direction:column;gap:5px;margin:10px 0;font-size:12px}.ws-field input,.ws-field select{background:#151923;color:#fff;border:1px solid #667185;border-radius:6px;padding:9px;min-width:0}",
    ".ws-check{display:flex;align-items:center;gap:9px;font-size:12px;margin:8px 0}.ws-check input{width:16px;height:16px}",
    ".ws-snapshot-grid{display:grid;grid-template-columns:1fr 1fr;gap:8px}",
    ".ws-snapshot-actions{display:flex;flex-wrap:wrap;gap:8px;margin-top:16px}",
    ".ws-snapshot-actions button{background:#39445a;color:#fff;border:1px solid #6d7990;padding:9px 11px;border-radius:6px;cursor:pointer}",
    ".ws-snapshot-actions .primary{background:#316aaf}.ws-snapshot-actions button:disabled{opacity:.45;cursor:wait}",
    ".ws-snapshot-status{white-space:pre-wrap;word-break:break-word;background:#151a22;border-radius:6px;padding:10px;font-size:12px;max-height:150px;overflow:auto;margin-top:12px}",
    ".ws-snapshot-panel .ws-separator{border-top:1px solid #485162;margin-top:15px;padding-top:12px}",
  ].join("\n");
  document.head.appendChild(style);
}

async function restoreSession(session, status) {
  if (!session || session.schema !== 1 || !Array.isArray(session.tabs) || !session.tabs.length) {
    throw new Error("Invalid workspace session");
  }
  const count = session.tabs.length;
  if (!window.confirm("Restore " + count + " workflow tabs?\n" +
    "They will be opened as separate tabs; saved workflow files will not be overwritten.")) {
    return false;
  }
  const ws = store();
  const openedWorkflows = [];
  for (let i = 0; i < count; i++) {
    const entry = session.tabs[i];
    const graph = JSON.parse(JSON.stringify(entry.graph));
    if (!Array.isArray(graph?.nodes)) throw new Error("Invalid graph in tab " + (i + 1));
    if (globalThis.crypto?.randomUUID) graph.id = crypto.randomUUID();
    delete graph.changeTracker;
    delete graph.activeState;
    status("Restoring tab " + (i + 1) + " of " + count + ": " + entry.name);
    // ComfyUI's native duplicate/load path opens a new tab while preserving
    // the saved workflow file, including when this checkpoint had unsaved edits.
    const filename = "Restored - " + String(entry.name || "Untitled").replace(/[\\/]/g, "_");
    await app.loadGraphData(graph, true, true, filename);
    openedWorkflows.push(ws?.activeWorkflow);
  }
  const desired = session.activeIndex;
  if (ws && typeof ws.openWorkflow === "function" && openedWorkflows[desired]) {
    try {
      await ws.openWorkflow(openedWorkflows[desired]);
    } catch (error) {
      console.warn("[Workspace Snapshots] Active-tab selection failed", error);
    }
  }
  status("Restored " + count + " tabs. Existing saved workflow files are unchanged.");
  return true;
}

function openPanel() {
  if (opened) return;
  opened = true;
  addStyles();
  const overlay = make("div", "", "ws-snapshot-overlay");
  const panel = make("div", "", "ws-snapshot-panel");
  panel.setAttribute("role", "dialog");
  panel.setAttribute("aria-modal", "true");
  panel.setAttribute("aria-label", "ComfyUI Workspace Snapshots");
  const title = make("h2", "Workspace Snapshots");
  const explainer = make("p", "Capture live tabs (including unsaved edits), then optionally upload them with snapshot-pod.");
  const name = inputRow("Snapshot name", "comfy-workspace");
  const group = inputRow("Snapshot group", "comfy-workspace");
  const tag = inputRow("Tag", "workspace");
  const selected = {
    input: checkRow("Input images", true),
    output_gpu0: checkRow("output_gpu0", true),
    output: checkRow("output", false),
    workflows: checkRow("Saved workflows", true),
    tab_manager: checkRow("Tab Manager layout", true),
    settings: checkRow("ComfyUI settings", true),
  };
  const checks = make("div", "", "ws-snapshot-grid");
  Object.values(selected).forEach((entry) => checks.appendChild(entry.wrap));
  const controls = make("div", "", "ws-snapshot-actions");
  const captureButton = make("button", "Capture tabs locally");
  const uploadButton = make("button", "Capture + HF snapshot", "primary");
  const refreshButton = make("button", "Refresh saved sessions");
  const restoreButton = make("button", "Restore selected session");
  const closeButton = make("button", "Close");
  controls.append(captureButton, uploadButton);
  const divider = make("div", "", "ws-separator");
  const sessionsLabel = make("label", "", "ws-field");
  sessionsLabel.appendChild(make("span", "Saved session checkpoints"));
  const sessions = document.createElement("select");
  sessionsLabel.appendChild(sessions);
  const restoreControls = make("div", "", "ws-snapshot-actions");
  restoreControls.append(refreshButton, restoreButton, closeButton);
  const message = make("div", "Ready.", "ws-snapshot-status");
  message.setAttribute("aria-live", "polite");
  panel.append(title, explainer, name.wrap, group.wrap, tag.wrap, checks,
    controls, divider, sessionsLabel, restoreControls, message);
  overlay.appendChild(panel);
  document.body.appendChild(overlay);
  const buttons = [captureButton, uploadButton, refreshButton, restoreButton];

  function status(value) {
    message.textContent = String(value);
    message.scrollTop = message.scrollHeight;
  }
  function setBusy(value) {
    busy = value;
    for (const button of buttons) button.disabled = value;
  }
  function close() {
    if (busy) {
      notify("warn", "A snapshot operation is running. You can close after it finishes.");
      return;
    }
    opened = false;
    overlay.remove();
    window.removeEventListener("keydown", escapeKey);
  }
  function escapeKey(event) {
    if (event.key === "Escape") close();
  }
  window.addEventListener("keydown", escapeKey);
  closeButton.onclick = close;

  async function refresh() {
    const result = await requestJson("/sessions");
    sessions.replaceChildren();
    for (const entry of result.sessions || []) {
      const option = document.createElement("option");
      option.value = entry.id;
      option.textContent = entry.id + " (" + entry.tab_count + " tabs)";
      sessions.appendChild(option);
    }
    status((result.sessions || []).length + " saved session(s) available.");
  }

  async function capture(upload) {
    if (busy) return;
    setBusy(true);
    try {
      // Authenticate before switching any tabs.
      getToken();
      const captured = await captureOpenTabs(status);
      status("Saving " + captured.tabs.length + " tabs on the pod...");
      const local = await requestJson("/session", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(captured),
      });
      status("Session saved: " + local.id);
      if (upload) {
        const include = Object.fromEntries(
          Object.entries(selected).map(([key, row]) => [key, row.inp.checked])
        );
        const job = await requestJson("/snapshot", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            session_id: local.id,
            name: name.inp.value,
            group: group.inp.value,
            tag: tag.inp.value,
            include,
          }),
        });
        status("Snapshot upload started: " + job.id);
        while (true) {
          await new Promise((resolve) => setTimeout(resolve, 1700));
          const update = await requestJson("/jobs/" + encodeURIComponent(job.id));
          if (update.status === "completed") {
            status("Snapshot verified.\n" + (update.warnings || []).join("\n") +
              "\n" + (update.output || ""));
            notify("success", "Hugging Face snapshot completed.");
            break;
          }
          if (update.status === "failed") {
            throw new Error("Upload failed (exit " + update.exit_code + "):\n" + update.output);
          }
          status("Uploading workspace snapshot... " + update.status +
            "\nYou can leave this popup open while the pod uploads.");
        }
      }
      await refresh();
      sessions.value = local.id;
      notify("success", "Workspace tab checkpoint created.");
    } catch (error) {
      status("Error: " + (error?.message || String(error)));
      notify("error", error?.message || String(error));
    } finally {
      setBusy(false);
    }
  }

  captureButton.onclick = () => capture(false);
  uploadButton.onclick = () => capture(true);
  refreshButton.onclick = async () => {
    try {
      await refresh();
    } catch (error) {
      status("Error: " + error.message);
    }
  };
  restoreButton.onclick = async () => {
    if (!sessions.value || busy) return;
    setBusy(true);
    try {
      const data = await requestJson("/sessions/" + encodeURIComponent(sessions.value));
      const restored = await restoreSession(data, status);
      if (restored) notify("success", "Workspace tabs restored.");
    } catch (error) {
      status("Error: " + error.message);
      notify("error", error.message);
    } finally {
      setBusy(false);
    }
  };
  refreshButton.click();
}

app.registerExtension({
  name: "pod-runtime.workspace-snapshots",
  commands: [
    {
      id: "PodRuntime.OpenWorkspaceSnapshots",
      label: "Workspace Snapshots",
      function: openPanel,
    },
  ],
  menuCommands: [
    { path: ["Workspace"], commands: ["PodRuntime.OpenWorkspaceSnapshots"] },
  ],
  async setup() {
    addStyles();
    const button = make("button", "📷 Workspace Snapshot", "ws-snapshot-launcher");
    button.title = "Capture and restore all open workflow tabs";
    button.addEventListener("click", openPanel);
    document.body.appendChild(button);
  },
});
