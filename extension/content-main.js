(() => {
  const VERSION = "0.1.18";
  if (window.__FLOWMETA_MAIN_VERSION === VERSION) return;
  window.__FLOWMETA_MAIN_VERSION = VERSION;

  const TAG = "FLOWMETA_MAIN";

  setTimeout(() => postBack({ command: "_READY", result: true, source: "main" }), 40);
  window.flowMetaRunFacebookJob = runFlowMetaJob;

  function postBack(payload) {
    window.postMessage({ tag: TAG, payload }, "*");
  }
  window.addEventListener("message", (event) => {
    const msg = event.data;
    if (!msg || typeof msg !== "object" || msg.tag !== "FLOWMETA_RSP") return;
    const p = msg.payload || msg;
    if (p.target !== "main" || p.responseTo || p.requestId === undefined || !p.command) return;
    resolveCommand(p.command, p.detail || {})
      .then((result) => postBack({ requestId: p.requestId, command: p.command, result }))
      .catch((error) => postBack({
        requestId: p.requestId,
        command: p.command,
        error: String(error?.message || error),
      }));
  });

  async function resolveCommand(command, detail) {
    switch (command) {
      case "PING": return { ready: true };
      case "FIND_COMPOSER": return await findComposer(detail);
      case "GET_TEXTBOX": return Boolean(findComposerTextbox());
      case "TYPE_TEXT": return await typeTextIntoComposer(detail);
      case "CLICK_POST": return await clickPostButton(detail);
      default: return { ok: true };
    }
  }

  async function findComposer(detail) {
    const kind = detail?.kind || "personal";
    const maxAttempts = detail?.attempts || 40;
    const existing = findPostDialog();
    if (existing) return { found: true, dialog: true };
    const trigger = await findComposerTrigger(maxAttempts, kind);
    if (!trigger) return { found: false, reason: "trigger_not_found" };
    clickLikeUser(trigger);
    const dialog = await waitFor(() => findPostDialog(), 12000);
    return { found: Boolean(dialog), triggerClicked: true, dialog: Boolean(dialog) };
  }

  async function findComposerTrigger(maxAttempts, kind) {
    const selectors = kind === "personal"
      ? "span"
      : "span, div[role='button'], button, div[aria-label]";
    const localPatterns = normalizedTriggerPatterns(kind);
    for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
      const scope = document.querySelector("[role='main']") || document.body;
      const candidates = [...scope.querySelectorAll(selectors)].filter(isVisible);
      for (const element of candidates) {
        if (isBadRegion(element)) continue;
        const text = searchableText(element);
        const matchesLocalPattern = localPatterns.some((pattern) => pattern.test(text));
        if (!matchesLocalPattern) continue;
        const clickable = closestClickable(element);
        if (clickable && isVisible(clickable) && !isBadRegion(clickable)) return clickable;
      }
      if (attempt === 0) window.scrollTo({ top: 0, behavior: "instant" });
      else if (attempt < 4) window.scrollBy({ top: 320, behavior: "instant" });
      else window.scrollBy({ top: 520, behavior: "instant" });
      await wait(350);
    }
    return null;
  }

  function normalizedTriggerPatterns(kind) {
    const personal = [/nghi gi/, /on your mind/];
    const group = [/viet gi/, /write something/, /say something/, /start a post/, /create public post/];
    const share = [/chia se/, /share something/, /share a post/, /create post/, /say something/];
    if (kind === "personal") return personal;
    if (kind === "share" || kind === "page") return share;
    return group;
  }

  function findPostDialog() {
    return [...document.querySelectorAll("div[role='dialog']")]
      .filter(isVisible)
      .filter((dialog) => !isBadRegion(dialog))
      .find((dialog) => findComposerTextbox(dialog)) || null;
  }

  function findComposerTextbox(root) {
    const scope = root || findPostDialog() || document.querySelector("[role='main']") || document.body;
    const boxes = [...scope.querySelectorAll("div[role='textbox'][contenteditable='true']")]
      .filter(isVisible)
      .filter((box) => !isBadRegion(box));
    return boxes.find((box) => box.closest("div[role='dialog']")) || boxes[0] || null;
  }

  function findPostButton(root, kind) {
    const scope = root || findPostDialog() || document;
    const exactAria = (kind === "share" || kind === "page"
      ? ["Share", "Chia sẻ", "Đăng", "Post"]
      : ["Đăng", "Post"]
    ).map(normalizeText);
    const ariaButton = [...scope.querySelectorAll("div[role='button'][aria-label], button[aria-label]")]
      .filter(isVisible)
      .filter((button) => !isBadRegion(button))
      .find((button) => {
        if (button.getAttribute("aria-disabled") === "true" || button.hasAttribute("disabled")) return false;
        return exactAria.includes(normalizeText(button.getAttribute("aria-label")));
      });
    if (ariaButton) return ariaButton;
    const labels = kind === "share" || kind === "page"
      ? [/^share$/, /^chia se$/, /^post$/, /^dang$/]
      : [/^post$/, /^dang$/];
    return [...scope.querySelectorAll("div[role='button'], button")]
      .filter(isVisible)
      .filter((button) => !isBadRegion(button))
      .find((button) => {
        if (button.getAttribute("aria-disabled") === "true" || button.hasAttribute("disabled")) return false;
        return labels.some((pattern) => pattern.test(searchableText(button)));
      }) || null;
  }

  async function typeTextIntoComposer(detail) {
    const text = String(detail?.text || "");
    const expected = normalizeText(text);
    if (!expected) return { success: true, committedLength: 0, method: "empty" };
    let textbox = findComposerTextbox();
    if (!textbox) {
      const opened = await findComposer({ kind: detail?.kind || "personal", attempts: 10 });
      if (!opened?.found) throw new Error("Composer textbox not found after opening composer.");
      textbox = await waitFor(() => findComposerTextbox(), 8000);
    }
    if (!textbox) throw new Error("Composer opened but textbox is missing.");
    activateTextbox(textbox);
    await wait(500);
    clearTextbox(textbox);
    await wait(200);
    document.execCommand("insertText", false, text);
    notifyComposerChanged(textbox);
    await wait(1000);
    const lastVisibleText = getComposerText(textbox);
    const normalizedVisible = normalizeText(lastVisibleText);
    const needle = expected.slice(0, Math.min(expected.length, 80));
    if (normalizedVisible.includes(needle)) {
      return { success: true, committedLength: lastVisibleText.length, method: "insertText" };
    }
    throw new Error("Text did not commit into Facebook composer. Visible length=" + lastVisibleText.length + ".");
  }

  async function runFlowMetaJob(job) {
    await wait(2200);
    if (isLoginPage()) return { success: false, message: "Facebook is not logged in. Please log in with this browser." };
    if (looksCheckpoint()) return { success: false, message: "Facebook checkpoint/security verification is required." };

    const kind = composerKind(job);
    const opened = await findComposer({ kind, attempts: 40 });
    if (!opened?.found && !opened?.dialog) {
      return { success: false, message: "Composer trigger not found on this page, or Facebook has not generated the page yet." };
    }

    try {
      const typed = await typeTextIntoComposer({ text: buildMessage(job), kind });
      if (!typed?.success) return { success: false, message: typed?.error || "Failed to type into Facebook composer." };
    } catch (error) {
      return { success: false, message: String(error?.message || error || "Failed to type into Facebook composer.") };
    }

    try {
      const media = await attachMediaFiles(job);
      if (!media?.success) return { success: false, message: media?.error || "Failed to attach media." };
    } catch (error) {
      return { success: false, message: String(error?.message || error || "Failed to attach media.") };
    }

    await wait(1000);
    try {
      const submitted = await clickPostButton({ kind });
      if (!submitted?.success) return { success: false, message: submitted?.error || "Failed to click Post button." };
    } catch (error) {
      return { success: false, message: String(error?.message || error || "Failed to click Post button.") };
    }

    await wait(2500);
    return {
      success: true,
      pending_review: kind === "group" && looksPendingReview(),
      message: "Done.",
      post_url: location.href,
    };
  }

  function composerKind(job) {
    const type = String(job?.type || "");
    if (type.includes("group")) return "group";
    if (type.includes("share")) return "share";
    if (type.includes("external")) return "page";
    return "personal";
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

  async function attachMediaFiles(job) {
    const mediaFiles = Array.isArray(job?.media_files) ? job.media_files : [];
    if (!mediaFiles.length) return { success: true, attached: 0 };
    const dialog = findPostDialog();
    if (!dialog) throw new Error("Composer dialog not found before media upload.");
    const input = findMediaInput(dialog);
    if (!input) throw new Error("Facebook media file input not found.");
    const files = mediaFiles.map(mediaPayloadToFile);
    const transfer = new DataTransfer();
    files.forEach((file) => transfer.items.add(file));
    input.files = transfer.files;
    input.dispatchEvent(new Event("input", { bubbles: true }));
    input.dispatchEvent(new Event("change", { bubbles: true }));
    const preview = await waitFor(() => hasMediaPreview(dialog), 60000);
    if (!preview) throw new Error("Media upload preview did not appear in Facebook composer.");
    await wait(1800);
    return { success: true, attached: files.length };
  }

  function findMediaInput(root) {
    const inputs = [...root.querySelectorAll("input[type='file']")].filter((input) => !input.disabled);
    if (!inputs.length) return null;
    return inputs.find((input) => {
      const accept = normalizeText(input.getAttribute("accept") || "");
      return accept.includes("image") || accept.includes("video") || accept.includes("photo");
    }) || inputs[0];
  }

  function mediaPayloadToFile(media) {
    const name = String(media?.name || "flowmeta-media.bin");
    const type = String(media?.type || "application/octet-stream");
    const base64 = String(media?.base64 || "");
    if (!base64) throw new Error(`Media file ${name} is empty.`);
    const binary = atob(base64);
    const bytes = new Uint8Array(binary.length);
    for (let index = 0; index < binary.length; index += 1) {
      bytes[index] = binary.charCodeAt(index);
    }
    return new File([bytes], name, { type });
  }

  function hasMediaPreview(root) {
    if (!root || !root.isConnected) return false;
    if (root.querySelector("img[src^='blob:'], video, [role='img']")) return true;
    const text = normalizeText(root.textContent || "");
    return /uploading|dang tai|processing|dang xu ly|photo|anh|video/.test(text);
  }

  async function clickPostButton(detail) {
    const kind = detail?.kind || "personal";
    const dialog = findPostDialog();
    const textbox = findComposerTextbox(dialog);
    const visibleText = normalizeText(getComposerText(textbox));
    if (!visibleText) throw new Error("Composer is empty, refusing to click Post.");
    const button = findPostButton(dialog, kind);
    if (!button) throw new Error("Post button not found.");
    clickLikeUser(button);
    return { success: true };
  }

  async function typeWholeText(_textbox, text) {
    document.execCommand("insertText", false, text);
  }

  async function typeLineByLine(textbox, text) {
    const lines = text.split(/\r?\n/);
    for (let index = 0; index < lines.length; index += 1) {
      if (index > 0) {
        document.execCommand("insertParagraph", false);
        textbox.dispatchEvent(new InputEvent("beforeinput", { bubbles: true, inputType: "insertParagraph", data: null }));
        await wait(40);
      }
      if (lines[index]) document.execCommand("insertText", false, lines[index]);
      await wait(Math.min(lines[index].length * 4, 350));
    }
  }

  async function typeCharacterByCharacter(_textbox, text) {
    for (let index = 0; index < text.length; index += 1) {
      const char = text[index];
      if (char === "\n") document.execCommand("insertParagraph", false);
      else document.execCommand("insertText", false, char);
      if (index % 12 === 0) await wait(16);
    }
  }

  async function typeByPasteEvent(textbox, text) {
    const data = new DataTransfer();
    data.setData("text/plain", text);
    textbox.dispatchEvent(new ClipboardEvent("paste", { bubbles: true, cancelable: true, clipboardData: data }));
    await wait(100);
    document.execCommand("insertText", false, text);
  }

  async function typeByDomFallback(textbox, text) {
    textbox.textContent = "";
    const lines = text.split(/\r?\n/);
    lines.forEach((line, index) => {
      if (index > 0) textbox.appendChild(document.createElement("br"));
      textbox.appendChild(document.createTextNode(line));
    });
  }

  function activateTextbox(textbox) {
    textbox.scrollIntoView?.({ block: "center", inline: "center" });
    clickLikeUser(textbox);
    textbox.focus();
    placeCaretAtEnd(textbox);
  }

  function clearTextbox(textbox) {
    activateTextbox(textbox);
    document.execCommand("selectAll", false);
    document.execCommand("delete", false);
    textbox.dispatchEvent(new InputEvent("input", { bubbles: true, inputType: "deleteContentBackward", data: null }));
  }

  function notifyComposerChanged(textbox) {
    textbox.dispatchEvent(new Event("input", { bubbles: true }));
    textbox.dispatchEvent(new Event("change", { bubbles: true }));
  }

  function getComposerText(textbox) {
    const element = textbox || findComposerTextbox();
    if (!element) return "";
    const offsetText = [...element.querySelectorAll("[data-offset-key]")]
      .map((node) => node.textContent || "")
      .join("");
    return (offsetText || element.textContent || "").trim();
  }

  function closestClickable(element) {
    return element.closest("div[role='button'], button, label[role='button']") || element;
  }

  function clickLikeUser(element) {
    const rect = element.getBoundingClientRect();
    const x = Math.max(rect.left + Math.min(rect.width / 2, 32), rect.left + 1);
    const y = Math.max(rect.top + Math.min(rect.height / 2, 18), rect.top + 1);
    const options = { bubbles: true, cancelable: true, view: window, clientX: x, clientY: y };
    element.dispatchEvent(new MouseEvent("mouseover", options));
    element.dispatchEvent(new MouseEvent("mousemove", options));
    element.dispatchEvent(new MouseEvent("mousedown", options));
    element.dispatchEvent(new MouseEvent("mouseup", options));
    element.click();
  }

  function placeCaretAtEnd(element) {
    const selection = window.getSelection();
    if (!selection) return;
    const range = document.createRange();
    range.selectNodeContents(element);
    range.collapse(false);
    selection.removeAllRanges();
    selection.addRange(range);
  }

  function searchableText(element) {
    if (!element) return "";
    return normalizeText([
      element.textContent || "",
      element.getAttribute("aria-label") || "",
      element.getAttribute("placeholder") || "",
      element.getAttribute("title") || "",
    ].join(" "));
  }

  function searchableTextFromParts(...parts) {
    return normalizeText(parts.join(" "));
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

  function isBadRegion(element) {
    for (let node = element; node && node !== document.body; node = node.parentElement) {
      const role = node.getAttribute?.("role") || "";
      const label = searchableTextFromParts(
        node.getAttribute?.("aria-label") || "",
        node.getAttribute?.("data-testid") || "",
        node.getAttribute?.("data-pagelet") || ""
      );
      if (role === "complementary") return true;
      if (/chat|messenger|contact|conversation|comment|reply|search|tim kiem|tin nhan|nhan tin/.test(label)) return true;
    }
    return false;
  }

  function isVisible(element) {
    if (!element || !(element instanceof Element)) return false;
    const style = window.getComputedStyle(element);
    if (style.visibility === "hidden" || style.display === "none" || Number(style.opacity) === 0) return false;
    const rect = element.getBoundingClientRect();
    return rect.width > 1 && rect.height > 1;
  }

  function wait(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }

  async function waitFor(factory, timeoutMs) {
    const started = Date.now();
    while (Date.now() - started < timeoutMs) {
      const value = factory();
      if (value) return value;
      await wait(250);
    }
    return null;
  }
})();
