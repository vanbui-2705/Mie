(() => {
  const VERSION = "0.1.35";
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
    if (String(job?.type || "").startsWith("share_to_")) return await runFlowMetaShareJob(job);

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

  async function runFlowMetaShareJob(job) {
    const targetKind = String(job?.target_kind || "");
    const sourceUrl = String(job?.source_url || location.href);
    if (job?.source_url && !urlsReferToSamePost(location.href, sourceUrl) && !findSourcePostScope(sourceUrl)) {
      return {
        success: false,
        navigation_url: sourceUrl,
        message: `Cần mở bài nguồn ${sourceUrl} trước khi chạy native Share.`,
      };
    }
    const attemptedTriggers = new Set();
    let shareTrigger = null;
    let identityCheck = null;
    for (let attempt = 1; attempt <= 3; attempt += 1) {
      shareTrigger = await findShareTrigger(18, sourceUrl, attemptedTriggers);
      if (!shareTrigger) break;
      attemptedTriggers.add(shareTrigger.element);
      const previousSurfaces = new Set(findVisibleShareSurfaces());
      clickLikeUser(shareTrigger.element);
      await wait(1800);
      identityCheck = await verifyOpenedShareIdentity(sourceUrl, shareTrigger, previousSurfaces, 4500);
      if (identityCheck.success) break;
      await dismissWrongShareSurface();
      shareTrigger = null;
    }
    if (!shareTrigger) {
      const detail = identityCheck?.message
        ? ` ${identityCheck.message}`
        : ` Không anchor được article của bài nguồn sau khi Facebook chuyển tới ${location.href}.`;
      return { success: false, message: `Không tìm thấy đúng nút Share/Chia sẻ của bài nguồn.${detail}` };
    }

    const shareKind = targetKind === "group" ? "group" : "page";
    const optionClicked = await chooseShareDestinationType(shareKind);
    if (!optionClicked) {
      return { success: false, message: `Không thấy lựa chọn share sang ${shareKind === "group" ? "Group" : "Page"} trong menu Share của Facebook.` };
    }

    const targetName = String(job?.target_name || job?.target_url || "");
    const selectedTarget = await selectShareDestination(targetName, String(job?.target_url || ""), shareKind);
    if (!selectedTarget) {
      return { success: false, message: `Không thấy target URL ${job?.target_url || targetName || ""} trong danh sách native Share của Facebook. Kiểm tra tài khoản có quyền share tới Page/Group này.` };
    }

    const caption = String(job?.message || "");
    if (caption) {
      const textbox = await waitFor(() => findComposerTextbox(findPostDialog()) || findComposerTextbox(), 10000);
      if (textbox) {
        activateTextbox(textbox);
        await wait(300);
        document.execCommand("insertText", false, caption);
        notifyComposerChanged(textbox);
        await wait(700);
      }
    }

    const submitted = await clickShareSubmitButton();
    if (!submitted?.success) return submitted;
    await wait(3000);
    return {
      success: true,
      pending_review: shareKind === "group" && looksPendingReview(),
      message: "Đã gửi thao tác share thật qua Facebook UI.",
      post_url: sourceUrl,
    };
  }

  async function findShareTrigger(maxAttempts, sourceUrl, excluded = new Set()) {
    const patterns = [
      /^share$/,
      /^chia se$/,
      /send this to friends or post it/i,
      /gui noi dung nay cho ban be/i,
    ];
    for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
      const anchored = findSourcePostScope(sourceUrl);
      if (!anchored && facebookPostIdentityTokens(sourceUrl).length) {
        if (attempt === 0) window.scrollTo({ top: 0, behavior: "instant" });
        else window.scrollBy({ top: attempt < 6 ? 360 : 620, behavior: "instant" });
        await wait(300);
        continue;
      }
      const scope = anchored?.scope || document.querySelector("[role='main']") || document.body;
      const candidates = [...scope.querySelectorAll("div[role='button'], button, span, a[role='link'], [aria-label], [data-visualcompletion]")]
        .filter(isVisible)
        .filter((element) => !isBadRegion(element, { allowPostActions: true }))
        .filter((element) => !excluded.has(closestClickable(element)));
      const found = findBestShareElement(candidates, patterns);
      if (found) {
        const clickable = closestClickable(found);
        clickable.scrollIntoView?.({ block: "center", inline: "center" });
        await wait(400);
        return { element: clickable, scope, sourceVerified: Boolean(anchored?.verified) };
      }
      if (anchored) {
        anchored.scope.scrollIntoView?.({ block: "center", inline: "center" });
      } else if (attempt === 0) window.scrollTo({ top: 0, behavior: "instant" });
      else if (attempt < 6) window.scrollBy({ top: 360, behavior: "instant" });
      else window.scrollBy({ top: 620, behavior: "instant" });
      await wait(300);
    }
    return null;
  }

  function findSourcePostScope(sourceUrl) {
    const identityUrls = sourceIdentityUrls(sourceUrl);
    const visibleDialogs = [...document.querySelectorAll("div[role='dialog']")]
      .filter(isVisible)
      .filter((dialog) => !isBadRegion(dialog, { allowPostActions: true }));
    const matchingDialog = visibleDialogs.find((dialog) =>
      identityUrls.some((identityUrl) => elementContainsSourceIdentity(dialog, identityUrl))
    );
    if (matchingDialog) return { scope: matchingDialog, verified: true };

    const matchingLink = [...document.querySelectorAll("a[href]")]
      .filter(isVisible)
      .find((link) => identityUrls.some((identityUrl) => urlsReferToSamePost(link.href, identityUrl)));
    if (matchingLink) {
      return {
        scope: matchingLink.closest("[role='article'], article, div[role='dialog']") || matchingLink.parentElement,
        verified: true,
      };
    }

    const postDialog = visibleDialogs.find((dialog) => dialog.querySelector("[role='article'], article"));
    if (postDialog && isLikelyFacebookPostUrl(location.href)) {
      return { scope: postDialog, verified: true };
    }

    if (isLikelyFacebookPostUrl(location.href)) {
      const articles = [...document.querySelectorAll("[role='main'] [role='article'], [role='main'] article")].filter(isVisible);
      const matchingArticle = articles.find((article) =>
        identityUrls.some((identityUrl) => elementContainsSourceIdentity(article, identityUrl))
      );
      if (matchingArticle) return { scope: matchingArticle, verified: true };
      if (articles.length === 1) return { scope: articles[0], verified: true };
      const articlesWithShare = articles.filter((article) => articleContainsShareAction(article));
      if (articlesWithShare.length === 1) return { scope: articlesWithShare[0], verified: true };
    }
    return null;
  }

  function sourceIdentityUrls(sourceUrl) {
    const urls = [String(sourceUrl || "")].filter(Boolean);
    const currentUrl = String(location.href || "");
    if (currentUrl && isLikelyFacebookPostUrl(currentUrl)) urls.push(currentUrl);
    return [...new Set(urls)];
  }

  function isLikelyFacebookPostUrl(value) {
    try {
      const url = new URL(String(value || ""), location.href);
      if (!/(^|\.)facebook\.com$/i.test(url.hostname)) return false;
      if (facebookPostIdentityTokens(url.href).length) return true;
      return /\/(?:permalink|story|photo)\.php$/i.test(url.pathname);
    } catch {
      return false;
    }
  }

  function articleContainsShareAction(article) {
    const patterns = [/^share$/, /^chia se$/, /send this to friends or post it/i, /gui noi dung nay cho ban be/i];
    const candidates = [...article.querySelectorAll("div[role='button'], button, span, [aria-label]")]
      .filter(isVisible)
      .filter((element) => !isBadRegion(element, { allowPostActions: true }));
    return Boolean(findBestShareElement(candidates, patterns));
  }

  function findVisibleShareSurfaces() {
    return [...document.querySelectorAll("div[role='dialog'], div[role='menu']")]
      .filter(isVisible)
      .filter((surface) => !isBadRegion(surface, { allowPostActions: true, allowSearch: true }));
  }

  async function verifyOpenedShareIdentity(sourceUrl, trigger, previousSurfaces, timeoutMs) {
    const started = Date.now();
    while (Date.now() - started < timeoutMs) {
      const surfaces = findVisibleShareSurfaces();
      const openedSurfaces = surfaces.filter((surface) => !previousSurfaces.has(surface));
      const identitySurface = openedSurfaces.find((surface) =>
        sourceIdentityUrls(sourceUrl).some((identityUrl) => elementContainsSourceIdentity(surface, identityUrl))
      );
      if (identitySurface) return { success: true, method: "share_surface_identity" };

      const activeSurface = openedSurfaces[openedSurfaces.length - 1];
      if (activeSurface && trigger.sourceVerified && trigger.scope.contains(trigger.element)) {
        return { success: true, method: "anchored_source_post" };
      }
      await wait(250);
    }
    return {
      success: false,
      message: `Dialog Share vừa mở không khớp bài nguồn ${sourceUrl}; đã thử nút Share khác.`,
    };
  }

  async function dismissWrongShareSurface() {
    const target = document.activeElement || document.body;
    target.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", code: "Escape", bubbles: true, cancelable: true }));
    target.dispatchEvent(new KeyboardEvent("keyup", { key: "Escape", code: "Escape", bubbles: true, cancelable: true }));
    await wait(700);
  }

  function elementContainsSourceIdentity(element, sourceUrl) {
    if (!element) return false;
    const matchingLink = [...element.querySelectorAll("a[href]")]
      .some((link) => urlsReferToSamePost(link.href, sourceUrl));
    if (matchingLink) return true;
    const tokens = facebookPostIdentityTokens(sourceUrl);
    const text = searchableText(element);
    return tokens.some((token) => token.length >= 6 && text.includes(normalizeText(token)));
  }

  function urlsReferToSamePost(candidateUrl, sourceUrl) {
    const sourceTokens = facebookPostIdentityTokens(sourceUrl);
    const candidateTokens = facebookPostIdentityTokens(candidateUrl);
    if (sourceTokens.length && candidateTokens.length) {
      return sourceTokens.some((token) => candidateTokens.includes(token));
    }
    try {
      const source = new URL(String(sourceUrl || ""), location.href);
      const candidate = new URL(String(candidateUrl || ""), location.href);
      return normalizeFacebookPath(source.pathname) === normalizeFacebookPath(candidate.pathname);
    } catch {
      return false;
    }
  }

  function facebookPostIdentityTokens(value) {
    try {
      const url = new URL(String(value || ""), location.href);
      const tokens = [];
      for (const key of ["story_fbid", "fbid", "v"]) {
        const token = String(url.searchParams.get(key) || "").trim().toLowerCase();
        if (token) tokens.push(token);
      }
      const parts = normalizeFacebookPath(url.pathname).split("/").filter(Boolean);
      for (const marker of ["posts", "videos", "reel"]) {
        const index = parts.indexOf(marker);
        if (index >= 0 && parts[index + 1]) tokens.push(parts[index + 1]);
      }
      if (parts[0] === "share" && ["p", "r", "v"].includes(parts[1]) && parts[2]) {
        tokens.push(parts[2]);
      }
      return [...new Set(tokens)];
    } catch {
      return [];
    }
  }

  function normalizeFacebookPath(value) {
    return decodeURIComponent(String(value || ""))
      .toLowerCase()
      .replace(/\/+$/, "")
      .replace(/^\/(?:www\.)?facebook\.com/i, "");
  }

  function findBestShareElement(candidates, patterns) {
    const exact = candidates.find((element) => {
      const text = searchableText(element);
      return patterns.some((pattern) => pattern.test(text));
    });
    if (exact) return exact;
    const aria = candidates.find((element) => {
      const label = normalizeText([
        element.getAttribute?.("aria-label") || "",
        element.getAttribute?.("title") || "",
      ].join(" "));
      return /(^| )share( |$)|(^| )chia se( |$)/.test(label);
    });
    if (aria) return aria;
    return candidates.find((element) => {
      const text = searchableText(element);
      if (!/(^| )share( |$)|(^| )chia se( |$)/.test(text)) return false;
      const clickable = closestClickable(element);
      const label = searchableText(clickable);
      return !/comment|reply|binh luan|tra loi|send|gui rieng|messenger/.test(label);
    }) || null;
  }

  async function chooseShareDestinationType(kind) {
    const patterns = kind === "group"
      ? [
        /share to a group/,
        /share in a group/,
        /share to a group you/i,
        /share with a group/,
        /chia se vao nhom/,
        /chia se len nhom/,
        /chia se den nhom/,
        /chia se toi nhom/,
      ]
      : [/share to a page/, /share as a page/, /chia se len trang/, /chia se toi trang/];
    // Only inspect the native Share overlays. Searching the entire Facebook page
    // can click the global "Groups/Nhóm" navigation item and leave the share flow.
    const clicked = await clickFirstMatchingMenuItem(patterns, 12000, { overlayOnly: true });
    if (clicked) return true;
    const directDialog = findPostDialog();
    return Boolean(directDialog && kind === "page");
  }

  async function clickFirstMatchingMenuItem(patterns, timeoutMs, options = {}) {
    const started = Date.now();
    while (Date.now() - started < timeoutMs) {
      const roots = options.overlayOnly ? findVisibleShareSurfaces() : [document];
      const candidates = [...new Set(roots.flatMap((root) => [
        ...(root.matches?.("div[role='menuitem'], div[role='button'], button") ? [root] : []),
        ...root.querySelectorAll("div[role='menuitem'], div[role='button'], button, span"),
      ]))]
        .filter(isVisible)
        .filter((element) => !isBadRegion(element, options));
      const item = candidates.find((element) => patterns.some((pattern) => pattern.test(searchableText(element))));
      if (item) {
        clickLikeUser(closestClickable(item));
        await wait(1400);
        return true;
      }
      await wait(300);
    }
    return false;
  }

  async function selectShareDestination(targetName, targetUrl, kind) {
    const queries = shareTargetQueries(targetName, targetUrl);
    const urlKeys = shareTargetUrlKeys(targetUrl);
    if (!queries.length) return false;
    if (kind === "page") {
      await clickFirstMatchingMenuItem([
        /select a page/, /choose a page/, /page you manage/,
        /chon trang/, /lua chon trang/, /trang ban quan ly/,
      ], 3500, { allowSearch: true, overlayOnly: true });
    }
    const searchBox = await waitFor(() => findShareSearchInput(findActiveShareSurface()), 7000);
    const searchQuery = shareTargetSearchQuery(targetName, targetUrl);
    if (searchBox && searchQuery) {
      setEditableText(searchBox, searchQuery);
      const committed = await waitFor(() => editableValue(searchBox) === searchQuery, 2500);
      if (!committed) return false;
      await wait(1800);
    }
    const clicked = await clickShareTargetResult(queries, urlKeys, 15000);
    return Boolean(clicked);
  }

  function findShareSearchInput(root) {
    const surface = root && root !== document ? root : null;
    if (!surface) return null;
    const selectors = [
      "input[type='search']",
      "input[placeholder]",
      "div[role='textbox'][contenteditable='true']",
    ];
    for (const selector of selectors) {
      const found = [...surface.querySelectorAll(selector)]
        .filter(isVisible)
        .filter((element) => !isBadRegion(element, { allowSearch: true }))
        .find((element) => {
          if (element instanceof HTMLInputElement && element.type === "search") return true;
          const ownLabel = normalizeText([
            element.getAttribute?.("aria-label") || "",
            element.getAttribute?.("placeholder") || "",
            element.getAttribute?.("title") || "",
          ].join(" "));
          return /search|tim kiem/.test(ownLabel);
        });
      if (found) return found;
    }
    return null;
  }

  function editableValue(element) {
    if (element instanceof HTMLInputElement || element instanceof HTMLTextAreaElement) {
      return String(element.value || "").trim();
    }
    return String(element.textContent || "").trim();
  }

  async function clickShareTargetResult(queries, urlKeys, timeoutMs) {
    const needles = queries.map(normalizeText).filter(Boolean);
    const started = Date.now();
    let attempts = 0;
    while (Date.now() - started < timeoutMs) {
      const surface = findActiveShareSurface();
      const resultRoots = shareTargetResultRoots(surface);
      const candidates = [...new Set(resultRoots.flatMap((root) => [
        ...root.querySelectorAll("div[role='option'], div[role='radio'], div[role='menuitem'], div[role='button'], a[role='link'], li, span"),
      ]))]
        .filter(isVisible)
        .filter((element) => !isBadRegion(element, { allowSearch: true }));
      const nameItems = candidates
        .filter((element) => {
          const text = searchableText(element);
          return needles.some((needle) => shareTargetTextMatches(text, needle));
        })
        .sort((left, right) => searchableText(left).length - searchableText(right).length);
      const nameItem = nameItems[0] || null;
      const urlItem = candidates.find((element) => elementMatchesTargetUrl(element, urlKeys))
        || candidates.find((element) => elementInnerTextContainsSlug(element, urlKeys));
      const item = nameItem || urlItem;
      if (item) {
        clickLikeUser(closestClickable(item));
        await wait(1400);
        return true;
      }
      attempts += 1;
      if (attempts % 3 === 0) scrollShareTargetList(surface);
      await wait(300);
    }
    return false;
  }

  function shareTargetResultRoots(activeSurface) {
    const overlays = [...document.querySelectorAll("div[role='listbox'], div[role='menu'], div[role='dialog']")]
      .filter(isVisible)
      .filter((element) => !isBadRegion(element, { allowSearch: true }));
    return [...new Set([activeSurface, ...overlays, document].filter(Boolean))];
  }

  function shareTargetTextMatches(text, needle) {
    if (!text || !needle) return false;
    if (text === needle) return true;
    const remainder = text.slice(needle.length).trimStart();
    if (!text.startsWith(needle) || !remainder) return false;
    return /^(?:[•(\-|]|joined\b|member\b|public group\b|private group\b|nhom\b|thanh vien\b|da tham gia\b|\d)/.test(remainder);
  }

  async function clickShareSubmitButton() {
    const patterns = [
      /^share$/, /^share now(?: \([^)]*\))?$/, /^share post$/,
      /^chia se$/, /^chia se ngay(?: \([^)]*\))?$/, /^chia se bai viet$/, /^chia se den nhom$/, /^chia se ngay len nhom$/,
      /^post$/, /^post now$/, /^dang$/, /^dang ngay$/, /^dang len nhom$/, /^dang ngay len nhom$/, /^publish$/,
    ];
    const started = Date.now();
    let sawSubmitButton = false;
    while (Date.now() - started < 15000) {
      const match = findFinalShareSubmitButton(patterns);
      const button = match?.button || null;
      const surface = match?.surface || null;
      if (button) {
        sawSubmitButton = true;
        button.scrollIntoView?.({ block: "center", inline: "center" });
        button.focus?.();
        dispatchSubmitPointerEvents(button);
        clickLikeUser(button);
        const accepted = await waitFor(() => (
          !button.isConnected
          || (surface && !surface.isConnected)
          || !isVisible(button)
          || (surface && !isVisible(surface))
        ), 5000);
        if (accepted) return { success: true };
      }
      await wait(300);
    }
    return {
      success: false,
      message: sawSubmitButton
        ? "Đã thấy nút Đăng nhưng Facebook chưa nhận thao tác hoặc dialog chưa đóng."
        : "Không tìm thấy nút Đăng cuối cùng trong dialog Tạo bài viết.",
    };
  }

  function findFinalShareSubmitButton(patterns) {
    const candidates = [...document.querySelectorAll("div[role='button'], button, [aria-label][role='button']")]
      .filter(isVisible)
      .filter((button) => button.getAttribute("aria-disabled") !== "true" && !button.hasAttribute("disabled"))
      .map((button) => {
        const surface = button.closest("div[role='dialog']");
        const labels = [
          normalizeText(button.getAttribute?.("aria-label") || ""),
          normalizeText(button.getAttribute?.("title") || ""),
          normalizeText(button.textContent || ""),
        ].filter(Boolean);
        const surfaceText = normalizeText(surface?.textContent || "");
        const isComposerDialog = /tao bai viet|create post/.test(surfaceText);
        const exactAccessibleLabel = labels.slice(0, 2)
          .some((label) => patterns.some((pattern) => pattern.test(label)));
        const bottom = button.getBoundingClientRect().bottom;
        return {
          button,
          surface,
          labels,
          score: (surface && isVisible(surface) ? 10000 : 0)
            + (isComposerDialog ? 1000 : 0)
            + (exactAccessibleLabel ? 100 : 0)
            + Math.max(0, bottom),
        };
      })
      .filter(({ surface, labels }) => (
        surface
        && isVisible(surface)
        && labels.some((label) => patterns.some((pattern) => pattern.test(label)))
      ))
      .sort((left, right) => right.score - left.score);
    return candidates[0] || null;
  }

  function dispatchSubmitPointerEvents(element) {
    if (typeof PointerEvent !== "function") return;
    const rect = element.getBoundingClientRect();
    const options = {
      bubbles: true,
      cancelable: true,
      composed: true,
      pointerId: 1,
      pointerType: "mouse",
      isPrimary: true,
      clientX: rect.left + Math.max(1, rect.width / 2),
      clientY: rect.top + Math.max(1, rect.height / 2),
    };
    element.dispatchEvent(new PointerEvent("pointerover", options));
    element.dispatchEvent(new PointerEvent("pointerenter", { ...options, bubbles: false }));
    element.dispatchEvent(new PointerEvent("pointerdown", options));
    element.dispatchEvent(new PointerEvent("pointerup", options));
  }

  function shareTargetQuery(value) {
    const raw = String(value || "").trim();
    if (!raw) return "";
    try {
      const url = new URL(raw);
      const parts = url.pathname.split("/").filter(Boolean);
      return decodeURIComponent(parts[parts.length - 1] || parts[0] || raw);
    } catch {
      return raw.replace(/^https?:\/\/(www\.)?facebook\.com\//i, "").replace(/^groups\//i, "").split(/[/?#]/)[0] || raw;
    }
  }

  function shareTargetQueries(targetName, targetUrl) {
    return [...new Set([targetName, shareTargetQuery(targetUrl)]
      .map((value) => String(value || "").trim())
      .filter(Boolean))];
  }

  function shareTargetUrlKeys(targetUrl) {
    try {
      const url = new URL(String(targetUrl || ""));
      const parts = url.pathname.split("/").filter(Boolean).map((part) => decodeURIComponent(part).toLowerCase());
      const path = `/${parts.join("/")}`;
      return [...new Set([path, ...parts.filter((part) => part !== "groups")].filter((value) => value && value !== "/"))];
    } catch {
      return [];
    }
  }

  function elementMatchesTargetUrl(element, urlKeys) {
    if (!urlKeys.length) return false;
    const links = [];
    if (element.matches?.("a[href]")) links.push(element);
    links.push(...element.querySelectorAll?.("a[href]") || []);
    return links.some((link) => {
      try {
        const href = new URL(link.href, location.origin);
        const path = decodeURIComponent(href.pathname).replace(/\/$/, "").toLowerCase();
        return urlKeys.some((key) => key.startsWith("/") ? path === key || path.startsWith(`${key}/`) : path.split("/").includes(key));
      } catch {
        return false;
      }
    });
  }

  function scrollShareTargetList(surface) {
    const scrollable = [...surface.querySelectorAll("div")]
      .filter((element) => isVisible(element) && element.scrollHeight > element.clientHeight + 40)
      .sort((left, right) => right.clientHeight - left.clientHeight)[0];
    if (!scrollable) return;
    const next = scrollable.scrollTop + Math.max(180, Math.floor(scrollable.clientHeight * 0.7));
    scrollable.scrollTop = next >= scrollable.scrollHeight - scrollable.clientHeight ? 0 : next;
  }

  function findActiveShareSurface() {
    const dialogs = [...document.querySelectorAll("div[role='dialog']")].filter(isVisible);
    const searchDialog = [...dialogs].reverse().find((dialog) => {
      const fields = [...dialog.querySelectorAll("input[type='search'], input[placeholder], div[role='textbox'][contenteditable='true']")]
        .filter(isVisible);
      return fields.some((field) => {
        if (field instanceof HTMLInputElement && field.type === "search") return true;
        const label = searchableTextFromParts(
          field.getAttribute?.("aria-label") || "",
          field.getAttribute?.("placeholder") || "",
          field.getAttribute?.("title") || ""
        );
        return /search|tim kiem/.test(label);
      });
    });
    if (searchDialog) return searchDialog;
    return dialogs[dialogs.length - 1] || document;
  }

  function shareTargetSearchQuery(targetName, targetUrl) {
    const name = String(targetName || "").trim();
    if (name && !/^https?:\/\//i.test(name)) return name;
    return shareTargetQuery(targetUrl).replace(/[-_.]+/g, " ").trim();
  }

  function elementInnerTextContainsSlug(element, urlKeys) {
    if (!element || !urlKeys.length) return false;
    const text = searchableText(element);
    return urlKeys.some((key) => {
      const raw = String(key || "").replace(/^\/+|\/+$/g, "");
      if (!raw || raw.includes("/")) return false;
      const variants = [raw, raw.replace(/[-_.]+/g, " ")]
        .map(normalizeText)
        .filter((value) => value.length >= 3);
      return variants.some((needle) => text.includes(needle));
    });
  }

  function setEditableText(element, text) {
    if (element instanceof HTMLInputElement || element instanceof HTMLTextAreaElement) {
      element.focus();
      const prototype = element instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
      const setter = Object.getOwnPropertyDescriptor(prototype, "value")?.set;
      if (setter) setter.call(element, text);
      else element.value = text;
      element.dispatchEvent(new InputEvent("input", { bubbles: true, inputType: "insertText", data: text }));
      element.dispatchEvent(new Event("change", { bubbles: true }));
      return;
    }
    activateTextbox(element);
    document.execCommand("selectAll", false);
    document.execCommand("delete", false);
    document.execCommand("insertText", false, text);
    notifyComposerChanged(element);
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
    if (!visibleText && !hasMediaPreview(dialog)) throw new Error("Composer is empty, refusing to click Post.");
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
    return element.closest("div[role='option'], div[role='radio'], div[role='menuitem'], div[role='button'], button, label[role='button'], a[role='link'], li[role='option'], [tabindex='0']") || element;
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
      element.getAttribute?.("aria-label") || "",
      element.getAttribute?.("placeholder") || "",
      element.getAttribute?.("title") || "",
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

  function isBadRegion(element, options = {}) {
    for (let node = element; node && node !== document.body; node = node.parentElement) {
      const role = node.getAttribute?.("role") || "";
      const label = searchableTextFromParts(
        node.getAttribute?.("aria-label") || "",
        node.getAttribute?.("data-testid") || "",
        node.getAttribute?.("data-pagelet") || ""
      );
      if (role === "complementary") return true;
      const badPattern = options.allowSearch
        ? (options.allowPostActions
          ? /chat|messenger|contact|conversation|tin nhan|nhan tin/
          : /chat|messenger|contact|conversation|comment|reply|tin nhan|nhan tin/)
        : (options.allowPostActions
          ? /chat|messenger|contact|conversation|search|tim kiem|tin nhan|nhan tin/
          : /chat|messenger|contact|conversation|comment|reply|search|tim kiem|tin nhan|nhan tin/);
      if (badPattern.test(label)) return true;
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
