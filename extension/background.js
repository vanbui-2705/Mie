const DEFAULT_API_BASE = "http://localhost:8000";
const POLL_DELAY_MS = 800;
const JOB_TIMEOUT_MS = 150000;

let polling = false;
let consecutiveFetchFailures = 0;
let runtimeAccessToken = "";

chrome.runtime.onInstalled.addListener(async () => {
  const state = await chrome.storage.local.get(["apiBase"]);
  if (!state.apiBase) await chrome.storage.local.set({ apiBase: DEFAULT_API_BASE });
  await resumePollingFromStorage();
});

chrome.runtime.onStartup.addListener(() => {
  void resumePollingFromStorage();
});

void resumePollingFromStorage();

async function resumePollingFromStorage() {
  const state = await chrome.storage.local.get(["accountId", "clientId", "accessToken"]);
  if (!state.accountId || !state.clientId || !state.accessToken) return;
  await startPolling(String(state.accessToken));
}

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message?.type === "START_CONNECTOR") {
    startPolling(message.accessToken).then(() => sendResponse({
      ok: true,
      version: chrome.runtime.getManifest().version,
    })).catch((error) => sendResponse({
      ok: false,
      error: String(error),
      version: chrome.runtime.getManifest().version,
    }));
    return true;
  }
  if (message?.type === "STOP_CONNECTOR") {
    polling = false;
    sendResponse({ ok: true });
    return true;
  }
});

async function startPolling(accessToken = "") {
  if (accessToken) runtimeAccessToken = accessToken;
  if (polling) return;
  polling = true;
  void pollLoop();
}

async function pollLoop() {
  while (polling) {
    try {
      const state = await getState();
      if (!state.accountId || !state.clientId || !state.accessToken) { polling = false; return; }
      await heartbeat(state);
      if (consecutiveFetchFailures > 0) { consecutiveFetchFailures = 0; await setConnectorStatus("Connected. Waiting for jobs.", "ON"); }
      const job = await pollJob(state);
      if (job) {
        await setConnectorStatus(`Running ${job.type || "job"} ${job.job_id || ""}`.trim(), "RUN");
        await runJob(state, job);
        await setConnectorStatus("Connected. Waiting for jobs.", "ON");
      }
    } catch (error) {
      consecutiveFetchFailures += 1;
      const message = error instanceof Error ? error.message : String(error);
      await setConnectorStatus(
        consecutiveFetchFailures >= 3 ? message : `Reconnecting... ${message}`,
        consecutiveFetchFailures >= 3 ? "ERR" : "WAIT"
      );
      console.warn("FlowMeta connector poll failed", error);
      if (error?.status === 401 || error?.status === 404) {
        polling = false;
        if (error?.status === 401) await chrome.storage.local.remove(["accessToken", "authUser"]);
        return;
      }
      await sleep(3000);
    }
    await sleep(POLL_DELAY_MS);
  }
}

async function heartbeat(state) {
  await apiFetch(state, "/api/extension/heartbeat", {
    method: "POST",
    body: { account_id: state.accountId, client_id: state.clientId },
  });
}

async function pollJob(state) {
  const params = new URLSearchParams({
    account_id: state.accountId,
    client_id: state.clientId,
    timeout: "20",
  });
  const data = await apiFetch(state, `/api/extension/jobs?${params.toString()}`);
  return data.job || null;
}

