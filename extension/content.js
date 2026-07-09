(() => {
  const TAG_RSP = "FLOWMETA_RSP";
  const TAG_MAIN = "FLOWMETA_MAIN";

  const VERSION = "0.1.18";
  if (window.__FLOWMETA_CONTENT_VERSION === VERSION) return;
  window.__FLOWMETA_CONTENT_VERSION = VERSION;

  chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
    if (message?.type !== "FLOWMETA_RUN_JOB") return;
    runFlowMetaJob(message.job)
      .then((result) => sendResponse(result))
      .catch((error) => sendResponse({ success: false, message: String(error?.message || error) }));
    return true;
  });

  async function runFlowMetaJob(job) {
    await wait(2200);
    if (isLoginPage()) return { success: false, message: "Facebook is not logged in. Please log in with this browser." };
    if (looksCheckpoint()) return { success: false, message: "Facebook checkpoint/security verification is required." };

    const kind = composerKind(job);
    const opened = await callMain("FIND_COMPOSER", { kind, labels: triggerPatterns(kind), attempts: 40 }, 90000);
    if (!opened?.found && !opened?.dialog) {
      return { success: false, message: getStatusMessage(opened?.reason || "trigger_not_found") };
    }

    let typed;
    try {
      typed = await callMain("TYPE_TEXT", { text: buildMessage(job) }, 90000);
    } catch (err) {
      return { success: false, message: String(err?.message || err || "Failed to type into Facebook composer.") };
    }
    if (!typed?.success) return { success: false, message: typed?.error || "Failed to type into Facebook composer." };

    await wait(1000);
    const submitted = await callMain("CLICK_POST", { kind }, 45000);
    if (!submitted?.success) return { success: false, message: submitted?.error || "Failed to click Post button." };

    await wait(2500);
    return {
      success: true,
      pending_review: looksPendingReview(),
      message: "Done.",
      post_url: location.href,
    };
  }

  function callMain(command, detail, timeoutMs) {
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error(`MAIN world timeout for ${command}`)), timeoutMs);
      const requestId = Date.now() + "_" + Math.random().toString(36).slice(2, 8);
      const handler = (event) => {
        const m = event.data;
        if (!m || typeof m !== "object" || m.tag !== TAG_MAIN) return;
        const p = m.payload || {};
        if (p.requestId !== requestId) return;
        window.removeEventListener("message", handler);
        clearTimeout(timer);
        if (p.error) reject(new Error(p.error));
        else resolve(p.result);
      };
      window.addEventListener("message", handler);
      window.postMessage({ tag: TAG_RSP, payload: { target: "main", command, detail, requestId } }, "*");
    });
  }

  function composerKind(job) {
    const type = String(job?.type || "");
    if (type.includes("group")) return "group";
    if (type.includes("share")) return "share";
    if (type.includes("external")) return "page";
    return "personal";
  }

  function triggerPatterns(kind) {
    const personal = [/nghi gi/i, /ban dang nghi/i, /on your mind/i, /what.*mind/i, /create post/i, /new post/i];
    const group = [/viet gi/i, /write something/i, /say something/i, /start a post/i, /create public post/i];
    const share = [/chia se/i, /share something/i, /share a post/i, /create post/i, /say something/i];
    if (kind === "personal") return personal;
    if (kind === "share" || kind === "page") return share;
    return group;
  }

  function buildMessage(job) {
    const message = String(job?.message || "");
    const link = String(job?.link || "");
    const sourceUrl = String(job?.source_url || "");
    if (sourceUrl) return `${message}\n\n${sourceUrl}`.trim();
    if (link) return `${message}\n\n${link}`.trim();
    return message;
  }

  function isLoginPage() {
    return Boolean(document.querySelector("input[name='email'], input#email"));
  }

  function looksCheckpoint() {
    const url = location.href.toLowerCase();
    if (/\/checkpoint\/|checkpoint\.facebook\.com|\/login\/checkpoint/.test(url)) return true;
    if (document.querySelector("input[name='approvals_code'], input[name='checkpoint_data'], input#approvals_code")) return true;
    const mainText = normalizeText(document.querySelector("[role='main']")?.textContent || document.body?.textContent || "");
    return /confirm your identity|enter the code|two-factor|two factor|xac nhan danh tinh|nhap ma|ma xac nhan|nhap ma xac thuc/.test(mainText);
  }

  function looksPendingReview() {
    return /pending|review|approval|duyet|cho phe duyet/.test(normalizeText(document.body?.textContent || ""));
  }

  function getStatusMessage(reason) {
    return {
      trigger_not_found: "Composer trigger not found on this page, or Facebook hasn't generated the page yet.",
    }[reason] || "Cannot open Facebook composer.";
  }

  function normalizeText(value) {
    return String(value || "")
      .replace(/[Đđ]/g, "d")
      .normalize("NFD")
      .replace(/[\u0300-\u036f]/g, "")
      .replace(/\s+/g, " ")
      .trim()
      .toLowerCase();
  }

  function wait(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }
})();
