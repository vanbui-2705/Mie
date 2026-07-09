const apiBaseInput = document.querySelector("#apiBase");
const accountSelect = document.querySelector("#account");
const statusEl = document.querySelector("#status");
const debugEl = document.querySelector("#debug");
const pillEl = document.querySelector("#pill");
const versionEl = document.querySelector("#version");
const connectBtn = document.querySelector("#connect");
const stopBtn = document.querySelector("#stop");
const reloadBtn = document.querySelector("#reload");

init();

connectBtn.addEventListener("click", connect);
stopBtn.addEventListener("click", stop);
reloadBtn.addEventListener("click", loadAccounts);
chrome.storage.onChanged.addListener(() => refreshDebug());

async function init() {
  versionEl.textContent = `v${chrome.runtime.getManifest().version}`;
  const state = await chrome.storage.local.get(["apiBase", "accountId"]);
  apiBaseInput.value = state.apiBase || "http://localhost:8000";
  await loadAccounts();
  if (state.accountId) accountSelect.value = state.accountId;
  await refreshDebug();
}

async function loadAccounts() {
  try {
    setStatus("Loading accounts...");
    const accounts = await apiFetch("/api/facebook-accounts");
    accountSelect.innerHTML = "";
    if (!accounts.length) {
      accountSelect.append(new Option("No account in FlowMeta", ""));
      setStatus("Import UID|TOKEN in FlowMeta first.");
      return;
    }
    for (const account of accounts) {
      accountSelect.append(new Option(`${account.name || account.uid} (${account.uid})`, account.id));
    }
    setStatus("Choose account and connect.");
  } catch (error) {
    setStatus(String(error.message || error));
    setPill("ERR", "err");
  }
}

async function connect() {
  const accountId = accountSelect.value;
  if (!accountId) {
    setStatus("Choose an account first.");
    return;
  }
  const apiBase = apiBaseInput.value.replace(/\/$/, "");
  const current = await chrome.storage.local.get(["clientId"]);
  const clientId = current.clientId || crypto.randomUUID();
  await chrome.storage.local.set({ apiBase, accountId, clientId });
  try {
    setPill("Connecting", "run");
    connectBtn.disabled = true;
    const result = await apiFetch("/api/extension/connect", {
      method: "POST",
      body: { account_id: accountId, client_id: clientId },
    });
    await chrome.storage.local.set({
      lastConnectorEvent: result.message || "Connected. Waiting for jobs.",
      lastConnectorEventAt: new Date().toISOString(),
      lastConnectorBadge: "ON",
    });
    await chrome.runtime.sendMessage({ type: "START_CONNECTOR" });
    setStatus(result.message || "Connected.");
    setPill("Online", "ok");
  } catch (error) {
    setStatus(String(error.message || error));
    setPill("Error", "err");
  } finally {
    connectBtn.disabled = false;
    await refreshDebug();
  }
}

async function stop() {
  await chrome.runtime.sendMessage({ type: "STOP_CONNECTOR" });
  await chrome.storage.local.remove(["accountId"]);
  setStatus("Stopped.");
  setPill("Stopped", "");
  await refreshDebug();
}

async function apiFetch(path, options = {}) {
  const apiBase = apiBaseInput.value.replace(/\/$/, "");
  const response = await fetch(`${apiBase}${path}`, {
    method: options.method || "GET",
    headers: { "Content-Type": "application/json" },
    body: options.body ? JSON.stringify(options.body) : undefined,
  });
  if (!response.ok) throw new Error(`API ${response.status}: ${await response.text()}`);
  const text = await response.text();
  return text ? JSON.parse(text) : {};
}

async function refreshDebug() {
  const state = await chrome.storage.local.get(["lastConnectorEvent", "lastConnectorEventAt", "lastConnectorBadge"]);
  const badge = state.lastConnectorBadge || "IDLE";
  const event = state.lastConnectorEvent || "No job event yet.";
  const at = state.lastConnectorEventAt ? new Date(state.lastConnectorEventAt).toLocaleTimeString() : "";
  setPill(labelForBadge(badge), classForBadge(badge));
  debugEl.textContent = `${badge} | ${event}${at ? ` | ${at}` : ""}`;
}

function labelForBadge(badge) {
  if (badge === "OK" || badge === "ON") return "Online";
  if (badge === "ERR") return "Error";
  if (badge === "WAIT") return "Reconnecting";
  if (badge === "RUN" || badge === "INJ" || badge === "TAB") return "Running";
  return "Idle";
}

function classForBadge(badge) {
  if (badge === "OK" || badge === "ON") return "ok";
  if (badge === "ERR") return "err";
  if (badge === "WAIT" || badge === "RUN" || badge === "INJ" || badge === "TAB") return "run";
  return "";
}

function setStatus(message) {
  statusEl.textContent = message;
}

function setPill(label, className) {
  pillEl.textContent = label;
  pillEl.className = `pill ${className || ""}`.trim();
}