async function runJob(state, job) {
  const startUrl = shareJobStartUrl(job);
  const tab = await chrome.tabs.create({
    url: startUrl,
    active: false,
  });
  let closeTab = false;
  try {
    const preparedJob = await prepareJobMedia(state, job);
    const result = await withTimeout(runJobInTab(tab.id, preparedJob), JOB_TIMEOUT_MS, "FlowMeta extension job timeout");
    closeTab = Boolean(result?.success);
    await completeJob(state, job, result);
    await setConnectorStatus(
      result?.success ? "Job completed." : `Job failed: ${result?.message || "unknown error"}`,
      result?.success ? "OK" : "ERR"
    );
  } catch (error) {
    await completeJob(state, job, {
      success: false,
      message: error instanceof Error ? error.message : String(error),
    });
    await setConnectorStatus(error instanceof Error ? error.message : String(error), "ERR");
  } finally {
    if (closeTab) {
      try {
        await chrome.tabs.remove(tab.id);
      } catch {
        // The user or Facebook may already have closed/navigated the tab.
      }
    } else {
      try {
        await chrome.tabs.update(tab.id, { active: true });
      } catch {
        // Keep the original failure result if the tab no longer exists.
      }
    }
  }
}

function shareJobStartUrl(job) {
  const type = String(job?.type || "");
  const sourceUrl = String(job?.source_url || "");
  const targetUrl = String(job?.target_url || "");
  if (!type.startsWith("share_to_")) return targetUrl || "https://www.facebook.com/";
  if (job?.target_kind === "group" || type === "share_to_group") {
    return targetUrl || sourceUrl || "https://www.facebook.com/";
  }
  return sourceUrl || targetUrl || "https://www.facebook.com/";
}

async function prepareJobMedia(state, job) {
  const urls = Array.isArray(job.media_urls) ? job.media_urls.filter(Boolean) : [];
  if (!urls.length) return job;
  await setConnectorStatus(`Downloading ${urls.length} media file(s).`, "MED");
  const mediaFiles = [];
  for (const url of urls) {
    mediaFiles.push(await fetchMediaFile(state, String(url)));
  }
  return { ...job, media_files: mediaFiles };
}

async function fetchMediaFile(state, url) {
  const absoluteUrl = /^https?:\/\//i.test(url) ? url : `${state.apiBase}${url.startsWith("/") ? "" : "/"}${url}`;
  const response = await fetch(absoluteUrl);
  if (!response.ok) throw new Error(`Media download failed ${response.status}: ${absoluteUrl}`);
  const buffer = await response.arrayBuffer();
  const contentType = response.headers.get("content-type") || "application/octet-stream";
  const disposition = response.headers.get("content-disposition") || "";
  const name = filenameFromDisposition(disposition) || filenameFromUrl(absoluteUrl) || "flowmeta-media.bin";
  return {
    name,
    type: contentType.split(";")[0] || "application/octet-stream",
    base64: arrayBufferToBase64(buffer),
  };
}

