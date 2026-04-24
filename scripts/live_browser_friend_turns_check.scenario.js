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
  await page.locator("#composer-input").waitFor({ state: "visible", timeout: 30000 });

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

  await sendTurn(
    "Honestly I'm a little anxious. No checklist right now, just help me calm down for a second.",
  );
  let reply = await latestAssistantText();
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

  if (browserErrors.length > 0) {
    throw new Error(`Browser errors during scenario:\n${browserErrors.join("\n")}`);
  }
}
