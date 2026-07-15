const apiBaseInput = document.querySelector("#apiBase");
const accountSelect = document.querySelector("#account");
const statusEl = document.querySelector("#status");
const debugEl = document.querySelector("#debug");
const pillEl = document.querySelector("#pill");
const versionEl = document.querySelector("#version");
const connectBtn = document.querySelector("#connect");
const stopBtn = document.querySelector("#stop");
const reloadBtn = document.querySelector("#reload");
const authPanel = document.querySelector("#authPanel");
const connectorPanel = document.querySelector("#connectorPanel");
const identifierInput = document.querySelector("#identifier");
const passwordInput = document.querySelector("#password");
const loginBtn = document.querySelector("#login");
const retryBtn = document.querySelector("#retry");
const logoutBtn = document.querySelector("#logout");
const signedInUserEl = document.querySelector("#signedInUser");

init();

connectBtn.addEventListener("click", connect);
stopBtn.addEventListener("click", stop);
reloadBtn.addEventListener("click", loadAccounts);
loginBtn.addEventListener("click", login);
retryBtn.addEventListener("click", login);
logoutBtn.addEventListener("click", logout);
passwordInput.addEventListener("keydown", (event) => { if (event.key === "Enter") void login(); });
chrome.storage.onChanged.addListener(() => refreshDebug());

async function init() {
  versionEl.textContent = `v${chrome.runtime.getManifest().version}`;
  const state = await chrome.storage.local.get(["apiBase", "accountId", "accessToken", "authUser"]);
  apiBaseInput.value = state.apiBase || "http://localhost:8000";
  if (!state.accessToken) {
    showAuth();
    setStatus("Đăng nhập FlowMeta để kết nối extension.");
    await refreshDebug();
    return;
  }
  try {
    const me = await apiFetch("/api/auth/me");
    await chrome.storage.local.set({ authUser: me });
    showConnector(me);
    await loadAccounts(state.accountId || "");
  } catch (error) {
    await clearAuth();
    showAuth();
    setStatus(readableError(error));
    setPill("Cần đăng nhập", "err");
  }
  await refreshDebug();
}

async function login() {
  const identifier = identifierInput.value.trim();
  const password = passwordInput.value;
  if (!identifier || !password) {
    setStatus("Nhập email/tên đăng nhập và mật khẩu.");
    setPill("Thiếu thông tin", "err");
    return;
  }
  try {
    loginBtn.disabled = true;
    retryBtn.disabled = true;
    setPill("Đang đăng nhập", "run");
    const result = await apiFetch("/api/auth/login", {
      method: "POST",
      body: { username: identifier, password },
      skipAuth: true,
    });
    await chrome.storage.local.set({ accessToken: result.access_token, authUser: result.user });
    passwordInput.value = "";
    showConnector(result.user);
    await loadAccounts();
    setPill("Sẵn sàng", "ok");
  } catch (error) {
    setStatus(readableError(error));
    setPill("Đăng nhập lỗi", "err");
  } finally {
    loginBtn.disabled = false;
    retryBtn.disabled = false;
  }
}

async function logout() {
  await chrome.runtime.sendMessage({ type: "STOP_CONNECTOR" });
  await clearAuth();
  showAuth();
  setStatus("Đã đăng xuất khỏi FlowMeta.");
  setPill("Đã đăng xuất", "");
  await refreshDebug();
}

async function clearAuth() {
  await chrome.storage.local.remove(["accessToken", "authUser", "accountId"]);
}

function showAuth() {
  authPanel.classList.remove("hidden");
  connectorPanel.classList.add("hidden");
}

function showConnector(user) {
  authPanel.classList.add("hidden");
  connectorPanel.classList.remove("hidden");
  signedInUserEl.textContent = user?.username ? `FlowMeta: ${user.username}` : "Đã đăng nhập FlowMeta";
}

async function loadAccounts(preferredAccountId = "") {
  try {
    setStatus("Đang tải tài khoản Facebook...");
    const accounts = await apiFetch("/api/facebook-accounts");
    accountSelect.innerHTML = "";
    if (!accounts.length) {
      accountSelect.append(new Option("Chưa có tài khoản Facebook", ""));
      await chrome.storage.local.remove(["accountId"]);
      setStatus("Hãy nhập UID|TOKEN trong FlowMeta trước.");
      return;
    }
    for (const account of accounts) {
      accountSelect.append(new Option(`${account.name || account.uid} (${account.uid})`, account.id));
    }
    const stored = await chrome.storage.local.get(["accountId"]);
    const candidate = preferredAccountId || stored.accountId || "";
    const exists = accounts.some((account) => account.id === candidate);
    accountSelect.value = exists ? candidate : accounts[0].id;
    if (candidate && !exists) await chrome.storage.local.remove(["accountId"]);
    setStatus(candidate && !exists ? "Tài khoản đã lưu không còn tồn tại. Hãy chọn lại và bấm Kết nối." : "Chọn tài khoản và bấm Kết nối.");
  } catch (error) {
    if (error?.status === 401) {
      await clearAuth();
      showAuth();
    }
    const message = readableError(error);
    await chrome.storage.local.set({
      lastConnectorEvent: message,
      lastConnectorEventAt: new Date().toISOString(),
      lastConnectorBadge: "ERR",
    });
    setStatus(message);
    setPill("Lỗi", "err");
  }
}