function filenameFromDisposition(value) {
  const match = /filename\*?=(?:UTF-8''|")?([^";]+)/i.exec(value || "");
  return match ? decodeURIComponent(match[1].replace(/"/g, "")) : "";
}

function filenameFromUrl(value) {
  try {
    const pathname = new URL(value).pathname;
    return decodeURIComponent(pathname.split("/").filter(Boolean).pop() || "");
  } catch {
    return "";
  }
}

function arrayBufferToBase64(buffer) {
  const bytes = new Uint8Array(buffer);
  let binary = "";
  const chunkSize = 0x8000;
  for (let offset = 0; offset < bytes.length; offset += chunkSize) {
    const chunk = bytes.subarray(offset, offset + chunkSize);
    binary += String.fromCharCode(...chunk);
  }
  return btoa(binary);
}

async function runJobInTab(tabId, job) {
  await setConnectorStatus("Waiting for Facebook tab.", "TAB");
  await waitForTabReady(tabId);
  await waitForStableFacebookTab(tabId);
  let lastError = null;
  let sourceNavigationCompleted = false;
  for (let attempt = 1; attempt <= 3; attempt += 1) {
    await setConnectorStatus(attempt === 1 ? "Running Facebook job in page context." : `Facebook tab changed. Retrying ${attempt}/3.`, "RUN");
    await waitForTabReady(tabId);
    await waitForStableFacebookTab(tabId);
    try {
      const result = await runMainWorldJob(tabId, job);
      const navigationUrl = String(result?.navigation_url || "");
      if (navigationUrl && !sourceNavigationCompleted) {
        if (!isAllowedFacebookUrl(navigationUrl)) {
          return { success: false, message: "FlowMeta từ chối điều hướng tới source_url không thuộc facebook.com." };
        }
        sourceNavigationCompleted = true;
        await setConnectorStatus("Opening the Facebook source post before sharing.", "NAV");
        await chrome.tabs.update(tabId, { url: navigationUrl });
        await waitForTabReady(tabId);
        await waitForStableFacebookTab(tabId);
        continue;
      }
      if (navigationUrl) {
        return {
          success: false,
          message: result?.message || "Facebook không mở được bài nguồn để share.",
        };
      }
      return result;
    } catch (error) {
      lastError = error;
      if (!isTabNavigationError(error) || attempt === 3) throw error;
      await sleep(1400);
    }
  }
  throw lastError || new Error("Facebook tab changed before the job could run.");
}

function isAllowedFacebookUrl(value) {
  try {
    const url = new URL(String(value || ""));
    return url.protocol === "https:" && /(^|\.)facebook\.com$/i.test(url.hostname);
  } catch {
    return false;
  }
}


async function runMainWorldJob(tabId, job) {
  await chrome.scripting.executeScript({
    target: { tabId },
    world: "MAIN",
    files: ["content-main.js"],
  });
  await sleep(300);
  const executionId = crypto.randomUUID();
  const started = await chrome.scripting.executeScript({
    target: { tabId },
    world: "MAIN",
    func: (payload, jobExecutionId) => {
      if (typeof window.flowMetaRunFacebookJob !== "function") {
        return { started: false, message: "FlowMeta page runner is not installed." };
      }
      window.__FLOWMETA_JOB_RESULTS = window.__FLOWMETA_JOB_RESULTS || {};
      window.__FLOWMETA_JOB_RESULTS[jobExecutionId] = { done: false, startedAt: Date.now() };
      Promise.resolve(window.flowMetaRunFacebookJob(payload))
        .then((result) => {
          window.__FLOWMETA_JOB_RESULTS[jobExecutionId] = {
            done: true,
            result: result || { success: false, message: "FlowMeta page runner completed without a result." },
          };
        })
        .catch((error) => {
          window.__FLOWMETA_JOB_RESULTS[jobExecutionId] = {
            done: true,
            result: { success: false, message: String(error?.message || error || "FlowMeta page runner failed.") },
          };
        });
      return { started: true, executionId: jobExecutionId };
    },
    args: [job, executionId],
  });
  const startResult = started?.[0]?.result;
  if (!startResult?.started) throw new Error(startResult?.message || "FlowMeta page runner did not start.");

  const deadline = Date.now() + JOB_TIMEOUT_MS - 5000;
  while (Date.now() < deadline) {
    await sleep(700);
    const polled = await chrome.scripting.executeScript({
      target: { tabId },
      world: "MAIN",
      func: (jobExecutionId) => {
        const store = window.__FLOWMETA_JOB_RESULTS;
        if (!store || !store[jobExecutionId]) return null;
        const state = store[jobExecutionId];
        if (state.done) delete store[jobExecutionId];
        return state;
      },
      args: [executionId],
    });
    const state = polled?.[0]?.result;
    if (!state) throw new Error("FlowMeta job state lost after Facebook frame navigation.");
    if (state.done) return state.result || { success: false, message: "FlowMeta page runner completed without a result." };
  }
  throw new Error("FlowMeta page runner timed out while waiting for a result.");
}

async function completeJob(state, job, result) {
  await apiFetch(state, `/api/extension/jobs/${encodeURIComponent(job.job_id)}/complete`, {
    method: "POST",
    body: {
      ...result,
      account_id: state.accountId,
      client_id: state.clientId,
      run_id: job.run_id,
      task_item_id: job.task_item_id,
      share_target_id: job.share_target_id,
      log_index: job.log_index,
      uid: job.uid,
      action: job.action || actionForJob(job.type),
      target_url: job.target_url,
    },
  });
}

function actionForJob(type) {
  return {
    personal_post: "post_personal",
    group_post: "post_group",
    share_to_group: "share_group",
    share_to_external_page: "share_external_page",
  }[type] || type || "extension_job";
}

async function waitForTabReady(tabId) {
  const current = await chrome.tabs.get(tabId);
  if (current.status === "complete" && /^https:\/\/(www\.)?facebook\.com\//i.test(current.url || "")) {
    await sleep(500);
    return;
  }
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      chrome.tabs.onUpdated.removeListener(listener);
      reject(new Error("Facebook tab load timeout"));
    }, 60000);
    function listener(updatedTabId, info) {
      if (updatedTabId === tabId && info.status === "complete") {
        clearTimeout(timer);
        chrome.tabs.onUpdated.removeListener(listener);
        sleep(500).then(resolve);
      }
    }
    chrome.tabs.onUpdated.addListener(listener);
  });
}

