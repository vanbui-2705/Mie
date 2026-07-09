const DEFAULT_API_BASE = "http://localhost:8000";
const POLL_DELAY_MS = 1500;
const JOB_TIMEOUT_MS = 150000;

let polling = false;
let consecutiveFetchFailures = 0;

chrome.runtime.onInstalled.addListener(() => {
  chrome.storage.local.set({ apiBase: DEFAULT_API_BASE });
});

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message?.type === "START_CONNECTOR") {
    startPolling().then(() => sendResponse({ ok: true })).catch((error) => sendResponse({ ok: false, error: String(error) }));
    return true;
  }
  if (message?.type === "STOP_CONNECTOR") {
    polling = false;
    sendResponse({ ok: true });
    return true;
  }
});

async function startPolling() {
  if (polling) return;
  polling = true;
  void pollLoop();
}

async function pollLoop() {
  while (polling) {
    try {
      const state = await getState();
      if (!state.accountId || !state.clientId) { polling = false; return; }
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
  const tab = await chrome.tabs.create({
    url: job.target_url || "https://www.facebook.com/",
    active: true,
  });
  try {
    const preparedJob = await prepareJobMedia(state, job);
    const result = await withTimeout(runJobInTab(tab.id, preparedJob), JOB_TIMEOUT_MS, "FlowMeta extension job timeout");
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
  }
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
  await setConnectorStatus("Running Facebook job in page context.", "RUN");
  try {
    return await runMainWorldJob(tabId, job);
  } catch (error) {
    if (!isTabNavigationError(error)) throw error;
    await setConnectorStatus("Facebook tab changed. Retrying once.", "RUN");
    await waitForTabReady(tabId);
    await waitForStableFacebookTab(tabId);
    return await runMainWorldJob(tabId, job);
  }
}


async function runMainWorldJob(tabId, job) {
  await chrome.scripting.executeScript({
    target: { tabId },
    world: "MAIN",
    files: ["content-main.js"],
  });
  await sleep(300);
  const results = await chrome.scripting.executeScript({
    target: { tabId },
    world: "MAIN",
    func: async (payload) => {
      if (typeof window.flowMetaRunFacebookJob !== "function") {
        return { success: false, message: "FlowMeta page runner is not installed." };
      }
      return await window.flowMetaRunFacebookJob(payload);
    },
    args: [job],
  });
  return results?.[0]?.result || { success: false, message: "FlowMeta page runner returned no result." };
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
    share_to_managed_page: "share_page_browser",
  }[type] || type || "extension_job";
}

async function waitForTabReady(tabId) {
  const current = await chrome.tabs.get(tabId);
  if (current.status === "complete" && /^https:\/\/(www\.)?facebook\.com\//i.test(current.url || "")) {
    await sleep(1200);
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
        sleep(1200).then(resolve);
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
        if (stableCount >= 3) { await sleep(1000); return; }
      } else {
        stableCount = 0;
        lastUrl = url;
      }
    }
    await sleep(500);
  }
}

function isTabNavigationError(error) {
  const message = String(error?.message || error || "");
  return /frame was removed|cannot access|tab closed|extension context invalidated|receiving end does not exist/i.test(message);
}

function withTimeout(promise, timeoutMs, message) {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error(message)), timeoutMs);
    promise.then((value) => { clearTimeout(timer); resolve(value); }).catch((error) => { clearTimeout(timer); reject(error); });
  });
}

async function apiFetch(state, path, options = {}) {
  const res = await fetch(`${state.apiBase}${path}`, {
    method: options.method || "GET",
    headers: { "Content-Type": "application/json" },
    body: options.body ? JSON.stringify(options.body) : undefined,
  });
  if (!res.ok) throw new Error(`API ${res.status}: ${await res.text()}`);
  const text = await res.text();
  return text ? JSON.parse(text) : {};
}

async function getState() {
  const data = await chrome.storage.local.get(["apiBase", "accountId", "clientId"]);
  return {
    apiBase: data.apiBase || DEFAULT_API_BASE,
    accountId: data.accountId || "",
    clientId: data.clientId || "",
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