async function connect() {
  const accountId = accountSelect.value;
  if (!accountId) {
    setStatus("Hãy chọn một tài khoản Facebook.");
    return;
  }
  const apiBase = apiBaseInput.value.replace(/\/$/, "");
  const current = await chrome.storage.local.get(["clientId"]);
  const clientId = current.clientId || crypto.randomUUID();
  await chrome.storage.local.set({ apiBase, accountId, clientId });
  try {
    setPill("Đang kết nối", "run");
    connectBtn.disabled = true;
    const result = await apiFetch("/api/extension/connect", {
      method: "POST",
      body: { account_id: accountId, client_id: clientId },
    });
    const session = await chrome.storage.local.get(["accessToken"]);
    if (!session.accessToken) throw new Error("Extension chưa nhận được phiên đăng nhập FlowMeta.");
    const worker = await chrome.runtime.sendMessage({
      type: "START_CONNECTOR",
      accessToken: session.accessToken,
    });
    const popupVersion = chrome.runtime.getManifest().version;
    if (!worker?.ok) throw new Error(worker?.error || "Không khởi động được connector nền.");
    if (worker.version !== popupVersion) {
      throw new Error(`Worker nền đang ở phiên bản ${worker.version || "cũ"}, popup là ${popupVersion}. Hãy Reload extension.`);
    }
    await chrome.storage.local.set({
      lastConnectorEvent: result.message || "Extension đã kết nối và đang chờ tác vụ.",
      lastConnectorEventAt: new Date().toISOString(),
      lastConnectorBadge: "ON",
    });
    setStatus("Extension đã kết nối và đang chờ tác vụ.");
    setPill("Trực tuyến", "ok");
  } catch (error) {
    if (error?.status === 401) {
      await clearAuth();
      showAuth();
    }
    const message = readableError(error);
    await chrome.storage.local.set({
      lastConnectorEvent: message,
      lastConnectorEventAt: new Date().toISOString(),
      lastConnectorBadge: "ERR",
    });
    setStatus(message);
    setPill("Lỗi", "err");
  } finally {
    connectBtn.disabled = false;
    await refreshDebug();
  }
}

async function stop() {
  await chrome.runtime.sendMessage({ type: "STOP_CONNECTOR" });
  await chrome.storage.local.remove(["accountId"]);
  setStatus("Đã dừng connector.");
  setPill("Đã dừng", "");
  await refreshDebug();
}

async function apiFetch(path, options = {}) {
  const state = await chrome.storage.local.get(["apiBase", "accessToken"]);
  const apiBase = (apiBaseInput.value || state.apiBase || "http://localhost:8000").replace(/\/$/, "");
  const headers = { "Content-Type": "application/json" };
  if (!options.skipAuth && state.accessToken) headers.Authorization = `Bearer ${state.accessToken}`;
  let response;
  try {
    response = await fetch(`${apiBase}${path}`, {
      method: options.method || "GET",
      headers,
      body: options.body ? JSON.stringify(options.body) : undefined,
    });
  } catch (error) {
    throw new Error("Không kết nối được backend FlowMeta. Kiểm tra Backend URL và server.", { cause: error });
  }
  if (!response.ok) {
    const raw = await response.text();
    let detail = raw;
    try { detail = JSON.parse(raw).detail || raw; } catch { /* Keep raw response. */ }
    const error = new Error(response.status === 401 ? "Phiên đăng nhập FlowMeta đã hết hạn. Hãy đăng nhập lại." : String(detail));
    error.status = response.status;
    throw error;
  }
  const text = await response.text();
  return text ? JSON.parse(text) : {};
}

async function refreshDebug() {
  const state = await chrome.storage.local.get(["lastConnectorEvent", "lastConnectorEventAt", "lastConnectorBadge"]);
  const badge = state.lastConnectorBadge || "IDLE";
  const event = state.lastConnectorEvent || "Chưa có sự kiện tác vụ.";
  const at = state.lastConnectorEventAt ? new Date(state.lastConnectorEventAt).toLocaleTimeString() : "";
  setPill(labelForBadge(badge), classForBadge(badge));
  debugEl.textContent = `${badge} | ${event}${at ? ` | ${at}` : ""}`;
}

function readableError(error) {
  return String(error?.message || error || "Đã xảy ra lỗi không xác định.");
}

function labelForBadge(badge) {
  if (badge === "OK" || badge === "ON") return "Trực tuyến";
  if (badge === "ERR") return "Lỗi";
  if (badge === "WAIT") return "Đang kết nối lại";
  if (badge === "RUN" || badge === "INJ" || badge === "TAB") return "Đang chạy";
  return "Chờ";
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