async function waitForStableFacebookTab(tabId) {
  let lastUrl = "";
  let stableCount = 0;
  const started = Date.now();
  while (Date.now() - started < 15000) {
    const tab = await chrome.tabs.get(tabId);
    const url = tab.url || "";
    if (tab.status === "complete" && /^https:\/\/(www\.)?facebook\.com\//i.test(url)) {
      if (url === lastUrl) {
        stableCount += 1;
        if (stableCount >= 2) { await sleep(500); return; }
      } else {
        stableCount = 0;
        lastUrl = url;
      }
    }
    await sleep(300);
  }
}

function isTabNavigationError(error) {
  const message = String(error?.message || error || "");
  return /frame (with id \d+ )?was removed|frame with id \d+ was removed|no frame with id|execution context was destroyed|job state lost after facebook frame navigation|cannot access|tab closed|extension context invalidated|receiving end does not exist/i.test(message);
}

function withTimeout(promise, timeoutMs, message) {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error(message)), timeoutMs);
    promise.then((value) => { clearTimeout(timer); resolve(value); }).catch((error) => { clearTimeout(timer); reject(error); });
  });
}

async function apiFetch(state, path, options = {}) {
  if (!state.accessToken) {
    const error = new Error("Extension chưa nhận được phiên đăng nhập FlowMeta.");
    error.status = 401;
    throw error;
  }
  const res = await fetch(`${state.apiBase}${path}`, {
    method: options.method || "GET",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${state.accessToken}`,
      "X-FlowMeta-Extension-Version": chrome.runtime.getManifest().version,
    },
    body: options.body ? JSON.stringify(options.body) : undefined,
  });
  if (!res.ok) {
    const raw = await res.text();
    const error = new Error(res.status === 401
      ? "Phiên đăng nhập FlowMeta đã hết hạn. Mở extension để đăng nhập lại."
      : res.status === 404
        ? "Tài khoản đã chọn không còn tồn tại. Mở extension để chọn lại."
        : `API ${res.status}: ${raw}`);
    error.status = res.status;
    throw error;
  }
  const text = await res.text();
  return text ? JSON.parse(text) : {};
}

async function getState() {
  const data = await chrome.storage.local.get(["apiBase", "accountId", "clientId", "accessToken"]);
  return {
    apiBase: data.apiBase || DEFAULT_API_BASE,
    accountId: data.accountId || "",
    clientId: data.clientId || "",
    accessToken: runtimeAccessToken || data.accessToken || "",
  };
}

async function setConnectorStatus(message, badgeText = "") {
  const payload = {
    lastConnectorEvent: message,
    lastConnectorEventAt: new Date().toISOString(),
    lastConnectorBadge: badgeText,
  };
  await chrome.storage.local.set(payload);
  await chrome.action.setBadgeText({ text: badgeText.slice(0, 4) });
  await chrome.action.setBadgeBackgroundColor({ color: badgeText === "ERR" ? "#dc2626" : "#2563eb" });
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

void startPolling();
