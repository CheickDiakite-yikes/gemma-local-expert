async (page) => {
  async function sendTurn(text) {
    const assistantRows = page.locator(".message-row.assistant");
    const beforeCount = await assistantRows.count();
    await page.locator("#composer-input").fill(text);
    await page.locator("#send-button").click();
    await waitForTextIncludes(page.locator(".message-row.user").last(), text, "user echo");
    await waitForCount(assistantRows, beforeCount + 1, "assistant response row");
    const latestAssistant = assistantRows.last();
    await waitForNoLoading(latestAssistant);
    await waitForTextMatches(page.locator("#status-pill"), /ready/i, "ready status");
    return latestAssistant;
  }

  async function latestAssistantText() {
    const latestAssistant = page.locator(".message-row.assistant").last();
    await latestAssistant.locator(".message-content").waitFor({
      state: "visible",
      timeout: 30000,
    });
    return latestAssistant.innerText();
  }

  async function waitForCount(locator, expected, label) {
    await waitUntil(async () => (await locator.count()) === expected, `${label} count ${expected}`);
  }

  async function waitForNoLoading(locator) {
    await waitUntil(
      async () => (await locator.locator(".assistant-loading").count()) === 0,
      "assistant loading to finish",
    );
  }

  async function waitForTextIncludes(locator, expected, label) {
    await waitUntil(
      async () => (await locator.innerText()).includes(expected),
      `${label} includes ${expected}`,
    );
  }

  async function waitForTextMatches(locator, pattern, label) {
    await waitUntil(
      async () => pattern.test(await locator.innerText()),
      `${label} matches ${pattern}`,
    );
  }

  async function assertTextMatches(locator, pattern, label) {
    const text = await locator.innerText();
    assertMatches(text, pattern, label);
  }

  async function assertInputValueMatches(locator, pattern, label) {
    const value = await locator.inputValue();
    assertMatches(value, pattern, label);
  }

  function assertMatches(text, pattern, label) {
    if (!pattern.test(text)) {
      throw new Error(`Expected ${label} to match ${pattern}, got:\n${text}`);
    }
  }

  function assertNotMatches(text, pattern, label) {
    if (pattern.test(text)) {
      throw new Error(`Expected ${label} not to match ${pattern}, got:\n${text}`);
    }
  }

  async function waitUntil(predicate, label) {
    const deadline = Date.now() + 30000;
    let lastError = null;
    while (Date.now() < deadline) {
      try {
        if (await predicate()) {
          return;
        }
      } catch (error) {
        lastError = error;
      }
      await page.waitForTimeout(100);
    }
    throw new Error(`Timed out waiting for ${label}${lastError ? `: ${lastError.message}` : ""}`);
  }

  const baseUrl = page.url().replace(/\/chat\/?.*$/, "");
  const browserErrors = [];

  page.on("pageerror", (error) => browserErrors.push(error.message));
  page.on("console", (message) => {
    if (message.type() === "error") {
      browserErrors.push(message.text());
    }
  });

  await page.goto(`${baseUrl}/chat/`, { waitUntil: "domcontentloaded" });
  await page.setViewportSize({ width: 2048, height: 1208 });
  await page.locator("#composer-input").waitFor({ state: "visible", timeout: 30000 });
  const decorativeTopbarButtons = await page.locator(".topbar-actions button").count();
  if (decorativeTopbarButtons !== 0) {
    throw new Error(`Expected decorative topbar controls not to be buttons, found ${decorativeTopbarButtons}`);
  }
  const artifactPanel = page.locator("[data-artifact-panel]");
  await assertTextMatches(
    page.locator("#composer-model-pill"),
    /Mock local|Mock \+ OCR|Fallback local|Local model/i,
    "honest runtime capability pill",
  );

  await page.setViewportSize({ width: 390, height: 844 });
  await page.locator("#status-button").click();
  await waitUntil(
    async () =>
      (await page.locator("#status-menu").isVisible()) &&
      (await page.locator("#status-button").getAttribute("aria-expanded")) === "true",
    "mobile status menu opens with expanded state",
  );
  await page.keyboard.press("Escape");
  await waitUntil(
    async () =>
      (await page.locator("#status-menu").isHidden()) &&
      (await page.locator("#status-button").getAttribute("aria-expanded")) === "false",
    "mobile status menu closes with collapsed state",
  );
  await page.locator("#sidebar-toggle").click();
  await waitUntil(
    async () =>
      /is-open/.test(await page.locator("#sidebar").getAttribute("class")) &&
      (await page.locator("#sidebar-toggle").getAttribute("aria-expanded")) === "true",
    "mobile sidebar opens with expanded state",
  );
  await page.locator("#sidebar-backdrop").click();
  await waitUntil(
    async () =>
      !/is-open/.test(await page.locator("#sidebar").getAttribute("class")) &&
      (await page.locator("#sidebar-toggle").getAttribute("aria-expanded")) === "false",
    "mobile sidebar closes with collapsed state",
  );
  await page.evaluate(() => {
    Object.defineProperty(navigator, "mediaDevices", {
      configurable: true,
      value: {
        getUserMedia: () => Promise.reject(new DOMException("Permission denied", "NotAllowedError")),
      },
    });
  });
  await page.locator("#camera-button").click();
  const cameraSheet = page.locator("#camera-sheet");
  await cameraSheet.waitFor({ state: "visible", timeout: 30000 });
  await assertTextMatches(
    cameraSheet,
    /Capture for review[\s\S]*Unavailable[\s\S]*Use device capture/i,
    "minimal mobile camera unavailable sheet",
  );
  await page.screenshot({
    path: "output/playwright/friend-turns/camera-mobile-ui.png",
    fullPage: false,
  });
  await page.locator("#camera-close-button").click();
  await waitUntil(async () => await cameraSheet.isHidden(), "camera sheet closes");
  await page.setViewportSize({ width: 2048, height: 1208 });
  await page.locator("#file-input").setInputFiles("data/test-assets/field_supply_board.png");
  await assertTextMatches(
    page.locator("#attachment-strip"),
    /field_supply_board\.png[\s\S]*Local OCR after send[\s\S]*Queued for local review/i,
    "image attachment draft shows local OCR route",
  );
  await page.locator("[data-remove-attachment]").click();
  await waitUntil(
    async () => (await page.locator(".attachment-draft").count()) === 0,
    "attachment draft can be removed",
  );
  await page.locator("#file-input").setInputFiles("data/test-assets/field_supply_board.png");
  await assertTextMatches(
    page.locator("#attachment-strip"),
    /field_supply_board\.png[\s\S]*Queued for local review/i,
    "image attachment can be re-queued",
  );
  await sendTurn("Describe this attached supply board as local workspace context.");
  await artifactPanel.waitFor({ state: "visible", timeout: 30000 });
  await assertTextMatches(
    artifactPanel,
    /Files[\s\S]*Workspace files[\s\S]*field_supply_board\.png[\s\S]*Local OCR route/i,
    "artifact pane file workspace for image upload",
  );
  await page.screenshot({
    path: "output/playwright/friend-turns/artifact-files-ui.png",
    fullPage: false,
  });

  await sendTurn("What does local-first mean in this product, in plain English?");
  let reply = await latestAssistantText();
  assertMatches(reply, /run on this machine/i, "local-first direct explanation");
  assertMatches(reply, /weak internet/i, "local-first weak internet explanation");
  assertNotMatches(reply, /Yes\. We can just talk this through/i, "local-first reply should not be generic filler");

  await sendTurn(
    "Can we talk normally while you help me think through a field visit tomorrow? Keep it conversational.",
  );
  reply = await latestAssistantText();
  assertMatches(reply, /keep it conversational/i, "field visit conversational opening");
  assertMatches(reply, /rough shape of tomorrow/i, "field visit next prompt");

  await sendTurn("Teach me how to prepare oral rehydration solution in the field for a new volunteer.");
  reply = await latestAssistantText();
  assertMatches(reply, /clean water/i, "ORS concrete safety guidance");
  assertMatches(reply, /escalate quickly/i, "ORS escalation guidance");

  await sendTurn("Create a report summarizing the current field assistant architecture.");

  let canvas = page.locator(".approval-canvas-create_report").last();
  await canvas.waitFor({ state: "visible", timeout: 30000 });
  await assertTextMatches(
    canvas.locator(".approval-canvas-kicker"),
    /report draft/i,
    "report canvas kicker",
  );
  await assertInputValueMatches(
    canvas.locator('[data-approval-field="title"]'),
    /Field Assistant Architecture Report/i,
    "report canvas title",
  );
  await artifactPanel.waitFor({ state: "visible", timeout: 30000 });
  await assertTextMatches(
    artifactPanel,
    /Field Assistant Architecture Report[\s\S]*Local workspace preview/i,
    "right artifact workspace preview",
  );
  await assertTextMatches(
    artifactPanel.locator("[data-artifact-zoom]"),
    /Actual size/i,
    "artifact zoom button starts with useful action",
  );
  await assertTextMatches(
    artifactPanel.locator("[data-artifact-open]"),
    /Focus/i,
    "artifact focus action is honestly labeled",
  );
  await artifactPanel.locator('[data-artifact-mode="canvas"]').click();
  await assertTextMatches(
    artifactPanel,
    /Canvas draft[\s\S]*Field Assistant Architecture Report/i,
    "right artifact canvas surface",
  );
  await artifactPanel.locator('[data-artifact-mode="summary"]').click();
  await assertTextMatches(
    artifactPanel,
    /Local workspace preview/i,
    "right artifact summary surface",
  );
  await artifactPanel.locator("[data-artifact-zoom]").click();
  await waitUntil(
    async () => /is-actual-size/.test(await artifactPanel.getAttribute("class")),
    "artifact preview zoom toggle",
  );
  await assertTextMatches(
    artifactPanel.locator("[data-artifact-zoom]"),
    /Zoom to fit/i,
    "artifact zoom button offers return-to-fit action",
  );
  await artifactPanel.locator("[data-artifact-zoom]").click();
  await waitUntil(
    async () => !/is-actual-size/.test(await artifactPanel.getAttribute("class")),
    "artifact preview zoom reset",
  );
  await assertTextMatches(
    artifactPanel.locator("[data-artifact-zoom]"),
    /Actual size/i,
    "artifact zoom button resets to actual-size action",
  );
  await artifactPanel.locator("[data-artifact-open]").click();
  await waitUntil(
    async () => /is-attention/.test(await canvas.getAttribute("class")),
    "artifact open focuses canvas",
  );
  await canvas.locator('[data-approval-field="title"]').fill("Temporary title for revert check");
  await assertTextMatches(
    canvas.locator("[data-approval-draft-state]"),
    /^Edited$/,
    "canvas revert check marks local edits",
  );
  await canvas.locator("[data-approval-reset]").click();
  await assertInputValueMatches(
    canvas.locator('[data-approval-field="title"]'),
    /Field Assistant Architecture Report/i,
    "canvas revert restores original title",
  );
  await assertTextMatches(
    canvas.locator("[data-approval-draft-state]"),
    /^Unsaved$/,
    "canvas revert returns to clean pending state",
  );
  await canvas.locator("[data-approval-canvas-collapse]").first().click();
  await waitUntil(
    async () => /is-collapsed/.test(await canvas.getAttribute("class")),
    "inline canvas collapse",
  );
  await assertTextMatches(
    canvas.locator(".approval-canvas-collapsed-preview"),
    /Canvas tucked away[\s\S]*Field Assistant Architecture/i,
    "collapsed canvas preview",
  );
  await canvas.locator("[data-approval-canvas-collapse]").first().click();
  await waitUntil(
    async () => !/is-collapsed/.test(await canvas.getAttribute("class")),
    "inline canvas expand",
  );
  await page.screenshot({
    path: "output/playwright/friend-turns/artifact-split-ui.png",
    fullPage: false,
  });

  await canvas.locator('[data-approval-field="content"]').fill(
    [
      "Field Assistant Architecture Report",
      "",
      "Local canvas edit: keep this concise, plain, and human.",
      "",
      "We must make the strongest claims immediately.",
    ].join("\n"),
  );
  await assertTextMatches(
    canvas.locator("[data-approval-draft-state]"),
    /^Edited$/,
    "edited canvas state",
  );
  await artifactPanel.locator('[data-artifact-mode="canvas"]').click();
  await assertTextMatches(
    artifactPanel,
    /Canvas draft[\s\S]*Local canvas edit: keep this concise, plain, and human\./i,
    "right canvas pane reflects edited canvas",
  );
  await page.screenshot({
    path: "output/playwright/friend-turns/artifact-canvas-ui.png",
    fullPage: false,
  });
  await artifactPanel.locator(".artifact-canvas-actions [data-artifact-open]").click();
  await waitUntil(
    async () => /is-attention/.test(await canvas.getAttribute("class")),
    "canvas pane focus editor action",
  );
  await page.setViewportSize({ width: 390, height: 844 });
  await page.locator("#artifact-toggle").waitFor({ state: "visible", timeout: 30000 });
  await page.locator("#artifact-toggle").click();
  await waitUntil(
    async () => /is-mobile-open/.test(await artifactPanel.getAttribute("class")),
    "mobile artifact drawer opens",
  );
  await page.waitForTimeout(250);
  await assertTextMatches(
    artifactPanel,
    /Canvas draft[\s\S]*Local canvas edit: keep this concise, plain, and human\./i,
    "mobile artifact canvas drawer reflects edited canvas",
  );
  await page.screenshot({
    path: "output/playwright/friend-turns/mobile-artifact-ui.png",
    fullPage: false,
  });
  await artifactPanel.locator("[data-artifact-close]").click();
  await waitUntil(
    async () => !/is-mobile-open/.test(await artifactPanel.getAttribute("class")),
    "mobile artifact drawer closes",
  );
  await page.setViewportSize({ width: 2048, height: 1208 });
  await artifactPanel.locator('[data-artifact-mode="summary"]').click();

  await sendTurn(
    "Honestly I'm a little anxious. No checklist right now, just help me calm down for a second.",
  );
  reply = await latestAssistantText();
  assertMatches(
    reply,
    /take a breath|slow this down|one piece at a time/i,
    "supportive friend-like reply",
  );
  assertNotMatches(
    reply,
    /field assistant architecture report|bounded routing|approval|drafted a report/i,
    "supportive reply should not drag the draft back in",
  );

  canvas = page.locator(".approval-canvas-create_report").last();
  await canvas.waitFor({ state: "visible", timeout: 30000 });
  await assertTextMatches(
    canvas.locator("[data-approval-draft-state]"),
    /^Edited$/,
    "canvas state after supportive detour",
  );
  await assertInputValueMatches(
    canvas.locator('[data-approval-field="content"]'),
    /Local canvas edit: keep this concise, plain, and human\./,
    "canvas content after supportive detour",
  );

  await sendTurn(
    "Actually, forget the report for a second. What's the real difference between memory and context here?",
  );
  reply = await latestAssistantText();
  assertMatches(reply, /context is the live working set/i, "task-pivot context answer");
  assertMatches(reply, /memory is older distilled state/i, "task-pivot memory answer");
  assertNotMatches(
    reply,
    /bounded routing|approval|drafted a report/i,
    "task-pivot reply should not revive draft details",
  );

  canvas = page.locator(".approval-canvas-create_report").last();
  await canvas.waitFor({ state: "visible", timeout: 30000 });
  await assertTextMatches(
    canvas.locator("[data-approval-draft-state]"),
    /^Edited$/,
    "canvas state after task pivot",
  );

  await sendTurn("What title are you using for that draft?");
  reply = await latestAssistantText();
  assertMatches(reply, /Field Assistant Architecture Report/i, "return-to-draft title recall");
  await assertInputValueMatches(
    canvas.locator('[data-approval-field="title"]'),
    /Field Assistant Architecture Report/i,
    "canvas title after return-to-draft turn",
  );

  canvas = page.locator(".approval-canvas-create_report").last();
  const contentField = canvas.locator('[data-approval-field="content"]');
  const selectedPhrase = "We must make the strongest claims immediately.";
  await contentField.evaluate((element, phrase) => {
    const start = element.value.indexOf(phrase);
    if (start < 0) {
      throw new Error(`Could not find phrase to select: ${phrase}`);
    }
    element.focus();
    element.setSelectionRange(start, start + phrase.length);
    element.dispatchEvent(new Event("select", { bubbles: true }));
    element.dispatchEvent(new MouseEvent("mouseup", { bubbles: true }));
    element.dispatchEvent(new KeyboardEvent("keyup", { bubbles: true }));
  }, selectedPhrase);
  await assertTextMatches(
    canvas.locator("[data-canvas-selection-hint]"),
    /Selected \d+ words/i,
    "canvas selection hint",
  );

  await sendTurn("make this selection more neutral");
  reply = await latestAssistantText();
  assertMatches(reply, /selected draft text in the canvas/i, "selection edit confirmation");
  await assertInputValueMatches(
    contentField,
    /We should make the best-supported points soon\./,
    "neutralized selected text",
  );
  await assertInputValueMatches(
    contentField,
    /^(?![\s\S]*We must make the strongest claims immediately\.)[\s\S]*$/,
    "original selected text removed",
  );
  await assertTextMatches(
    canvas.locator("[data-document-edit-history]"),
    /Edit history[\s\S]*Made selection more neutral[\s\S]*We should make the best-supported points soon\./i,
    "visible document edit history",
  );
  const documentEditItems = await page.evaluate(async () => {
    const conversationsResponse = await fetch("/v1/conversations?limit=1");
    if (!conversationsResponse.ok) {
      throw new Error(`Could not list conversations: ${conversationsResponse.status}`);
    }
    const conversations = await conversationsResponse.json();
    if (!conversations.length) {
      throw new Error("No conversations found after browser scenario");
    }
    const itemsResponse = await fetch(`/v1/conversations/${conversations[0].id}/items`);
    if (!itemsResponse.ok) {
      throw new Error(`Could not list conversation items: ${itemsResponse.status}`);
    }
    const items = await itemsResponse.json();
    return items.filter((item) => item.kind === "document_edit");
  });
  if (documentEditItems.length !== 1) {
    throw new Error(`Expected one document_edit item, found ${documentEditItems.length}`);
  }
  assertMatches(
    documentEditItems[0].payload.after_text,
    /We should make the best-supported points soon\./,
    "document_edit item after_text",
  );
  assertMatches(
    documentEditItems[0].payload.visible_content_after,
    /Local canvas edit: keep this concise, plain, and human\./,
    "document_edit item preserved visible draft content",
  );
  await page.locator('[data-sidebar-command="plugins"]').click();
  await assertTextMatches(
    page.locator(".message-row.system").last(),
    /Plugins will live here/i,
    "plugins sidebar command feedback",
  );
  await page.locator('[data-sidebar-command="search"]').click();
  await waitUntil(
    async () => (await page.evaluate(() => document.activeElement?.id)) === "composer-input",
    "search command focuses composer",
  );
  await page.locator("#new-chat-button").click();
  await waitUntil(async () => await artifactPanel.isHidden(), "new chat hides artifact preview");

  await sendTurn("Create a checklist for final phone UX QA before shipping.");
  const checklistCanvas = page.locator(".approval-canvas-create_checklist").last();
  await checklistCanvas.waitFor({ state: "visible", timeout: 30000 });
  await artifactPanel.waitFor({ state: "visible", timeout: 30000 });
  await assertTextMatches(
    artifactPanel,
    /Checklist[\s\S]*final phone ux qa/i,
    "artifact checklist type card",
  );
  await assertTextMatches(
    artifactPanel.locator(".artifact-type-checklist"),
    /Confirm destination and route|Prepare translation and contact materials|Pack supplies and backup power/i,
    "rich checklist artifact preview",
  );
  await page.setViewportSize({ width: 390, height: 844 });
  await page.locator("#artifact-toggle").waitFor({ state: "visible", timeout: 30000 });
  await page.locator("#artifact-toggle").click();
  await waitUntil(
    async () => /is-mobile-open/.test(await artifactPanel.getAttribute("class")),
    "mobile checklist artifact drawer opens",
  );
  await page.waitForTimeout(250);
  await page.screenshot({
    path: "output/playwright/friend-turns/checklist-artifact-mobile-ui.png",
    fullPage: false,
  });
  await artifactPanel.locator("[data-artifact-close]").click();
  await waitUntil(
    async () => !/is-mobile-open/.test(await artifactPanel.getAttribute("class")),
    "mobile checklist artifact drawer closes",
  );
  await page.setViewportSize({ width: 2048, height: 1208 });

  if (browserErrors.length > 0) {
    throw new Error(`Browser errors during scenario:\n${browserErrors.join("\n")}`);
  }
}
