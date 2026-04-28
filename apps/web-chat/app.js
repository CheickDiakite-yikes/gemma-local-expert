const state = {
  conversations: [],
  activeConversationId: null,
  currentMode: "general",
  streaming: false,
  mobileSidebarOpen: false,
  sidebarCollapsed: false,
  mobileArtifactOpen: false,
  artifactPanelCollapsed: false,
  dragActive: false,
  statusMenuOpen: false,
  draftMessages: [],
  pendingAttachments: [],
  transcripts: new Map(),
  conversationTurns: new Map(),
  conversationItems: new Map(),
  agentRuns: new Map(),
  approvals: new Map(),
  approvalDrafts: new Map(),
  approvalErrors: new Map(),
  approvalPanels: new Map(),
  messagePanels: new Map(),
  runPanels: new Map(),
  assetTextPreviews: new Map(),
  capabilities: null,
  medicalSessions: new Map(),
  canvasSelection: null,
  artifactZoomActual: false,
  artifactMode: "summary",
  artifactSelectedAssetId: null,
  processFeed: [],
  statusDetail: "Ready for the next turn.",
  camera: {
    open: false,
    stream: null,
    recorder: null,
    recordedFile: null,
    recordedUrl: null,
    mimeType: null,
    watchActive: false,
    watchTimer: null,
    monitorFrames: [],
    cadenceSeconds: 12,
    status: "idle",
    error: null,
  },
};

const STORAGE_KEYS = {
  approvalDrafts: "field-assistant.approval-drafts.v1",
  approvalPanels: "field-assistant.approval-panels.v2",
  messagePanels: "field-assistant.message-panels.v1",
  runPanels: "field-assistant.run-panels.v2",
  activeConversation: "field-assistant.active-conversation.v1",
};

const elements = {
  appShell: document.querySelector(".app-shell"),
  artifactPanel: document.getElementById("artifact-panel"),
  artifactToggle: document.getElementById("artifact-toggle"),
  attachmentButton: document.getElementById("attachment-button"),
  attachmentStrip: document.getElementById("attachment-strip"),
  backdrop: document.getElementById("sidebar-backdrop"),
  cameraAnalyzeButton: document.getElementById("camera-analyze-button"),
  cameraButton: document.getElementById("camera-button"),
  cameraCadenceLabel: document.getElementById("camera-cadence-label"),
  cameraCaptureInput: document.getElementById("camera-capture-input"),
  cameraCloseButton: document.getElementById("camera-close-button"),
  cameraLiveButton: document.getElementById("camera-live-button"),
  cameraModeLabel: document.getElementById("camera-mode-label"),
  cameraMonitorStrip: document.getElementById("camera-monitor-strip"),
  cameraNativeButton: document.getElementById("camera-native-button"),
  cameraOutputLabel: document.getElementById("camera-output-label"),
  cameraOverlay: document.getElementById("camera-overlay"),
  cameraPreview: document.getElementById("camera-preview"),
  cameraRecordButton: document.getElementById("camera-record-button"),
  cameraRetakeButton: document.getElementById("camera-retake-button"),
  cameraSheet: document.getElementById("camera-sheet"),
  cameraSnapshotButton: document.getElementById("camera-snapshot-button"),
  cameraStatusCopy: document.getElementById("camera-status-copy"),
  cameraStatusPill: document.getElementById("camera-status-pill"),
  cameraStopButton: document.getElementById("camera-stop-button"),
  cameraUseButton: document.getElementById("camera-use-button"),
  cameraWatchButton: document.getElementById("camera-watch-button"),
  composer: document.getElementById("composer"),
  composerModelPill: document.getElementById("composer-model-pill"),
  conversationList: document.getElementById("conversation-list"),
  conversationTitle: document.getElementById("conversation-title"),
  emptyState: document.getElementById("empty-state"),
  fileInput: document.getElementById("file-input"),
  messageList: document.getElementById("message-list"),
  messageScroll: document.getElementById("message-scroll"),
  newChatButton: document.getElementById("new-chat-button"),
  promptInput: document.getElementById("composer-input"),
  sendButton: document.getElementById("send-button"),
  sidebar: document.getElementById("sidebar"),
  sidebarCommands: Array.from(document.querySelectorAll("[data-sidebar-command]")),
  sidebarToggle: document.getElementById("sidebar-toggle"),
  statusButton: document.getElementById("status-button"),
  statusDot: document.getElementById("status-dot"),
  statusMenu: document.getElementById("status-menu"),
  statusPill: document.getElementById("status-pill"),
  statusRuntimeCopy: document.getElementById("status-runtime-copy"),
  processList: document.getElementById("process-list"),
  voiceButton: document.getElementById("voice-button"),
};

const scheduledConversationRefreshes = new Map();
const inflightConversationRefreshes = new Set();

function activeMessages() {
  if (!state.activeConversationId) {
    return state.draftMessages;
  }
  return conversationTranscript(state.activeConversationId);
}

function conversationTranscript(conversationId) {
  return state.transcripts.get(conversationId) ?? [];
}

function itemsForConversation(conversationId) {
  return state.conversationItems.get(conversationId) ?? [];
}

function turnsForConversation(conversationId) {
  return state.conversationTurns.get(conversationId) ?? [];
}

function canUseStorage() {
  try {
    return typeof window !== "undefined" && Boolean(window.localStorage);
  } catch (error) {
    return false;
  }
}

function loadStoredRecord(key) {
  if (!canUseStorage()) {
    return {};
  }
  try {
    const raw = window.localStorage.getItem(key);
    if (!raw) {
      return {};
    }
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed : {};
  } catch (error) {
    return {};
  }
}

function saveStoredRecord(key, value) {
  if (!canUseStorage()) {
    return;
  }
  try {
    window.localStorage.setItem(key, JSON.stringify(value));
  } catch (error) {
    // Ignore local storage write failures.
  }
}

function loadPersistedUiState() {
  state.approvalDrafts = new Map(Object.entries(loadStoredRecord(STORAGE_KEYS.approvalDrafts)));
  state.approvalPanels = new Map(
    Object.entries(loadStoredRecord(STORAGE_KEYS.approvalPanels)).map(([key, value]) => [key, Boolean(value)]),
  );
  state.messagePanels = new Map(
    Object.entries(loadStoredRecord(STORAGE_KEYS.messagePanels)).map(([key, value]) => [key, Boolean(value)]),
  );
  state.runPanels = new Map(
    Object.entries(loadStoredRecord(STORAGE_KEYS.runPanels)).map(([key, value]) => [key, Boolean(value)]),
  );
  if (canUseStorage()) {
    state.activeConversationId = window.localStorage.getItem(STORAGE_KEYS.activeConversation) || null;
  }
}

function persistApprovalDrafts() {
  saveStoredRecord(STORAGE_KEYS.approvalDrafts, Object.fromEntries(state.approvalDrafts));
}

function persistApprovalPanels() {
  saveStoredRecord(STORAGE_KEYS.approvalPanels, Object.fromEntries(state.approvalPanels));
}

function persistMessagePanels() {
  saveStoredRecord(STORAGE_KEYS.messagePanels, Object.fromEntries(state.messagePanels));
}

function persistRunPanels() {
  saveStoredRecord(STORAGE_KEYS.runPanels, Object.fromEntries(state.runPanels));
}

function persistActiveConversation() {
  if (!canUseStorage()) {
    return;
  }
  try {
    if (state.activeConversationId) {
      window.localStorage.setItem(STORAGE_KEYS.activeConversation, state.activeConversationId);
    } else {
      window.localStorage.removeItem(STORAGE_KEYS.activeConversation);
    }
  } catch (error) {
    // Ignore local storage write failures.
  }
}

function stableSerialize(value) {
  if (Array.isArray(value)) {
    return `[${value.map((item) => stableSerialize(item)).join(",")}]`;
  }
  if (value && typeof value === "object") {
    return `{${Object.keys(value)
      .sort()
      .map((key) => `${JSON.stringify(key)}:${stableSerialize(value[key])}`)
      .join(",")}}`;
  }
  return JSON.stringify(value);
}

function setActiveMessages(messages) {
  if (!state.activeConversationId) {
    state.draftMessages = messages;
    return;
  }
  state.transcripts.set(state.activeConversationId, messages);
}

function purgeConversationUiState(conversationId) {
  const transcript = conversationTranscript(conversationId);
  const approvalIds = transcript.map((message) => message.approval?.id).filter(Boolean);
  const messageIds = transcript.map((message) => message.id).filter(Boolean);
  const runs = runsForConversation(conversationId);
  const scheduledRefresh = scheduledConversationRefreshes.get(conversationId);
  if (scheduledRefresh) {
    window.clearTimeout(scheduledRefresh);
    scheduledConversationRefreshes.delete(conversationId);
  }
  inflightConversationRefreshes.delete(conversationId);

  for (const approvalId of approvalIds) {
    state.approvalDrafts.delete(approvalId);
    state.approvalPanels.delete(approvalPanelKey(approvalId, "draft"));
    state.approvalPanels.delete(approvalPanelKey(approvalId, "edit"));
    state.approvalPanels.delete(approvalPanelKey(approvalId, "canvasCollapsed"));
  }
  for (const messageId of messageIds) {
    state.messagePanels.delete(messagePanelKey(messageId, "context"));
  }
  for (const run of runs) {
    if (run?.id) {
      state.runPanels.delete(run.id);
    }
  }

  state.transcripts.delete(conversationId);
  state.conversationTurns.delete(conversationId);
  state.conversationItems.delete(conversationId);
  state.agentRuns.delete(conversationId);
  state.medicalSessions.delete(conversationId);
  if (state.canvasSelection?.approvalId && approvalIds.includes(state.canvasSelection.approvalId)) {
    state.canvasSelection = null;
  }
  persistApprovalDrafts();
  persistApprovalPanels();
  persistMessagePanels();
  persistRunPanels();
}

function runsForConversation(conversationId) {
  return state.agentRuns.get(conversationId) || [];
}

function setConversationTurns(conversationId, turns) {
  state.conversationTurns.set(conversationId, Array.isArray(turns) ? turns : []);
}

function upsertAgentRun(conversationId, run) {
  if (!conversationId || !run?.id) {
    return null;
  }
  const runs = [...runsForConversation(conversationId)];
  const index = runs.findIndex((entry) => entry.id === run.id);
  if (index === -1) {
    runs.push(run);
  } else {
    runs[index] = run;
  }
  runs.sort((left, right) => String(left.created_at || "").localeCompare(String(right.created_at || "")));
  state.agentRuns.set(conversationId, runs);
  hydrateAgentRunsIntoMessages(conversationId);
  return run;
}

function approvalFromItem(item) {
  if (!item || item.kind !== "approval") {
    return null;
  }
  const payload = item.payload || {};
  if (payload.approval && typeof payload.approval === "object") {
    return payload.approval;
  }
  return null;
}

function workProductFromItem(item) {
  if (!item || item.kind !== "work_product") {
    return null;
  }
  const payload = item.payload || {};
  const approval = payload.approval && typeof payload.approval === "object" ? payload.approval : null;
  if (!approval?.id) {
    return null;
  }
  return {
    ...approval,
    payload:
      payload.work_product && typeof payload.work_product === "object"
        ? payload.work_product
        : approval.payload || {},
    result: payload.result || approval.result || null,
    source_domain: payload.source_domain || approval.source_domain || null,
    execution_mode: payload.execution_mode || approval.execution_mode || null,
    grounding_status: payload.grounding_status || approval.grounding_status || null,
    evidence_packet_id: payload.evidence_packet_id || approval.evidence_packet_id || null,
    workProductItem: item,
  };
}

function documentEditFromItem(item) {
  if (!item || item.kind !== "document_edit") {
    return null;
  }
  const payload = item.payload || {};
  if (!payload.approval_id) {
    return null;
  }
  return {
    id: item.id,
    createdAt: item.created_at || null,
    approvalId: payload.approval_id,
    toolName: payload.tool_name || null,
    action: payload.action || "updated",
    fieldName: payload.field_name || "content",
    range: payload.range || null,
    beforeText: payload.before_text || "",
    afterText: payload.after_text || "",
    visibleContentBefore: payload.visible_content_before || "",
    visibleContentAfter: payload.visible_content_after || "",
  };
}

function documentEditsForApproval(approvalId) {
  if (!approvalId || !state.activeConversationId) {
    return [];
  }
  return itemsForConversation(state.activeConversationId)
    .map(documentEditFromItem)
    .filter((edit) => edit?.approvalId === approvalId)
    .sort((left, right) => String(left.createdAt || "").localeCompare(String(right.createdAt || "")));
}

function documentEditActionLabel(action) {
  switch (action) {
    case "shorten":
      return "Shortened selection";
    case "neutral":
      return "Made selection more neutral";
    case "rewrite":
      return "Rewrote selection";
    default:
      return "Updated selection";
  }
}

function hydrateApprovalsIntoMessages(conversationId) {
  const messages = state.transcripts.get(conversationId);
  if (!messages) {
    return;
  }
  const items = itemsForConversation(conversationId);
  const latestApprovalsById = new Map();
  const latestWorkProductsById = new Map();
  let itemApprovalCount = 0;
  for (const item of items) {
    const approval = approvalFromItem(item);
    const workProduct = workProductFromItem(item);
    if (approval?.id) {
      itemApprovalCount += 1;
      latestApprovalsById.set(approval.id, approval);
      state.approvals.set(approval.id, approval);
    }
    if (workProduct?.id) {
      itemApprovalCount += 1;
      latestWorkProductsById.set(workProduct.id, workProduct);
      state.approvals.set(workProduct.id, workProduct);
    }
  }
  if (itemApprovalCount === 0) {
    return;
  }
  const approvalsByTurn = new Map();
  for (const approval of latestApprovalsById.values()) {
    if (approval?.turn_id) {
      approvalsByTurn.set(approval.turn_id, approval);
    }
  }
  const workProductsByTurn = new Map();
  for (const workProduct of latestWorkProductsById.values()) {
    if (workProduct?.turn_id) {
      workProductsByTurn.set(workProduct.turn_id, workProduct);
    }
  }
  for (const message of messages) {
    if (message.role === "assistant" && message.turnId) {
      const workProduct = workProductsByTurn.get(message.turnId) || null;
      const approval = workProduct || approvalsByTurn.get(message.turnId) || null;
      message.workProduct = workProduct;
      message.approval = approval;
      message.proposedTool = approval?.tool_name || null;
      message.toolResult = approval?.result || null;
    }
  }
}

function setConversationItems(conversationId, items) {
  const nextItems = Array.isArray(items) ? [...items] : [];
  nextItems.sort((left, right) => String(left?.created_at || "").localeCompare(String(right?.created_at || "")));
  state.conversationItems.set(conversationId, nextItems);
  hydrateApprovalsIntoMessages(conversationId);
}

function upsertConversationItem(conversationId, item) {
  if (!conversationId || !item?.id) {
    return null;
  }
  const items = [...itemsForConversation(conversationId)];
  const index = items.findIndex((entry) => entry.id === item.id);
  if (index === -1) {
    items.push(item);
  } else {
    items[index] = item;
  }
  setConversationItems(conversationId, items);
  const approval = approvalFromItem(item);
  if (approval?.id) {
    state.approvals.set(approval.id, approval);
  }
  const workProduct = workProductFromItem(item);
  if (workProduct?.id) {
    state.approvals.set(workProduct.id, workProduct);
  }
  if (item.kind === "agent_run" && item.payload?.run) {
    upsertAgentRun(conversationId, item.payload.run);
  }
  return item;
}

function normalizeTranscriptMessage(message, runsByTurn = new Map()) {
  return {
    id: message.id,
    role: message.role,
    turnId: message.turn_id || null,
    content: message.content,
    assets: message.assets || [],
    citations: [],
    approval: message.approval || null,
    workProduct: null,
    proposedTool: message.approval?.tool_name || null,
    process: [],
    toolResult: message.approval?.result || null,
    agentRun:
      message.role === "assistant" && message.turn_id ? runsByTurn.get(message.turn_id) || null : null,
    loading: false,
  };
}

function applyConversationState(conversationId, snapshot) {
  const runs = Array.isArray(snapshot?.runs) ? snapshot.runs : [];
  const turns = Array.isArray(snapshot?.turns) ? snapshot.turns : [];
  const items = Array.isArray(snapshot?.items) ? snapshot.items : [];
  const messages = Array.isArray(snapshot?.messages) ? snapshot.messages : [];

  state.agentRuns.set(conversationId, runs);
  setConversationTurns(conversationId, turns);

  const runsByTurn = new Map(
    runs
      .filter((run) => run?.turn_id)
      .map((run) => [run.turn_id, run]),
  );

  state.transcripts.set(
    conversationId,
    messages.map((message) => normalizeTranscriptMessage(message, runsByTurn)),
  );
  setConversationItems(conversationId, items);
  return state.transcripts.get(conversationId) || [];
}

function hydrateAgentRunsIntoMessages(conversationId) {
  const messages = state.transcripts.get(conversationId);
  if (!messages) {
    return;
  }
  const runsByTurn = new Map(
    runsForConversation(conversationId)
      .filter((run) => run?.turn_id)
      .map((run) => [run.turn_id, run]),
  );
  for (const message of messages) {
    message.agentRun =
      message.role === "assistant" && message.turnId ? runsByTurn.get(message.turnId) || null : null;
  }
}

function capabilitySummary(capabilities) {
  if (!capabilities) {
    return "Capabilities unavailable.";
  }
  return [
    capabilityBackendLabel("Assistant", capabilities.assistant_backend, capabilities.assistant_model_available),
    capabilityBackendLabel("Images", capabilities.specialist_backend, capabilities.vision_model_available, {
      ocrAvailable: capabilities.tesseract_available,
    }),
    capabilityBackendLabel("Video", capabilities.tracking_backend, capabilities.tracking_model_available, {
      ffmpegAvailable: capabilities.ffmpeg_available,
    }),
    capabilities.low_memory_profile ? "low-memory profile" : "full local profile",
  ].join(" • ");
}

function capabilityBackendLabel(label, backend, modelAvailable, options = {}) {
  const normalized = String(backend || "unknown").toLowerCase();
  if (normalized === "mock") {
    return `${label}: mock responses`;
  }
  if (normalized === "ocr") {
    return `${label}: OCR${options.ocrAvailable ? "" : " unavailable"}`;
  }
  if (normalized === "hash") {
    return `${label}: hash fallback`;
  }
  if (normalized === "fallback") {
    return `${label}: fallback mode`;
  }
  if (normalized === "none") {
    return `${label}: unavailable`;
  }
  if (normalized.includes("mock")) {
    return `${label}: mock responses`;
  }
  if (normalized.includes("mlx") || normalized.includes("local")) {
    return `${label}: ${modelAvailable ? "local model ready" : "configured, model missing"}`;
  }
  if (label === "Video" && options.ffmpegAvailable && !modelAvailable) {
    return `${label}: sampling fallback`;
  }
  return `${label}: ${normalized}${modelAvailable ? " ready" : " fallback"}`;
}

function capabilityPillCopy(capabilities) {
  if (!capabilities) {
    return "◐ Local status⌄";
  }
  const assistant = String(capabilities.assistant_backend || "").toLowerCase();
  const specialist = String(capabilities.specialist_backend || "").toLowerCase();
  if (assistant === "mock") {
    return specialist === "ocr" ? "◐ Mock + OCR⌄" : "◐ Mock local⌄";
  }
  if (capabilities.assistant_model_available) {
    return "◐ Local model⌄";
  }
  return "◐ Fallback local⌄";
}

function approvalDraftFor(approvalId) {
  return state.approvalDrafts.get(approvalId) || null;
}

function approvalErrorFor(approvalId) {
  return state.approvalErrors.get(approvalId) || "";
}

function approvalEditableFields(approval) {
  switch (approval?.tool_name) {
    case "create_task":
      return ["title", "details", "status"];
    case "create_note":
    case "create_report":
    case "create_message_draft":
    case "create_checklist":
    case "export_brief":
    case "log_observation":
      return ["title", "content"];
    default:
      return null;
  }
}

function approvalMergedPayload(approval, overridePayload = undefined) {
  const basePayload = approval?.payload || {};
  if (overridePayload === undefined || overridePayload === null) {
    return basePayload;
  }

  const editableFields = approvalEditableFields(approval);
  if (!editableFields) {
    return overridePayload;
  }

  return {
    ...basePayload,
    ...overridePayload,
  };
}

function approvalComparablePayload(approval, overridePayload = undefined) {
  const resolvedPayload = approvalMergedPayload(approval, overridePayload);
  const editableFields = approvalEditableFields(approval);
  if (!editableFields) {
    return resolvedPayload;
  }

  const comparablePayload = {};
  for (const field of editableFields) {
    if (Object.prototype.hasOwnProperty.call(resolvedPayload, field)) {
      comparablePayload[field] = resolvedPayload[field];
    }
  }
  return comparablePayload;
}

function approvalEffectivePayload(approval, overridePayload = undefined) {
  if (!approval?.payload) {
    return {};
  }
  if (overridePayload !== undefined) {
    return approvalMergedPayload(approval, overridePayload);
  }
  if (approval.status === "pending") {
    const draftPayload = approvalDraftFor(approval.id);
    if (draftPayload) {
      return approvalMergedPayload(approval, draftPayload);
    }
  }
  return approval.payload;
}

function selectedCanvasRangeFromField(field, approval) {
  if (!field || !approval?.id || field.dataset.approvalField !== "content") {
    return null;
  }
  const start = field.selectionStart;
  const end = field.selectionEnd;
  if (!Number.isInteger(start) || !Number.isInteger(end) || end <= start) {
    return null;
  }
  const text = field.value.slice(start, end);
  if (!text.trim()) {
    return null;
  }
  return {
    approvalId: approval.id,
    fieldName: "content",
    start,
    end,
    text,
  };
}

function updateCanvasSelectionHint(container, selection) {
  const hint = container.querySelector("[data-canvas-selection-hint]");
  if (!hint) {
    return;
  }
  if (!selection) {
    hint.hidden = true;
    hint.textContent = "";
    return;
  }
  const wordCount = selection.text.trim().split(/\s+/).filter(Boolean).length;
  hint.hidden = false;
  hint.textContent = `Selected ${wordCount} word${wordCount === 1 ? "" : "s"}. Ask: shorten this, rewrite this, or make this more neutral.`;
}

function rememberCanvasSelection(container, field, approval) {
  const selection = selectedCanvasRangeFromField(field, approval);
  if (!selection) {
    if (state.canvasSelection?.approvalId === approval?.id) {
      state.canvasSelection = null;
    }
    updateCanvasSelectionHint(container, null);
    return null;
  }
  state.canvasSelection = selection;
  updateCanvasSelectionHint(container, selection);
  return selection;
}

function currentCanvasSelection() {
  const selection = state.canvasSelection;
  if (!selection?.approvalId) {
    return null;
  }
  const textarea = document.querySelector(
    `[data-approval-editor="${CSS.escape(selection.approvalId)}"] [data-approval-field="content"]`,
  );
  if (!textarea || textarea.value.slice(selection.start, selection.end) !== selection.text) {
    state.canvasSelection = null;
    return null;
  }
  const container = textarea.closest(".message-row");
  const approval = state.approvals.get(selection.approvalId);
  if (!container || !approval || !approvalUsesInlineCanvas(approval)) {
    state.canvasSelection = null;
    return null;
  }
  return { ...selection, textarea, container, approval };
}

function selectedCanvasAction(prompt) {
  const lowered = String(prompt || "").toLowerCase();
  if (!/\b(this|selection|selected text|highlighted text|highlight)\b/.test(lowered)) {
    return null;
  }
  if (/\b(explain|what does|what is this saying|what does this mean)\b/.test(lowered)) {
    return "explain";
  }
  if (/\b(neutral|less certain|less dramatic|less strong|more careful|uncertainty)\b/.test(lowered)) {
    return "neutral";
  }
  if (/\b(shorten|shorter|tighten|trim|condense|more concise)\b/.test(lowered)) {
    return "shorten";
  }
  if (/\b(rewrite|rephrase|clean up|polish|clearer|more direct)\b/.test(lowered)) {
    return "rewrite";
  }
  return null;
}

function splitSelectionPrefix(text) {
  const match = String(text || "").match(/^(\s*(?:[-*+]\s+|\d+\.\s+|#{1,6}\s+|>\s*)?)([\s\S]*?)$/);
  return {
    prefix: match?.[1] || "",
    body: match?.[2] || "",
  };
}

function sentenceCase(text) {
  const trimmed = String(text || "").trim();
  if (!trimmed) {
    return "";
  }
  return `${trimmed[0].toUpperCase()}${trimmed.slice(1)}`;
}

function ensureTerminalPunctuation(text) {
  const trimmed = String(text || "").trim();
  if (!trimmed || /[.!?]$/.test(trimmed)) {
    return trimmed;
  }
  return `${trimmed}.`;
}

function cleanSelectionBody(text) {
  return stripMarkdownToText(text)
    .replace(/\s+/g, " ")
    .replace(/\s+([,.;:!?])/g, "$1")
    .trim();
}

function shortenSelectionText(text) {
  const { prefix, body } = splitSelectionPrefix(text);
  let clean = cleanSelectionBody(body);
  clean = clean
    .replace(/\b(currently|really|very|clearly|basically|immediately|actually)\b/gi, "")
    .replace(/\b(main structure, responsibilities, and current constraints)\b/gi, "structure and constraints")
    .replace(/\bbefore (?:it is|it's|we are|we're)?\s*saved locally\b/gi, "before saving")
    .replace(/\bif the audience needs a shorter version\b/gi, "for the audience")
    .replace(/\s{2,}/g, " ")
    .trim();
  const firstSentence = clean.split(/(?<=[.!?])\s+/)[0] || clean;
  const shortened = ensureTerminalPunctuation(firstSentence.length <= 120 ? firstSentence : `${firstSentence.slice(0, 117).trimEnd()}...`);
  return `${prefix}${sentenceCase(shortened)}`;
}

function neutralizeSelectionText(text) {
  const { prefix, body } = splitSelectionPrefix(text);
  let clean = cleanSelectionBody(body);
  clean = clean
    .replace(/\bmust\b/gi, "should")
    .replace(/\bwill\b/gi, "may")
    .replace(/\bdefinitely\b/gi, "may")
    .replace(/\bclearly\b/gi, "carefully")
    .replace(/\bimmediately\b/gi, "soon")
    .replace(/\bstrongest\b/gi, "best-supported")
    .replace(/\bstrong\b/gi, "well-supported")
    .replace(/\burgent\b/gi, "important")
    .replace(/\bclaims?\b/gi, "points")
    .replace(/\bprove\b/gi, "support")
    .replace(/\s{2,}/g, " ")
    .trim();
  return `${prefix}${ensureTerminalPunctuation(sentenceCase(clean))}`;
}

function rewriteSelectionText(text) {
  const { prefix, body } = splitSelectionPrefix(text);
  const clean = ensureTerminalPunctuation(sentenceCase(cleanSelectionBody(body)));
  return `${prefix}${clean}`;
}

function explainSelectionText(text) {
  const clean = cleanSelectionBody(text);
  if (!clean) {
    return "That selection is empty, so there is nothing to explain yet.";
  }
  return `That selected text is saying: ${ensureTerminalPunctuation(clean)}`;
}

function transformSelectedCanvasText(text, action) {
  switch (action) {
    case "shorten":
      return shortenSelectionText(text);
    case "neutral":
      return neutralizeSelectionText(text);
    case "rewrite":
      return rewriteSelectionText(text);
    default:
      return text;
  }
}

function approvalGroundingLabel(payload) {
  switch (payload?.source_domain) {
    case "video":
      return "video evidence";
    case "image":
      return "image evidence";
    case "document":
      return "document evidence";
    case "workspace":
      return "workspace evidence";
    default:
      return "local evidence";
  }
}

function approvalGroundingNotice(approval, payload) {
  if (!payload || !payload.grounding_status || !["grounded", "partial"].includes(payload.grounding_status)) {
    return "";
  }
  const label = approvalGroundingLabel(payload);
  if (payload.grounding_status === "partial") {
    return `This draft is only partially grounded in ${label}. Keep edits anchored to the same source material if you want to save it.`;
  }
  return `This draft is grounded in ${label}. Refine or shorten it, but keep it anchored to the same source material.`;
}

function approvalHasDraftChanges(approval, overridePayload = undefined) {
  if (!approval?.payload) {
    return false;
  }
  const comparableBase = approvalComparablePayload(approval, approval.payload);
  const comparableEffective = approvalComparablePayload(
    approval,
    overridePayload === undefined ? approvalDraftFor(approval.id) || approval.payload : overridePayload,
  );
  return stableSerialize(comparableEffective) !== stableSerialize(comparableBase);
}

function approvalDraftStateText({ dirty = false, invalid = false } = {}) {
  if (invalid) {
    return "JSON needs fixing";
  }
  return dirty ? "Local edits" : "Original";
}

function approvalCanvasStateText({ dirty = false } = {}) {
  return dirty ? "Edited" : "Unsaved";
}

function approvalStateLabelText(approval, { dirty = false, invalid = false } = {}) {
  if (approvalUsesInlineCanvas(approval)) {
    return invalid ? "Needs attention" : approvalCanvasStateText({ dirty });
  }
  return approvalDraftStateText({ dirty, invalid });
}

function approvalPanelKey(approvalId, section) {
  return `${approvalId}:${section}`;
}

function approvalPanelPreference(approvalId, section) {
  return state.approvalPanels.get(approvalPanelKey(approvalId, section));
}

function isApprovalSectionExpanded(approval, section) {
  if (section === "preview") {
    return true;
  }
  if (section === "editor" && (approvalErrorFor(approval.id) || approvalHasDraftChanges(approval))) {
    return true;
  }
  const saved = approvalPanelPreference(approval.id, section);
  if (typeof saved === "boolean") {
    return saved;
  }
  return false;
}

function setApprovalSectionExpanded(approvalId, section, expanded) {
  state.approvalPanels.set(approvalPanelKey(approvalId, section), Boolean(expanded));
  if (section === "editor") {
    return;
  }
  persistApprovalPanels();
}

function isApprovalCanvasCollapsed(approval) {
  return approvalPanelPreference(approval.id, "canvasCollapsed") === true;
}

function setApprovalCanvasCollapsed(approvalId, collapsed) {
  state.approvalPanels.set(approvalPanelKey(approvalId, "canvasCollapsed"), Boolean(collapsed));
  persistApprovalPanels();
}

function approvalStatusLabel(status) {
  switch (status) {
    case "pending":
      return "Unsaved";
    case "executed":
      return "Saved locally";
    case "rejected":
      return "Skipped";
    case "failed":
      return "Save failed";
    default:
      return humanizeRunStatus(status || "pending");
  }
}

function approvalStatusKicker(status) {
  switch (status) {
    case "pending":
      return "Draft";
    case "executed":
      return "Saved";
    case "rejected":
      return "Not saved";
    case "failed":
      return "Needs attention";
    default:
      return "Action update";
  }
}

function approvalSurfaceTitle(toolName) {
  switch (toolName) {
    case "create_note":
      return "Save note";
    case "create_report":
      return "Save report";
    case "create_message_draft":
      return "Save message draft";
    case "create_checklist":
      return "Save checklist";
    case "create_task":
      return "Save task";
    case "export_brief":
      return "Export markdown";
    case "log_observation":
      return "Save observation";
    default:
      return humanizeToolName(toolName);
  }
}

function approvalSurfaceNoun(toolName) {
  switch (toolName) {
    case "create_note":
      return "note";
    case "create_report":
      return "report";
    case "create_message_draft":
      return "message draft";
    case "create_checklist":
      return "checklist";
    case "create_task":
      return "task";
    case "export_brief":
      return "export";
    case "log_observation":
      return "observation";
    default:
      return "draft";
  }
}

function approvalReasonCopy(approval) {
  if (!approval) {
    return "";
  }
  if (approval.status === "executed") {
    return "Saved in this workspace.";
  }
  if (approval.status === "rejected") {
    return "Not saved locally.";
  }
  if (approval.status === "failed") {
    return "The local save did not finish cleanly.";
  }
  const sourceDomain = String(approval.source_domain || "").toLowerCase();
  switch (approval.tool_name) {
    case "create_checklist":
      return sourceDomain === "image" || sourceDomain === "video"
        ? "From the attached media findings."
        : "From this conversation.";
    case "create_task":
      return "From this conversation.";
    case "create_report":
      return sourceDomain === "workspace"
        ? "From the local workspace review."
        : sourceDomain === "document"
          ? "From the document findings."
          : "From this conversation.";
    case "create_message_draft":
      return sourceDomain === "image" || sourceDomain === "video"
        ? "From the attached media findings."
        : "From this conversation.";
    case "export_brief":
      return sourceDomain === "workspace"
        ? "From the local workspace review."
        : "From this conversation.";
    case "log_observation":
      return "From this conversation.";
    case "create_note":
      return sourceDomain === "workspace"
        ? "From the local workspace review."
        : sourceDomain === "document"
          ? "From the document findings."
          : "From this conversation.";
    default:
      return "Drafted locally.";
  }
}

function approvalReviewDetail(approvalLike) {
  const explicitReason = String(approvalLike?.reason || "").trim();
  if (explicitReason) {
    return explicitReason;
  }
  const descriptorSummary = String(approvalLike?.tool_descriptor?.approval_summary || "").trim();
  if (descriptorSummary) {
    return descriptorSummary;
  }
  switch (String(approvalLike?.category || "").toLowerCase()) {
    case "audited_export":
      return "Review the markdown export before it is written locally.";
    case "medical_specialist":
      return "Review the guarded medical specialist action before it continues.";
    default:
      return `Review the ${approvalSurfaceNoun(approvalLike?.tool_name || "")} before it is written locally.`;
  }
}

function approvalHeadingText(approval, payload = undefined) {
  const resolvedPayload = payload || approvalEffectivePayload(approval);
  const title = resolvedPayload?.title ? clipCopy(resolvedPayload.title, 88) : "";
  if (title) {
    return title;
  }
  const noun = approvalSurfaceNoun(approval?.tool_name || "");
  switch (approval?.status) {
    case "executed":
      return `Saved ${noun}`;
    case "rejected":
      return `${noun.charAt(0).toUpperCase() + noun.slice(1)} not saved`;
    case "failed":
      return `${noun.charAt(0).toUpperCase() + noun.slice(1)} needs attention`;
    default:
      return `${noun.charAt(0).toUpperCase() + noun.slice(1)} draft`;
  }
}

function approvalPrimaryActionLabel(approval) {
  switch (approval?.tool_name) {
    case "create_note":
      return "Save note";
    case "create_report":
      return "Save report";
    case "create_message_draft":
      return "Save message";
    case "create_checklist":
      return "Save checklist";
    case "create_task":
      return "Save task";
    case "export_brief":
      return "Export markdown";
    case "log_observation":
      return "Save observation";
    default:
      return "Save";
  }
}

function stripMarkdownToText(text) {
  return String(text || "")
    .replace(/\r\n?/g, "\n")
    .replace(/```[\s\S]*?```/g, " ")
    .replace(/`([^`]+)`/g, "$1")
    .replace(/!\[[^\]]*\]\([^)]+\)/g, " ")
    .replace(/\[([^\]]+)\]\([^)]+\)/g, "$1")
    .replace(/^#{1,6}\s+/gm, "")
    .replace(/^>\s?/gm, "")
    .replace(/^[-*+]\s+\[(?: |x)\]\s+/gim, "")
    .replace(/^[-*+]\s+/gm, "")
    .replace(/^\d+\.\s+/gm, "")
    .replace(/\*\*([^*]+)\*\*/g, "$1")
    .replace(/\*([^*]+)\*/g, "$1")
    .replace(/[_~]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function clipCopy(text, size = 180) {
  const normalized = String(text || "").trim();
  if (!normalized) {
    return "";
  }
  return normalized.length > size ? `${normalized.slice(0, size - 1).trimEnd()}...` : normalized;
}

function artifactPreviewTitle(title, size = 74) {
  return clipCopy(stripMarkdownToText(title), size);
}

function approvalMeaningfulLines(text) {
  return String(text || "")
    .replace(/\r\n?/g, "\n")
    .split("\n")
    .map((line) => ({ raw: line, clean: stripMarkdownToText(line).trim() }))
    .filter((entry) => entry.clean)
    .filter((entry) => !/^\s*[-*+]\s+\[[^\]]+\]\([^)]+\)\s*$/.test(entry.raw))
    .map((entry) => entry.clean)
    .filter(Boolean)
    .filter(
      (line) =>
        !/^(goal|workspace scope|top-level scope entries|workspace findings|related docs|related local docs|related brief|working title|date|status):/i.test(
          line,
        ),
    )
    .filter((line) => !/^\[[^\]]+\]\s+score=/i.test(line));
}

function approvalLooksLikeInventoryLine(line) {
  return (
    /^\.?[\w/-]+\/?$/.test(line) ||
    /^[\w./-]+\.(md|txt|json|png|jpe?g|webp|pdf)$/i.test(line) ||
    /^\[[^\]]+\](\([^)]+\))?$/i.test(line)
  );
}

function approvalPayloadExcerpt(approval, payload) {
  if (!payload) {
    return "";
  }
  const source = payload.content || payload.details || "";
  if (source) {
    const meaningful = approvalMeaningfulLines(source);
    const filtered = meaningful.filter((line) => !approvalLooksLikeInventoryLine(line));
    const preferred =
      filtered.find((line) => line.length >= 48 && /[.?!]$/.test(line)) ||
      filtered.find((line) => line.length >= 48) ||
      filtered.find((line) => line.length >= 24) ||
      filtered.slice(0, 2).join(" ");
    const normalized = preferred || stripMarkdownToText(source);
    return clipCopy(normalized, 190);
  }
  const keys = Object.keys(payload);
  if (!keys.length) {
    return "";
  }
  return `Contains ${keys.length} saved field${keys.length === 1 ? "" : "s"} for this ${approvalSurfaceNoun(approval.tool_name)}.`;
}

function approvalPayloadUsesTitleHeading(payload) {
  if (!payload?.content || !payload?.title) {
    return false;
  }
  const normalizedTitle = stripMarkdownToText(payload.title).trim().toLowerCase();
  if (!normalizedTitle) {
    return false;
  }
  const lines = String(payload.content)
    .replace(/\r\n?/g, "\n")
    .split("\n");
  const firstMeaningfulIndex = lines.findIndex((line) => stripMarkdownToText(line).trim());
  if (firstMeaningfulIndex === -1) {
    return false;
  }
  const firstRaw = lines[firstMeaningfulIndex].trim();
  const firstMeaningful = stripMarkdownToText(firstRaw).trim().toLowerCase();
  return /^#{1,6}\s+/.test(firstRaw) && firstMeaningful === normalizedTitle;
}

function approvalPreviewContent(approval, payload) {
  if (!payload) {
    return "";
  }
  const source = payload.content || payload.details || "";
  let content = String(source || "").trim();
  if (!content) {
    return "";
  }

  const normalizedTitle = stripMarkdownToText(payload.title || "").trim().toLowerCase();
  if (!normalizedTitle) {
    return content;
  }

  const lines = content.replace(/\r\n?/g, "\n").split("\n");
  const firstMeaningfulIndex = lines.findIndex((line) => stripMarkdownToText(line).trim());
  if (firstMeaningfulIndex === -1) {
    return content;
  }

  const firstMeaningful = stripMarkdownToText(lines[firstMeaningfulIndex]).trim().toLowerCase();
  if (firstMeaningful !== normalizedTitle) {
    return content;
  }

  const trimmedLines = lines.slice(firstMeaningfulIndex + 1);
  while (trimmedLines.length && !trimmedLines[0].trim()) {
    trimmedLines.shift();
  }
  return trimmedLines.join("\n").trim() || content;
}

function approvalCanvasContent(approval, payload) {
  if (!payload?.content) {
    return "";
  }
  if (!approvalPayloadUsesTitleHeading(payload)) {
    return String(payload.content || "");
  }
  return approvalPreviewContent(approval, payload);
}

function approvalComposeCanvasContent(approval, basePayload, nextTitle, nextContent) {
  if (!["create_note", "create_report", "export_brief", "log_observation"].includes(approval?.tool_name)) {
    return nextContent;
  }
  if (!approvalPayloadUsesTitleHeading(basePayload || {})) {
    return nextContent;
  }
  const normalizedTitle = String(nextTitle || "").trim();
  const normalizedContent = String(nextContent || "")
    .replace(/\r\n?/g, "\n")
    .trim();
  if (!normalizedContent || !normalizedTitle) {
    return nextContent;
  }
  const lines = normalizedContent.split("\n");
  const firstMeaningfulIndex = lines.findIndex((line) => stripMarkdownToText(line).trim());
  if (firstMeaningfulIndex !== -1) {
    const firstRaw = lines[firstMeaningfulIndex].trim();
    const firstMeaningful = stripMarkdownToText(firstRaw).trim().toLowerCase();
    if (/^#{1,6}\s+/.test(firstRaw) && firstMeaningful === normalizedTitle.toLowerCase()) {
      return normalizedContent;
    }
  }
  return `# ${normalizedTitle}\n\n${normalizedContent}`;
}

function approvalPayloadMeta(approval, payload) {
  const bits = [];
  if (approval?.tool_name === "create_task" && payload?.status) {
    bits.push(`Status: ${humanizeRunStatus(payload.status)}`);
  }
  if (payload?.content && approval?.tool_name === "create_checklist") {
    const itemCount = String(payload.content)
      .split(/\r?\n/)
      .map((line) => line.trim())
      .filter((line) => /^[-*+]\s+/.test(line) || /^\d+\.\s+/.test(line)).length;
    if (itemCount) {
      bits.push(`${itemCount} items`);
    }
  }
  return bits;
}

function approvalSummaryText(approval, overridePayload = undefined) {
  if (!approval) {
    return "";
  }
  const payload = approvalEffectivePayload(approval, overridePayload);
  const title = payload?.title ? clipCopy(payload.title, 72) : "";
  const excerpt = approvalPayloadExcerpt(approval, payload);
  switch (approval.status) {
    case "executed":
      return title ? `Saved "${title}" locally.` : "Saved locally.";
    case "rejected":
      return title ? `Skipped "${title}".` : "Skipped.";
    case "failed":
      return title ? `Could not save "${title}".` : "Could not save locally.";
    default:
      if (approval.tool_name === "export_brief" && title) {
        return title;
      }
      return excerpt || `Ready to save this ${approvalSurfaceNoun(approval.tool_name)}.`;
  }
}

function saveApprovalDraft(approvalId, payload) {
  state.approvalDrafts.set(approvalId, payload);
  persistApprovalDrafts();
}

function clearApprovalDraft(approvalId) {
  if (!state.approvalDrafts.has(approvalId)) {
    return;
  }
  state.approvalDrafts.delete(approvalId);
  persistApprovalDrafts();
}

function pruneResolvedApprovalDrafts(messages) {
  let changed = false;
  for (const message of messages || []) {
    if (
      message.approval?.id &&
      message.approval.status !== "pending" &&
      state.approvalDrafts.has(message.approval.id)
    ) {
      state.approvalDrafts.delete(message.approval.id);
      changed = true;
    }
  }
  if (changed) {
    persistApprovalDrafts();
  }
}

function runPanelPreference(runId) {
  return state.runPanels.get(runId);
}

function isRunExpanded(run) {
  const saved = runPanelPreference(run.id);
  if (typeof saved === "boolean") {
    return saved;
  }
  return false;
}

function setRunExpanded(runId, expanded) {
  state.runPanels.set(runId, Boolean(expanded));
  persistRunPanels();
}

function updateStatus(kind, label, detail = null) {
  const presented = presentStatusUpdate(kind, label, detail);
  elements.statusPill.textContent = presented.label;
  elements.statusRuntimeCopy.textContent = presented.detail;
  state.statusDetail = presented.detail;
  elements.statusPill.classList.toggle("is-thinking", kind === "thinking");
  elements.statusPill.classList.toggle("is-error", kind === "error");
  elements.statusButton.classList.toggle("is-thinking", kind === "thinking");
  elements.statusButton.classList.toggle("is-error", kind === "error");
  elements.statusDot.classList.toggle("is-thinking", kind === "thinking");
  elements.statusDot.classList.toggle("is-error", kind === "error");
}

function presentStatusUpdate(kind, label, detail = null) {
  const fallbackDetail = detail || label;
  if (kind === "ready" || kind === "error") {
    return {
      label,
      detail: fallbackDetail,
    };
  }

  const text = `${label || ""} ${detail || ""}`.toLowerCase();
  if (text.includes("medical")) {
    return {
      label: "Medical session",
      detail: "Opening the guarded workflow for medical review.",
    };
  }
  if (text.includes("upload")) {
    return {
      label: "Uploading",
      detail: "Saving attachments into the local workspace.",
    };
  }
  if (text.includes("ground")) {
    return {
      label: "Working locally",
      detail: "Reviewing local material for this turn.",
    };
  }
  if (text.includes("image") || text.includes("video") || text.includes("vision") || text.includes("media")) {
    return {
      label: "Reviewing media",
      detail: "Checking the attached media locally.",
    };
  }
  if (text.includes("approval") || text.includes("tool") || text.includes("draft ready") || text.includes("running local helper")) {
    return {
      label: "Preparing action",
      detail: "Preparing a local draft for review.",
    };
  }
  if (text.includes("workspace")) {
    return {
      label: "Working locally",
      detail: "Reviewing local workspace material.",
    };
  }
  if (text.includes("writ") || text.includes("draft")) {
    return {
      label: "Drafting answer",
      detail: "Composing the response from local context.",
    };
  }
  if (text.includes("rout")) {
    return {
      label: "Working locally",
      detail: "Choosing the best local path for this request.",
    };
  }
  return {
    label: "Working locally",
    detail: "Processing this request on-device.",
  };
}

function recordProcessEvent(kind, label, detail = "") {
  const previous = state.processFeed[0];
  if (previous && previous.kind === kind && previous.label === label && previous.detail === detail) {
    return;
  }
  state.processFeed = [
    {
      id: `${Date.now()}-${Math.random().toString(16).slice(2)}`,
      kind,
      label,
      detail,
      at: new Date().toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }),
    },
    ...state.processFeed,
  ].slice(0, 6);
}

function mergeMessageProcess(message, entry) {
  if (!message.process) {
    message.process = [];
  }
  const previous = message.process[message.process.length - 1];
  if (
    previous &&
    previous.kind === entry.kind &&
    previous.label === entry.label &&
    previous.detail === entry.detail
  ) {
    return;
  }
  message.process.push(entry);
}

function renderStatusMenu() {
  elements.statusButton.setAttribute("aria-expanded", String(state.statusMenuOpen));
  elements.statusMenu.hidden = !state.statusMenuOpen;
  const capabilityMarkup = state.capabilities
    ? `
      <div class="process-capabilities">
        <strong>Engine capabilities</strong>
        <p>${escapeHtml(capabilitySummary(state.capabilities))}</p>
      </div>
    `
    : "";

  if (!state.processFeed.length) {
    elements.processList.innerHTML = `
      ${capabilityMarkup}
      <div class="process-empty">
        <strong>Idle</strong>
        <span>The engine is waiting for the next turn.</span>
      </div>
    `;
    return;
  }

  elements.processList.innerHTML = state.processFeed
    .map(
      (entry) => `
        <div class="process-entry">
          <div class="process-entry-header">
            <strong>${escapeHtml(entry.label)}</strong>
            <span>${escapeHtml(entry.at)}</span>
          </div>
          ${entry.detail ? `<p>${escapeHtml(entry.detail)}</p>` : ""}
        </div>
      `,
    )
    .join("");
  if (capabilityMarkup) {
    elements.processList.innerHTML = capabilityMarkup + elements.processList.innerHTML;
  }
}

function toggleStatusMenu(forceOpen) {
  state.statusMenuOpen = typeof forceOpen === "boolean" ? forceOpen : !state.statusMenuOpen;
  renderStatusMenu();
}

function clip(text, size = 88) {
  if (!text) {
    return "";
  }
  return text.length > size ? `${text.slice(0, size - 1)}…` : text;
}

function formatRelativeAgeCompact(value) {
  if (!value) {
    return "";
  }
  const date = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "";
  }
  const diffMs = Date.now() - date.getTime();
  const minute = 60 * 1000;
  const hour = 60 * minute;
  const day = 24 * hour;
  if (diffMs < minute) {
    return "now";
  }
  if (diffMs < hour) {
    return `${Math.max(1, Math.round(diffMs / minute))}m`;
  }
  if (diffMs < day) {
    return `${Math.max(1, Math.round(diffMs / hour))}h`;
  }
  if (diffMs < day * 7) {
    return `${Math.max(1, Math.round(diffMs / day))}d`;
  }
  return date.toLocaleDateString([], { month: "short", day: "numeric" });
}

function conversationPreviewText(conversation) {
  const preview = stripMarkdownToText(conversation.last_message_preview || "");
  if (!preview) {
    return "No replies yet";
  }
  return clipCopy(preview, 42);
}

function conversationLabel(conversation) {
  return conversation.title || conversation.last_message_preview || "New conversation";
}

function formatRole(role) {
  if (role === "assistant") {
    return "Assistant";
  }
  if (role === "user") {
    return "You";
  }
  return "System";
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function formatBytes(byteSize) {
  if (!byteSize) {
    return "";
  }
  if (byteSize < 1024) {
    return `${byteSize} B`;
  }
  if (byteSize < 1024 * 1024) {
    return `${(byteSize / 1024).toFixed(1)} KB`;
  }
  return `${(byteSize / (1024 * 1024)).toFixed(1)} MB`;
}

function attachmentRouteCopy(attachment) {
  const loweredName = String(attachment.displayName || "").toLowerCase();
  const mediaType = String(attachment.mediaType || "").toLowerCase();
  if (attachment.kind === "image") {
    return attachment.careContext === "medical" ? "Medical route after send" : "Local OCR after send";
  }
  if (attachment.kind === "video") {
    return "Video sampling after send";
  }
  if (mediaType.includes("pdf") || loweredName.endsWith(".pdf")) {
    return "PDF preview after send";
  }
  if (mediaType.includes("markdown") || loweredName.endsWith(".md")) {
    return "Markdown preview after send";
  }
  if (mediaType.startsWith("text/") || loweredName.endsWith(".txt")) {
    return "Text preview after send";
  }
  return "Local file attached";
}

function attachmentStatusCopy(attachment) {
  if (attachment.uploadState === "uploading") {
    return `Uploading ${Math.round((attachment.uploadProgress || 0) * 100)}%`;
  }
  if (attachment.uploadState === "done") {
    return "Saved locally";
  }
  if (attachment.uploadState === "failed") {
    return "Upload failed";
  }
  return "Queued for local review";
}

function attachmentProgressValue(attachment) {
  if (attachment.uploadState === "done" || attachment.uploadState === "failed") {
    return 1;
  }
  return Math.max(0, Math.min(1, attachment.uploadProgress || 0));
}

function guessAssetKind(mediaType, displayName) {
  const lowered = (displayName || "").toLowerCase();
  if (mediaType?.startsWith("image/")) {
    return "image";
  }
  if (mediaType?.startsWith("video/")) {
    return "video";
  }
  if (mediaType?.startsWith("audio/")) {
    return "audio";
  }
  if (mediaType?.startsWith("text/") || mediaType === "application/pdf") {
    return "document";
  }
  if (/\.(png|jpe?g|webp|gif)$/i.test(lowered)) {
    return "image";
  }
  if (/\.(mp4|mov|webm)$/i.test(lowered)) {
    return "video";
  }
  if (/\.(pdf|txt|md)$/i.test(lowered)) {
    return "document";
  }
  return "other";
}

function humanizeToolName(name) {
  return String(name || "")
    .split("_")
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function hasLiveCameraSupport() {
  return Boolean(navigator.mediaDevices?.getUserMedia);
}

function hasRecordingSupport() {
  return typeof MediaRecorder !== "undefined";
}

function preferredRecorderMimeType() {
  if (!hasRecordingSupport() || typeof MediaRecorder.isTypeSupported !== "function") {
    return "";
  }
  const candidates = [
    "video/mp4;codecs=h264",
    "video/mp4",
    "video/webm;codecs=vp9",
    "video/webm;codecs=vp8",
    "video/webm",
  ];
  return candidates.find((candidate) => MediaRecorder.isTypeSupported(candidate)) || "";
}

function extensionForVideoType(mimeType) {
  if (!mimeType) {
    return "webm";
  }
  if (mimeType.includes("mp4")) {
    return "mp4";
  }
  if (mimeType.includes("quicktime")) {
    return "mov";
  }
  return "webm";
}

function timestampFileSlug() {
  return new Date().toISOString().replace(/[:.]/g, "-");
}

function cameraFramePrompt() {
  return "Review this live camera frame conservatively, noting visible tools, people, machines, and any process concerns without overclaiming.";
}

function formatRelativeTime(date) {
  return date.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

function startsRichBlock(line) {
  const trimmed = line.trim();
  if (!trimmed) {
    return false;
  }
  return (
    /^```/.test(trimmed) ||
    /^#{1,3}\s+/.test(trimmed) ||
    /^>\s?/.test(trimmed) ||
    /^[-*+]\s+/.test(trimmed) ||
    /^\d+\.\s+/.test(trimmed)
  );
}

function renderInlineMarkdown(text) {
  let html = escapeHtml(text);
  html = html.replace(/`([^`]+)`/g, "<code>$1</code>");
  html = html.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  html = html.replace(/(^|[\s(])\*([^*]+)\*(?=[\s).,!?:;]|$)/g, "$1<em>$2</em>");
  return html;
}

function renderPlainText(text) {
  return escapeHtml(text).replace(/\n/g, "<br />");
}

function latestMessageProcess(message) {
  if (!message?.process?.length) {
    return null;
  }
  return message.process[message.process.length - 1];
}

function messagePanelKey(message, section = "context") {
  const base = message.id || message.turnId || "";
  return base ? `${base}:${section}` : "";
}

function isMessagePanelExpanded(message, section = "context") {
  const key = messagePanelKey(message, section);
  if (!key) {
    return false;
  }
  return Boolean(state.messagePanels.get(key));
}

function setMessagePanelExpanded(message, section, expanded) {
  const key = messagePanelKey(message, section);
  if (!key) {
    return;
  }
  state.messagePanels.set(key, Boolean(expanded));
  persistMessagePanels();
}

function stripAssistantApprovalBoilerplate(content) {
  const rawLines = String(content || "").replace(/\r\n?/g, "\n").split("\n");
  const filtered = [];
  let previousBlank = true;
  for (const line of rawLines) {
    const trimmed = line.trim();
    const normalized = stripMarkdownToText(trimmed);
    if (!trimmed) {
      if (!previousBlank && filtered.length) {
        filtered.push("");
      }
      previousBlank = true;
      continue;
    }
    if (
      /^i can (save|create|write|log)\b/i.test(normalized) ||
      /^tool action detected:?/i.test(normalized) ||
      /^i will now\b/i.test(normalized) ||
      /^i prepared a .*ready for your approval\.?$/i.test(normalized) ||
      /^please approve\b/i.test(normalized) ||
      /^approval required:?/i.test(normalized) ||
      /^please confirm if you approve this action\b/i.test(normalized) ||
      /^please confirm if you want me to proceed\b/i.test(normalized) ||
      /^please confirm if you want me to generate\b/i.test(normalized) ||
      /^action:\s+/i.test(normalized) ||
      /^content summary:/i.test(normalized)
    ) {
      continue;
    }
    filtered.push(line);
    previousBlank = false;
  }
  return filtered.join("\n").replace(/\n{3,}/g, "\n\n").trim();
}

function sanitizeAssistantDisplayContent(content) {
  const rawLines = String(content || "").replace(/\r\n?/g, "\n").split("\n");
  const filtered = [];
  let previousBlank = true;

  for (const line of rawLines) {
    const trimmed = line.trim();
    const normalized = stripMarkdownToText(trimmed);

    if (!trimmed) {
      if (!previousBlank && filtered.length) {
        filtered.push("");
      }
      previousBlank = true;
      continue;
    }

    if (normalized === "*" || normalized === "-" || normalized === "---") {
      continue;
    }

    filtered.push(line);
    previousBlank = false;
  }

  return filtered.join("\n").replace(/\n{3,}/g, "\n\n").trim();
}

function messageDisplayContent(message) {
  let content = String(message.content || "").trim();
  if (!content) {
    return "";
  }
  if (message.role === "assistant" && message.approval) {
    content = stripAssistantApprovalBoilerplate(content);
  }
  if (message.role === "assistant") {
    content = sanitizeAssistantDisplayContent(content);
  }
  return content;
}

function shouldSuppressMessage(message) {
  if (!message || message.role !== "system") {
    return false;
  }
  const plain = stripMarkdownToText(String(message.content || "")).trim().toLowerCase();
  return (
    plain === "workspace agent actions are limited to the configured local workspace scope." ||
    plain === "exports should produce an audit record."
  );
}

function shouldCollapseMessageContent(message, content) {
  if (!content || message.role !== "assistant") {
    return false;
  }
  if (message.approval) {
    return false;
  }
  if (!message.agentRun) {
    return false;
  }
  const plain = stripMarkdownToText(content);
  const lineCount = content.split(/\r?\n/).filter((line) => line.trim()).length;
  const richBlockCount = (content.match(/^#{1,6}\s+|^[-*+]\s+|^\d+\.\s+/gm) || []).length;
  return plain.length > 420 || lineCount > 8 || richBlockCount > 4;
}

function presentAssistantLoadingCopy(message) {
  const latest = latestMessageProcess(message);
  if (message.agentRun) {
    return "Reviewing local workspace material.";
  }
  if (message.approval || message.proposedTool) {
    return "Preparing a local draft for review.";
  }
  if (latest?.kind === "retrieval") {
    return "Reviewing local material.";
  }
  if (latest?.kind === "vision") {
    return "Reviewing the attached media locally.";
  }
  if (latest?.kind === "tool") {
    return "Preparing a local action.";
  }
  return "Preparing a local reply.";
}

function renderAssistantLoadingMarkup(message, content = undefined) {
  const visibleContent = typeof content === "string" ? content : messageDisplayContent(message);
  if (message.role !== "assistant" || !message.loading || visibleContent) {
    return "";
  }

  return `
    <section class="assistant-loading" aria-live="polite">
      <div class="assistant-loading-lines" aria-hidden="true">
        <span class="assistant-loading-line is-long"></span>
        <span class="assistant-loading-line is-medium"></span>
        <span class="assistant-loading-line is-short"></span>
      </div>
      <p class="assistant-loading-copy">${escapeHtml(presentAssistantLoadingCopy(message))}</p>
    </section>
  `;
}

function renderMarkdownBlocks(text) {
  const normalized = String(text || "").replace(/\r\n?/g, "\n").trim();
  if (!normalized) {
    return "";
  }

  const lines = normalized.split("\n");
  const blocks = [];
  let index = 0;

  while (index < lines.length) {
    const current = lines[index];
    const trimmed = current.trim();

    if (!trimmed) {
      index += 1;
      continue;
    }

    const codeFence = trimmed.match(/^```([\w-]+)?\s*$/);
    if (codeFence) {
      const language = codeFence[1] ? ` data-lang="${escapeHtml(codeFence[1])}"` : "";
      const codeLines = [];
      index += 1;
      while (index < lines.length && !lines[index].trim().startsWith("```")) {
        codeLines.push(lines[index]);
        index += 1;
      }
      if (index < lines.length) {
        index += 1;
      }
      blocks.push(
        `<pre class="message-pre"><code${language}>${escapeHtml(codeLines.join("\n"))}</code></pre>`,
      );
      continue;
    }

    const heading = trimmed.match(/^(#{1,3})\s+(.*)$/);
    if (heading) {
      const level = Math.min(5, 2 + heading[1].length);
      blocks.push(
        `<h${level} class="message-heading">${renderInlineMarkdown(heading[2])}</h${level}>`,
      );
      index += 1;
      continue;
    }

    if (/^>\s?/.test(trimmed)) {
      const quoteLines = [];
      while (index < lines.length && /^>\s?/.test(lines[index].trim())) {
        quoteLines.push(lines[index].trim().replace(/^>\s?/, ""));
        index += 1;
      }
      blocks.push(
        `<blockquote class="message-quote">${renderMarkdownBlocks(quoteLines.join("\n"))}</blockquote>`,
      );
      continue;
    }

    if (/^[-*+]\s+/.test(trimmed)) {
      const items = [];
      while (index < lines.length && /^[-*+]\s+/.test(lines[index].trim())) {
        const line = lines[index].trim();
        const taskItem = line.match(/^[-*+]\s+\[( |x)\]\s+(.*)$/i);
        if (taskItem) {
          items.push({
            checked: taskItem[1].toLowerCase() === "x",
            content: taskItem[2],
            task: true,
          });
        } else {
          items.push({
            checked: false,
            content: line.replace(/^[-*+]\s+/, ""),
            task: false,
          });
        }
        index += 1;
      }
      const hasTaskItems = items.some((item) => item.task);
      blocks.push(
        `<ul class="message-list${hasTaskItems ? " is-task-list" : ""}">${items
          .map((item) => {
            const marker = item.task
              ? `<span class="task-marker${item.checked ? " is-checked" : ""}">${
                  item.checked ? "✓" : ""
                }</span>`
              : "";
            return `<li class="message-list-item${item.checked ? " is-checked" : ""}">${marker}<span>${renderInlineMarkdown(item.content)}</span></li>`;
          })
          .join("")}</ul>`,
      );
      continue;
    }

    if (/^\d+\.\s+/.test(trimmed)) {
      const items = [];
      while (index < lines.length && /^\d+\.\s+/.test(lines[index].trim())) {
        items.push(lines[index].trim().replace(/^\d+\.\s+/, ""));
        index += 1;
      }
      blocks.push(
        `<ol class="message-list is-ordered">${items
          .map((item) => `<li class="message-list-item"><span>${renderInlineMarkdown(item)}</span></li>`)
          .join("")}</ol>`,
      );
      continue;
    }

    const paragraphLines = [];
    while (index < lines.length && lines[index].trim() && !startsRichBlock(lines[index])) {
      paragraphLines.push(lines[index].trim());
      index += 1;
    }
    blocks.push(
      `<p>${paragraphLines.map((line) => renderInlineMarkdown(line)).join("<br />")}</p>`,
    );
  }

  return blocks.join("");
}

function renderMessageContent(message, overrideContent = undefined) {
  const content = typeof overrideContent === "string" ? overrideContent : messageDisplayContent(message);
  if (!content) {
    return "";
  }

  const richTextRoles = new Set(["assistant", "system"]);
  const collapsible = shouldCollapseMessageContent(message, content);
  const expanded = collapsible ? isMessagePanelExpanded(message, "context") : false;
  const body = richTextRoles.has(message.role)
    ? renderMarkdownBlocks(content)
    : `<p>${renderPlainText(content)}</p>`;

  return `
    <div class="message-content-shell${collapsible ? " is-collapsible" : ""}${expanded ? " is-expanded" : ""}">
      <div class="message-content${richTextRoles.has(message.role) ? " rich-text" : ""}">${body}</div>
      ${
        collapsible
          ? `<button
              class="message-content-toggle"
              data-message-content-toggle="${escapeHtml(messagePanelKey(message, "context"))}"
              type="button"
              aria-expanded="${String(expanded)}"
            >${expanded ? "Show less" : "Show more"}</button>`
          : ""
      }
    </div>
  `;
}

function renderApprovalPreview(approval, overridePayload = undefined) {
  const payload = approvalEffectivePayload(approval, overridePayload);
  if (!payload || !Object.keys(payload).length) {
    return "";
  }
  const previewContent = approvalPreviewContent(approval, payload);
  const previewSummary = approvalPayloadExcerpt(approval, payload);
  const meta = approvalPayloadMeta(approval, payload)
    .map((bit) => `<span>${escapeHtml(bit)}</span>`)
    .join("");

  return `
    <section class="approval-preview">
      ${
        previewContent
          ? `<div class="approval-preview-body rich-text">${renderMarkdownBlocks(previewContent)}</div>`
          : previewSummary
            ? `<p class="approval-preview-summary">${escapeHtml(previewSummary)}</p>`
            : ""
      }
      ${meta ? `<div class="approval-preview-meta">${meta}</div>` : ""}
    </section>
  `;
}

function renderApprovalEditor(approval) {
  if (!approval?.payload || approval.status !== "pending") {
    return "";
  }

  const payload = approvalEffectivePayload(approval);
  const isDirty = approvalHasDraftChanges(approval, payload);
  const draftStateText = approvalDraftStateText({ dirty: isDirty });
  const groundingNotice = approvalGroundingNotice(approval, payload);
  const errorMessage = approvalErrorFor(approval.id);
  if (approval.tool_name === "create_task") {
    return `
      <section class="approval-editor approval-editor-task" data-approval-editor="${approval.id}">
        <div class="approval-editor-header">
          <div class="approval-editor-copy">
            <strong>Editing locally</strong>
            <span>Adjust the task before you save it.</span>
          </div>
          <div class="approval-editor-controls">
            <span class="approval-editor-state${isDirty ? " is-dirty" : ""}" data-approval-draft-state>${draftStateText}</span>
            <button class="approval-editor-reset" data-approval-reset type="button"${isDirty ? "" : " disabled"}>Revert</button>
          </div>
        </div>
        ${groundingNotice ? `<p class="approval-grounding-note">${escapeHtml(groundingNotice)}</p>` : ""}
        <p class="approval-editor-error"${errorMessage ? "" : " hidden"} data-approval-error>${escapeHtml(errorMessage)}</p>
        <div class="approval-editor-grid approval-editor-grid-task">
          <label class="approval-field approval-field-full">
            <span>Title</span>
            <input data-approval-field="title" name="approval_title" type="text" value="${escapeHtml(payload.title || "")}" />
          </label>
          <label class="approval-field approval-field-full">
            <span>Details</span>
            <textarea data-approval-field="details" name="approval_details" rows="5">${escapeHtml(payload.details || "")}</textarea>
          </label>
          <label class="approval-field approval-field-status">
            <span>Status</span>
            <select data-approval-field="status">
              ${["open", "in_progress", "blocked", "done"]
                .map(
                  (status) =>
                    `<option value="${status}"${payload.status === status ? " selected" : ""}>${escapeHtml(humanizeRunStatus(status))}</option>`,
                )
                .join("")}
            </select>
          </label>
        </div>
      </section>
    `;
  }

  if (["create_note", "create_report", "create_message_draft", "create_checklist", "log_observation", "export_brief"].includes(approval.tool_name)) {
    const helperCopy =
      approval.tool_name === "create_checklist"
        ? "Adjust the checklist title or items before you save it."
        : approval.tool_name === "create_report"
          ? "Adjust the report title or content before you save it."
          : approval.tool_name === "create_message_draft"
            ? "Adjust the message title or content before you save it."
        : approval.tool_name === "export_brief"
          ? "Adjust the export title or content before you save it."
        : "Adjust the draft before you save it.";
    return `
      <section class="approval-editor approval-editor-simple" data-approval-editor="${approval.id}">
        <div class="approval-editor-header">
          <div class="approval-editor-copy">
            <strong>Editing locally</strong>
            <span>${escapeHtml(helperCopy)}</span>
          </div>
          <div class="approval-editor-controls">
            <span class="approval-editor-state${isDirty ? " is-dirty" : ""}" data-approval-draft-state>${draftStateText}</span>
            <button class="approval-editor-reset" data-approval-reset type="button"${isDirty ? "" : " disabled"}>Revert</button>
          </div>
        </div>
        ${groundingNotice ? `<p class="approval-grounding-note">${escapeHtml(groundingNotice)}</p>` : ""}
        <p class="approval-editor-error"${errorMessage ? "" : " hidden"} data-approval-error>${escapeHtml(errorMessage)}</p>
        <div class="approval-editor-grid">
          <label class="approval-field approval-field-full">
            <span>Title</span>
            <input data-approval-field="title" name="approval_title" type="text" value="${escapeHtml(payload.title || "")}" />
          </label>
          <label class="approval-field approval-field-full">
            <span>${
              approval.tool_name === "create_checklist"
                ? "Checklist content"
                : approval.tool_name === "create_report"
                  ? "Report content"
                  : approval.tool_name === "create_message_draft"
                    ? "Message draft"
                : approval.tool_name === "export_brief"
                  ? "Markdown content"
                  : "Content"
            }</span>
            <textarea data-approval-field="content" name="approval_content" rows="${approval.tool_name === "create_checklist" ? "6" : "5"}">${escapeHtml(payload.content || "")}</textarea>
          </label>
        </div>
      </section>
    `;
  }

  return `
    <section class="approval-editor approval-editor-advanced" data-approval-editor="${approval.id}">
      <div class="approval-editor-header">
        <div class="approval-editor-copy">
          <strong>Editing locally</strong>
          <span>Advanced fields stay local until you save them.</span>
        </div>
        <div class="approval-editor-controls">
          <span class="approval-editor-state${isDirty ? " is-dirty" : ""}" data-approval-draft-state>${draftStateText}</span>
          <button class="approval-editor-reset" data-approval-reset type="button"${isDirty ? "" : " disabled"}>Revert</button>
        </div>
      </div>
      ${groundingNotice ? `<p class="approval-grounding-note">${escapeHtml(groundingNotice)}</p>` : ""}
      <p class="approval-editor-error"${errorMessage ? "" : " hidden"} data-approval-error>${escapeHtml(errorMessage)}</p>
      <div class="approval-editor-grid">
        <label class="approval-field approval-field-code approval-field-full">
          <span>Payload JSON</span>
          <textarea data-approval-json name="approval_json" rows="7">${escapeHtml(JSON.stringify(payload, null, 2))}</textarea>
        </label>
      </div>
    </section>
  `;
}

function approvalUsesInlineCanvas(approval) {
  return (
    approval?.status === "pending" &&
    ["create_note", "create_report", "create_message_draft", "create_checklist", "export_brief", "log_observation"].includes(
      approval.tool_name,
    )
  );
}

function approvalCanvasFieldLabel(approval) {
  switch (approval?.tool_name) {
    case "create_checklist":
      return "Checklist";
    case "create_report":
      return "Report";
    case "create_message_draft":
      return "Message";
    case "export_brief":
      return "Markdown";
    case "log_observation":
      return "Observation";
    default:
      return "Draft";
  }
}

function approvalCanvasPlaceholder(approval) {
  switch (approval?.tool_name) {
    case "create_report":
      return "Draft the report here.";
    case "create_checklist":
      return "Draft the checklist here.";
    case "create_message_draft":
      return "Draft the message here.";
    case "create_note":
      return "Write the note here.";
    case "log_observation":
      return "Write the observation here.";
    case "export_brief":
      return "Write the markdown here.";
    default:
      return "Write here.";
  }
}

function approvalCanvasTitleLabel(approval) {
  switch (approval?.tool_name) {
    case "create_report":
      return "Report title";
    case "create_checklist":
      return "Checklist title";
    case "create_message_draft":
      return "Message title";
    case "create_note":
      return "Note title";
    case "export_brief":
      return "Export title";
    case "log_observation":
      return "Observation title";
    default:
      return "Draft title";
  }
}

function approvalCanvasOrigin(approval) {
  const reason = approvalReasonCopy(approval).trim();
  if (!reason || reason === "From this conversation.") {
    return "";
  }
  return reason;
}

function renderDocumentEditHistory(approval) {
  const edits = documentEditsForApproval(approval?.id);
  if (!edits.length) {
    return "";
  }
  const latest = edits.slice(-3).reverse();
  return `
    <section class="approval-canvas-history" data-document-edit-history>
      <div class="approval-canvas-history-header">
        <span>Edit history</span>
        <span>${edits.length} ${edits.length === 1 ? "edit" : "edits"}</span>
      </div>
      <ol class="approval-canvas-history-list">
        ${latest
          .map(
            (edit) => `
              <li class="approval-canvas-history-item" data-document-edit-item="${escapeHtml(edit.id)}">
                <div class="approval-canvas-history-meta">
                  <span>${escapeHtml(documentEditActionLabel(edit.action))}</span>
                  <span>${escapeHtml(edit.fieldName)}</span>
                </div>
                <div class="approval-canvas-history-diff">
                  <span class="approval-canvas-history-before">${escapeHtml(clipCopy(edit.beforeText, 96))}</span>
                  <span class="approval-canvas-history-arrow" aria-hidden="true">-&gt;</span>
                  <span class="approval-canvas-history-after">${escapeHtml(clipCopy(edit.afterText, 96))}</span>
                </div>
              </li>
            `,
          )
          .join("")}
      </ol>
    </section>
  `;
}

function renderApprovalCanvas(approval) {
  const payload = approvalEffectivePayload(approval);
  const isDirty = approvalHasDraftChanges(approval, payload);
  const draftStateText = approvalCanvasStateText({ dirty: isDirty });
  const groundingNotice = approvalGroundingNotice(approval, payload);
  const errorMessage = approvalErrorFor(approval.id);
  const canvasContent = approvalCanvasContent(approval, payload);
  const originCopy = approvalCanvasOrigin(approval);
  const editHistory = renderDocumentEditHistory(approval);
  const canvasCollapsed = isApprovalCanvasCollapsed(approval);
  const canvasPreview = canvasContent || approvalPayloadExcerpt(approval, payload) || approvalReasonCopy(approval);
  const editorId = `approval-editor-${approval.id}`;
  const collapseLabel = canvasCollapsed ? "Expand canvas" : "Collapse canvas";

  return `
    <section class="approval-canvas approval-canvas-${escapeHtml(approval.tool_name)}${canvasCollapsed ? " is-collapsed" : ""}">
      <div class="approval-canvas-header">
        <div class="approval-canvas-toolbar">
          <div class="approval-canvas-meta">
            <span class="approval-canvas-kicker">${escapeHtml(approvalSurfaceNoun(approval.tool_name))} draft</span>
            ${originCopy ? `<span class="approval-canvas-origin">${escapeHtml(originCopy)}</span>` : ""}
          </div>
          <div class="approval-canvas-controls">
            <span class="approval-editor-state approval-canvas-state${isDirty ? " is-dirty" : ""}" data-approval-draft-state>${draftStateText}</span>
            <button
              class="approval-canvas-collapse-toggle"
              data-approval-canvas-collapse
              data-approval-id="${escapeHtml(approval.id)}"
              type="button"
              aria-controls="${escapeHtml(editorId)}"
              aria-expanded="${String(!canvasCollapsed)}"
              title="${escapeHtml(collapseLabel)}"
            >${escapeHtml(collapseLabel)}</button>
            <button class="approval-editor-reset" data-approval-reset type="button"${isDirty ? "" : " disabled"}>Revert</button>
            <button class="approval-action reject" data-approval-action="reject" data-approval-id="${approval.id}" type="button">Dismiss</button>
            <button class="approval-action approve" data-approval-action="approve" data-approval-id="${approval.id}" type="button">${escapeHtml(approvalPrimaryActionLabel(approval))}</button>
          </div>
        </div>
        <label class="approval-canvas-heading">
          <span class="visually-hidden">${escapeHtml(approvalCanvasTitleLabel(approval))}</span>
          <input
            class="approval-canvas-title-input"
            data-approval-field="title"
            aria-label="${escapeHtml(approvalCanvasTitleLabel(approval))}"
            name="approval_title"
            type="text"
            placeholder="Untitled ${escapeHtml(approvalSurfaceNoun(approval.tool_name))}"
            value="${escapeHtml(payload.title || "")}"
          />
        </label>
      </div>
      ${groundingNotice ? `<p class="approval-grounding-note">${escapeHtml(groundingNotice)}</p>` : ""}
      <p class="approval-editor-error"${errorMessage ? "" : " hidden"} data-approval-error>${escapeHtml(errorMessage)}</p>
      <p class="approval-canvas-selection" data-canvas-selection-hint hidden></p>
      <section class="approval-canvas-collapsed-preview"${canvasCollapsed ? "" : " hidden"}>
        <span>Canvas tucked away</span>
        <p>${escapeHtml(clipCopy(canvasPreview, 220))}</p>
        <button
          class="approval-canvas-collapse-toggle"
          data-approval-canvas-collapse
          data-approval-id="${escapeHtml(approval.id)}"
          type="button"
          aria-controls="${escapeHtml(editorId)}"
          aria-expanded="false"
          title="Expand canvas to edit"
        >Expand to edit</button>
      </section>
      <section
        class="approval-editor approval-editor-canvas"
        id="${escapeHtml(editorId)}"
        data-approval-editor="${approval.id}"
        ${canvasCollapsed ? "hidden" : ""}
      >
        <textarea
          class="approval-canvas-textarea"
          data-approval-field="content"
          aria-label="${escapeHtml(approvalCanvasFieldLabel(approval))} content"
          name="approval_content"
          rows="12"
          placeholder="${escapeHtml(approvalCanvasPlaceholder(approval))}"
        >${escapeHtml(canvasContent)}</textarea>
      </section>
      ${editHistory}
    </section>
  `;
}

function latestArtifactApproval() {
  const messages = activeMessages();
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const workProduct = messages[index].workProduct || messages[index].approval;
    if (workProduct?.id) {
      return workProduct;
    }
  }
  return null;
}

function artifactFileKind(approval) {
  switch (approval?.tool_name) {
    case "create_report":
      return "Report";
    case "create_note":
      return "Note";
    case "create_message_draft":
      return "Draft";
    case "create_checklist":
      return "Checklist";
    case "export_brief":
      return "Brief";
    case "log_observation":
      return "Observation";
    case "create_task":
      return "Task";
    default:
      return approvalSurfaceNoun(approval?.tool_name || "artifact");
  }
}

function renderArtifactEditLedger(edits) {
  if (!edits.length) {
    return "";
  }
  return `
    <section class="artifact-edit-ledger">
      <div class="artifact-edit-ledger-header">
        <span>Edit history</span>
        <strong>${edits.length}</strong>
      </div>
      ${edits
        .slice(0, 3)
        .map(
          (edit) => `
            <div class="artifact-edit-row">
              <span>${escapeHtml(documentEditActionLabel(edit.action))}</span>
              <p>${escapeHtml(clipCopy(edit.afterText, 140))}</p>
            </div>
          `,
        )
        .join("")}
    </section>
  `;
}

function artifactPreviewLines(content, limit = 5) {
  return approvalMeaningfulLines(content)
    .filter((line) => !approvalLooksLikeInventoryLine(line))
    .slice(0, limit);
}

function artifactChecklistItems(content, limit = 7) {
  return String(content || "")
    .replace(/\r\n?/g, "\n")
    .split("\n")
    .map((line) => line.trim())
    .map((line) => {
      const checklistMatch = line.match(/^[-*+]\s+\[([ xX])\]\s+(.+)$/);
      if (checklistMatch) {
        return { text: stripMarkdownToText(checklistMatch[2]), checked: checklistMatch[1].toLowerCase() === "x" };
      }
      const bulletMatch = line.match(/^[-*+]\s+(.+)$/) || line.match(/^\d+\.\s+(.+)$/);
      return bulletMatch ? { text: stripMarkdownToText(bulletMatch[1]), checked: false } : null;
    })
    .filter((item) => item?.text)
    .slice(0, limit);
}

function renderArtifactTypePreview({ approval, payload, title, kind, statusLabel, previewContent }) {
  const content = previewContent || payload?.details || approvalPayloadExcerpt(approval, payload);
  const lines = artifactPreviewLines(content, 5);
  const displayTitle = artifactPreviewTitle(title);
  const escapedFullTitle = escapeHtml(title);
  const escapedDisplayTitle = escapeHtml(displayTitle);
  const lineMarkup = lines
    .map((line) => `<li>${escapeHtml(clipCopy(line, 120))}</li>`)
    .join("");
  const meta = approvalPayloadMeta(approval, payload);
  const metaMarkup = meta.length
    ? `<div class="artifact-type-meta">${meta.map((item) => `<span>${escapeHtml(item)}</span>`).join("")}</div>`
    : "";

  switch (approval?.tool_name) {
    case "create_checklist": {
      const items = artifactChecklistItems(payload?.content || content, 7);
      return `
        <article class="artifact-type-card artifact-type-checklist">
          <header>
            <span>${escapeHtml(kind)}</span>
            <strong title="${escapedFullTitle}">${escapedDisplayTitle}</strong>
          </header>
          ${metaMarkup}
          <ol class="artifact-checklist-preview">
            ${(items.length ? items : [{ text: approvalPayloadExcerpt(approval, payload) || "Checklist is ready for review.", checked: false }])
              .map(
                (item) => `
                  <li>
                    <span class="artifact-check${item.checked ? " is-checked" : ""}" aria-hidden="true"></span>
                    <span>${escapeHtml(clipCopy(item.text, 100))}</span>
                  </li>
                `,
              )
              .join("")}
          </ol>
        </article>
      `;
    }
    case "create_message_draft": {
      const body = lines.slice(0, 3).join(" ") || approvalPayloadExcerpt(approval, payload) || "Message draft ready.";
      return `
        <article class="artifact-type-card artifact-type-message">
          <header>
            <span>Message draft</span>
            <strong title="${escapedFullTitle}">${escapedDisplayTitle}</strong>
          </header>
          <div class="artifact-message-envelope">
            <span>Drafted locally</span>
            <p>${escapeHtml(clipCopy(body, 260))}</p>
          </div>
        </article>
      `;
    }
    case "create_task": {
      const details = payload?.details || approvalPayloadExcerpt(approval, payload) || "Task details are ready.";
      return `
        <article class="artifact-type-card artifact-type-task">
          <header>
            <span>Task</span>
            <strong title="${escapedFullTitle}">${escapedDisplayTitle}</strong>
          </header>
          <div class="artifact-task-board">
            <span>${escapeHtml(statusLabel)}</span>
            <p>${escapeHtml(clipCopy(details, 260))}</p>
          </div>
        </article>
      `;
    }
    case "log_observation": {
      return `
        <article class="artifact-type-card artifact-type-observation">
          <header>
            <span>Observation</span>
            <strong title="${escapedFullTitle}">${escapedDisplayTitle}</strong>
          </header>
          <blockquote>${escapeHtml(clipCopy(lines.join(" ") || approvalPayloadExcerpt(approval, payload), 320))}</blockquote>
        </article>
      `;
    }
    case "export_brief": {
      const headingCount = String(payload?.content || "")
        .split(/\r?\n/)
        .filter((line) => /^#{1,6}\s+/.test(line.trim())).length;
      return `
        <article class="artifact-type-card artifact-type-export">
          <header>
            <span>Markdown export</span>
            <strong title="${escapedFullTitle}">${escapedDisplayTitle}</strong>
          </header>
          <div class="artifact-export-grid">
            <span>${headingCount || "Ready"} sections</span>
            <span>${escapeHtml(statusLabel)}</span>
          </div>
          ${lineMarkup ? `<ul>${lineMarkup}</ul>` : ""}
        </article>
      `;
    }
    default:
      return `
        <article class="artifact-type-card artifact-type-generic">
          <header>
            <span>${escapeHtml(kind)}</span>
            <strong title="${escapedFullTitle}">${escapedDisplayTitle}</strong>
          </header>
          ${lineMarkup ? `<ul>${lineMarkup}</ul>` : `<p>${escapeHtml(approvalPayloadExcerpt(approval, payload) || "Ready for local review.")}</p>`}
        </article>
      `;
  }
}

function renderArtifactSummarySurface({ approval, payload, title, kind, statusLabel, contentMarkup, editMarkup, previewContent }) {
  const typePreview = renderArtifactTypePreview({ approval, payload, title, kind, statusLabel, previewContent });
  const displayTitle = artifactPreviewTitle(title);
  return `
    <div class="artifact-preview-scroll" data-artifact-mode-panel="summary">
      ${typePreview}
      <article class="artifact-page artifact-cover-page">
        <div class="artifact-page-hero artifact-cover-hero">
          <span>${escapeHtml(kind)}</span>
          <h3 title="${escapeHtml(title)}">${escapeHtml(displayTitle)}</h3>
          <p>${escapeHtml(approvalReasonCopy(approval))}</p>
        </div>
        <footer class="artifact-page-footer">
          <span>${escapeHtml(statusLabel)}</span>
          <strong>LOCAL ASSISTANT</strong>
        </footer>
      </article>
      <article class="artifact-page artifact-content-page">
        <div class="artifact-page-ribbon">
          <strong>${escapeHtml(clip(title, 72))}</strong>
        </div>
        <section class="artifact-page-body rich-text">
          ${contentMarkup}
        </section>
        <footer class="artifact-page-footer">
          <span>Local workspace preview</span>
          <strong>GEMMA LOCAL</strong>
        </footer>
      </article>
      ${editMarkup}
    </div>
  `;
}

function renderArtifactCanvasSurface({ approval, payload, title, statusLabel, editMarkup }) {
  const canvasContent = approvalCanvasContent(approval, payload) || approvalPreviewContent(approval, payload);
  const bodyMarkup = canvasContent
    ? renderMarkdownBlocks(canvasContent)
    : `<p>This canvas is ready for drafting.</p>`;
  return `
    <div class="artifact-preview-scroll artifact-canvas-scroll" data-artifact-mode-panel="canvas">
      <section class="artifact-canvas-workspace">
        <header class="artifact-canvas-workspace-header">
          <div>
            <span>Canvas draft</span>
            <h3>${escapeHtml(title)}</h3>
          </div>
          <div class="artifact-canvas-actions">
            <span>${escapeHtml(statusLabel)}</span>
            <button class="artifact-open" data-artifact-open="${escapeHtml(approval.id)}" type="button">Focus editor</button>
          </div>
        </header>
        <article class="artifact-canvas-sheet">
          <div class="artifact-canvas-paper-topline">
            <span>${escapeHtml(artifactFileKind(approval))}</span>
            <span>Live canvas</span>
          </div>
          <h4>${escapeHtml(title)}</h4>
          <section class="artifact-canvas-body rich-text">
            ${bodyMarkup}
          </section>
        </article>
        ${editMarkup}
      </section>
    </div>
  `;
}

function activeWorkspaceAssets(limit = 8) {
  const assets = [];
  const seen = new Set();
  for (const message of [...activeMessages()].reverse()) {
    for (const asset of [...(message.assets || [])].reverse()) {
      if (!asset?.id || seen.has(asset.id)) {
        continue;
      }
      seen.add(asset.id);
      assets.push(asset);
      if (assets.length >= limit) {
        return assets;
      }
    }
  }
  return assets;
}

function artifactAssetKindLabel(asset) {
  if (!asset) {
    return "File";
  }
  const mediaType = String(asset.media_type || "").toLowerCase();
  if (asset.kind === "image") {
    return asset.care_context === "medical" ? "Medical image" : "Image";
  }
  if (asset.kind === "video") {
    return "Video";
  }
  if (mediaType.includes("pdf") || String(asset.display_name || "").toLowerCase().endsWith(".pdf")) {
    return "PDF";
  }
  if (mediaType.includes("markdown") || String(asset.display_name || "").toLowerCase().endsWith(".md")) {
    return "Markdown";
  }
  if (mediaType.includes("text")) {
    return "Text file";
  }
  return "File";
}

function artifactAssetRouteLabel(asset) {
  const mediaType = String(asset.media_type || "").toLowerCase();
  const displayName = String(asset.display_name || "").toLowerCase();
  if (asset.kind === "image") {
    return asset.care_context === "medical" ? "Medical review route" : "Local OCR route";
  }
  if (asset.kind === "video") {
    return "Video sampling route";
  }
  if (mediaType.includes("pdf") || displayName.endsWith(".pdf")) {
    return "Native PDF preview";
  }
  if (mediaType.includes("markdown") || displayName.endsWith(".md")) {
    return "Native Markdown preview";
  }
  if (mediaType.startsWith("text/") || displayName.endsWith(".txt")) {
    return "Native text preview";
  }
  return "Local file context";
}

function artifactDocumentPreviewType(asset) {
  const mediaType = String(asset?.media_type || "").toLowerCase();
  const displayName = String(asset?.display_name || "").toLowerCase();
  if (mediaType.includes("pdf") || displayName.endsWith(".pdf")) {
    return "pdf";
  }
  if (mediaType.includes("markdown") || displayName.endsWith(".md")) {
    return "markdown";
  }
  if (mediaType.startsWith("text/") || displayName.endsWith(".txt")) {
    return "text";
  }
  return "";
}

function assetPreviewCacheKey(asset) {
  return asset?.id || asset?.content_url || asset?.display_name || "";
}

function scheduleArtifactTextPreview(asset, documentPreviewType) {
  if (!asset?.content_url || !["markdown", "text"].includes(documentPreviewType)) {
    return;
  }
  const cacheKey = assetPreviewCacheKey(asset);
  if (!cacheKey) {
    return;
  }
  const cached = state.assetTextPreviews.get(cacheKey);
  if (cached?.status === "loading" || cached?.status === "ready") {
    return;
  }
  state.assetTextPreviews.set(cacheKey, { status: "loading", text: "" });
  fetch(asset.content_url, { headers: { Accept: "text/plain,*/*" } })
    .then((response) => {
      if (!response.ok) {
        throw new Error(`Preview request failed with ${response.status}`);
      }
      return response.text();
    })
    .then((text) => {
      const previewLimit = 12000;
      state.assetTextPreviews.set(cacheKey, {
        status: "ready",
        text: text.slice(0, previewLimit),
        truncated: text.length > previewLimit,
      });
      renderArtifactPanel();
    })
    .catch(() => {
      state.assetTextPreviews.set(cacheKey, { status: "error", text: "" });
      renderArtifactPanel();
    });
}

function artifactTextPreviewMarkup(asset, documentPreviewType, previewLabel) {
  const cacheKey = assetPreviewCacheKey(asset);
  const cached = cacheKey ? state.assetTextPreviews.get(cacheKey) : null;
  scheduleArtifactTextPreview(asset, documentPreviewType);

  if (cached?.status === "ready") {
    const text = String(cached.text || "").trim();
    const bodyMarkup = text
      ? documentPreviewType === "markdown"
        ? renderMarkdownBlocks(text)
        : `<pre class="artifact-document-text-pre">${escapeHtml(text)}</pre>`
      : `<p>No readable text was found in this file.</p>`;
    return `
      <div class="artifact-document-preview is-${escapeHtml(documentPreviewType)} is-inline">
        <article class="artifact-document-paper">
          <div class="artifact-document-paper-topline">
            <span>${escapeHtml(artifactAssetKindLabel(asset))}</span>
            <span>${escapeHtml(formatBytes(asset.byte_size))}</span>
          </div>
          <section class="artifact-document-body rich-text">
            ${bodyMarkup}
            ${cached.truncated ? `<p class="artifact-document-truncated">Preview truncated for speed. Open the file for the full document.</p>` : ""}
          </section>
        </article>
        <div class="artifact-document-preview-label">${escapeHtml(previewLabel)}</div>
      </div>
    `;
  }

  const statusCopy =
    cached?.status === "error"
      ? "Preview unavailable. Open the file to inspect it locally."
      : "Loading local text preview...";
  return `
    <div class="artifact-document-preview is-${escapeHtml(documentPreviewType)} is-inline is-loading">
      <article class="artifact-document-paper">
        <span class="artifact-document-loader" aria-hidden="true"></span>
        <p>${escapeHtml(statusCopy)}</p>
      </article>
      <div class="artifact-document-preview-label">${escapeHtml(previewLabel)}</div>
    </div>
  `;
}

function artifactFilePreviewMarkup(asset, { hero = false, rail = false } = {}) {
  const href = escapeHtml(asset.content_url || "#");
  const name = escapeHtml(asset.display_name || "Attachment");
  const mediaType = escapeHtml(asset.media_type || asset.kind || "file");
  const size = asset.byte_size ? ` • ${escapeHtml(formatBytes(asset.byte_size))}` : "";
  if (asset.kind === "image" && asset.preview_url) {
    return `<img class="${hero ? "artifact-file-hero-media" : "artifact-file-thumb"}" src="${escapeHtml(asset.preview_url)}" alt="${name}" />`;
  }
  if (asset.kind === "video" && asset.preview_url) {
    return `<video class="${hero ? "artifact-file-hero-media" : "artifact-file-thumb"}" src="${escapeHtml(asset.preview_url)}" controls playsinline preload="metadata"></video>`;
  }
  const documentPreviewType = artifactDocumentPreviewType(asset);
  if (hero && documentPreviewType && asset.content_url) {
    const previewLabel =
      documentPreviewType === "pdf"
        ? "Native PDF preview"
        : documentPreviewType === "markdown"
          ? "Native Markdown preview"
          : "Native text preview";
    if (["markdown", "text"].includes(documentPreviewType)) {
      return artifactTextPreviewMarkup(asset, documentPreviewType, previewLabel);
    }
    return `
      <div class="artifact-document-preview is-${escapeHtml(documentPreviewType)}">
        <iframe
          class="artifact-file-document-frame"
          src="${href}"
          title="${name} preview"
          loading="lazy"
          ${documentPreviewType === "pdf" ? "" : "sandbox"}
        ></iframe>
        <div class="artifact-document-preview-label">${escapeHtml(previewLabel)}</div>
      </div>
    `;
  }
  return `
    <div class="${hero ? "artifact-file-hero-placeholder" : "artifact-file-thumb-placeholder"}">
      <span>${escapeHtml(artifactAssetKindLabel(asset).slice(0, 4).toUpperCase())}</span>
      ${asset.content_url && !rail ? `<a href="${href}" target="_blank" rel="noreferrer">Open locally</a>` : ""}
      <small>${mediaType}${size}</small>
    </div>
  `;
}

function renderArtifactFilesSurface({ assets, approval, title }) {
  const selectedIndex = Math.max(
    0,
    assets.findIndex((asset) => asset.id && asset.id === state.artifactSelectedAssetId),
  );
  const selectedAsset = assets[selectedIndex] || assets[0];
  const primary = selectedAsset;
  const fileCount = assets.length;
  if (!primary) {
    return `
      <div class="artifact-preview-scroll artifact-files-scroll" data-artifact-mode-panel="files">
        <section class="artifact-files-empty">
          <span>Files</span>
          <h3>No attached files yet</h3>
          <p>Drop an image, video, PDF, Markdown, or text file into the composer and it will appear here as local workspace context.</p>
        </section>
      </div>
    `;
  }
  return `
    <div class="artifact-preview-scroll artifact-files-scroll" data-artifact-mode-panel="files">
      <section class="artifact-files-workspace">
        <header class="artifact-files-header">
          <div>
            <span>Workspace files</span>
            <h3>${escapeHtml(primary.display_name || title || "Attached file")}</h3>
            <p>${escapeHtml(artifactAssetRouteLabel(primary))} • ${escapeHtml(primary.media_type || primary.kind || "file")}${primary.byte_size ? ` • ${escapeHtml(formatBytes(primary.byte_size))}` : ""}</p>
          </div>
          <div class="artifact-files-header-actions">
            <strong>${selectedIndex + 1}/${fileCount}</strong>
            ${
              fileCount > 1
                ? `
                  <div class="artifact-files-nav" aria-label="File preview navigation">
                    <button data-artifact-file-step="-1" type="button" aria-label="Previous file">← Prev</button>
                    <button data-artifact-file-step="1" type="button" aria-label="Next file">Next →</button>
                  </div>
                `
                : ""
            }
          </div>
        </header>
        <article class="artifact-file-hero">
          ${artifactFilePreviewMarkup(primary, { hero: true })}
          <div class="artifact-file-hero-copy">
            <span>${escapeHtml(artifactAssetKindLabel(primary))}</span>
            <h4>${escapeHtml(primary.display_name || "Attachment")}</h4>
            <p>${escapeHtml(primary.analysis_summary || "Stored locally and ready for grounded review in this conversation.")}</p>
            ${primary.content_url ? `<a class="artifact-open" href="${escapeHtml(primary.content_url)}" target="_blank" rel="noreferrer">↗ Open</a>` : ""}
          </div>
        </article>
        <div class="artifact-file-rail" aria-label="Attached workspace files">
          ${assets
            .map(
              (asset) => `
                <button
                  class="artifact-file-row${asset.id === primary.id ? " is-active" : ""}"
                  data-artifact-asset-id="${escapeHtml(asset.id || "")}"
                  type="button"
                  aria-pressed="${String(asset.id === primary.id)}"
                  aria-label="${escapeHtml(`Preview ${asset.display_name || "attachment"}`)}"
                >
                  ${artifactFilePreviewMarkup(asset, { rail: true })}
                  <div>
                    <strong>${escapeHtml(clip(asset.display_name || "Attachment", 42))}</strong>
                    <span>${escapeHtml(artifactAssetKindLabel(asset))} • ${escapeHtml(artifactAssetRouteLabel(asset))}</span>
                    ${asset.analysis_summary ? `<p>${escapeHtml(clipCopy(asset.analysis_summary, 150))}</p>` : ""}
                  </div>
                </button>
              `,
            )
            .join("")}
        </div>
        ${approval ? `<p class="artifact-files-link-note">Canvas and files are linked in this workspace. Use the tabs above to move between the draft and its supporting attachments.</p>` : ""}
      </section>
    </div>
  `;
}

function isArtifactDrawerLayout() {
  return window.innerWidth <= 1500;
}

function isSidebarDrawerLayout() {
  return window.innerWidth <= 1080;
}

function setMobileArtifactOpen(open, { renderPanel = true } = {}) {
  state.mobileArtifactOpen = Boolean(open);
  if (renderPanel) {
    renderArtifactPanel();
  }
}

function renderArtifactPanel() {
  if (!elements.artifactPanel || !elements.appShell) {
    return;
  }

  const approval = latestArtifactApproval();
  const workspaceAssets = activeWorkspaceAssets();
  const hasArtifact = Boolean(approval?.id || workspaceAssets.length);
  const drawerLayout = isArtifactDrawerLayout();
  if (drawerLayout && state.artifactPanelCollapsed) {
    state.artifactPanelCollapsed = false;
  }
  const panelVisible = hasArtifact && (!state.artifactPanelCollapsed || drawerLayout);
  elements.appShell.classList.toggle("has-artifact", panelVisible);
  elements.appShell.classList.toggle("has-artifact-available", hasArtifact);
  elements.artifactPanel.hidden = !panelVisible;
  if (elements.artifactToggle) {
    elements.artifactToggle.hidden = !hasArtifact;
  }
  if (!hasArtifact) {
    elements.artifactPanel.innerHTML = "";
    elements.artifactPanel.classList.remove("is-mobile-open", "is-actual-size", "is-canvas-mode");
    if (elements.artifactToggle) {
      elements.artifactToggle.classList.remove("is-active");
      elements.artifactToggle.setAttribute("aria-expanded", "false");
    }
    state.artifactMode = "summary";
    state.mobileArtifactOpen = false;
    state.artifactSelectedAssetId = null;
    return;
  }
  if (
    state.artifactSelectedAssetId &&
    !workspaceAssets.some((asset) => asset.id === state.artifactSelectedAssetId)
  ) {
    state.artifactSelectedAssetId = null;
  }

  const payload = approval ? approvalEffectivePayload(approval) : {};
  const requestedMode = state.artifactMode;
  const mode =
    requestedMode === "files" && workspaceAssets.length
      ? "files"
      : requestedMode === "canvas" && approval
        ? "canvas"
        : approval
          ? "summary"
          : "files";
  state.artifactMode = mode;
  const selectedWorkspaceAsset =
    workspaceAssets.find((asset) => asset.id && asset.id === state.artifactSelectedAssetId) ||
    workspaceAssets[0];
  const title = String(
    approval && mode !== "files"
      ? payload?.title || approvalHeadingText(approval, payload) || "Untitled workspace"
      : selectedWorkspaceAsset?.display_name || "Workspace files",
  ).trim();
  const previewContent = approval ? approvalPreviewContent(approval, payload) : "";
  const previewSummary = approval ? approvalPayloadExcerpt(approval, payload) : "";
  const statusLabel = approval ? approvalStatusLabel(approval.status || "pending") : "Attached";
  const kind = approval ? artifactFileKind(approval) : artifactAssetKindLabel(workspaceAssets[0]);
  const edits = approval ? documentEditsForApproval(approval.id) : [];
  const drawerOpen = drawerLayout && state.mobileArtifactOpen;
  const zoomLabel = state.artifactZoomActual ? "Zoom to fit" : "Actual size";
  const zoomTitle = state.artifactZoomActual
    ? "Fit the preview back inside the artifact pane"
    : "Show the artifact preview at actual size";
  const focusTitle = "Focus the inline editor for this draft";
  elements.artifactPanel.classList.toggle("is-actual-size", state.artifactZoomActual);
  elements.artifactPanel.classList.toggle("is-canvas-mode", mode === "canvas");
  elements.artifactPanel.classList.toggle("is-mobile-open", drawerOpen);
  if (elements.artifactToggle) {
    const expanded = drawerLayout ? drawerOpen : panelVisible;
    elements.artifactToggle.classList.toggle("is-active", expanded);
    elements.artifactToggle.setAttribute("aria-expanded", String(expanded));
  }
  const contentMarkup = previewContent
    ? renderMarkdownBlocks(previewContent)
    : previewSummary
      ? `<p>${escapeHtml(previewSummary)}</p>`
      : `<p>This workspace item is ready for review.</p>`;
  const editMarkup = renderArtifactEditLedger(edits);
  const bodyMarkup =
    mode === "files"
      ? renderArtifactFilesSurface({ assets: workspaceAssets, approval, title })
      : mode === "canvas"
        ? renderArtifactCanvasSurface({ approval, payload, title, statusLabel, editMarkup })
        : renderArtifactSummarySurface({ approval, payload, title, kind, statusLabel, contentMarkup, editMarkup, previewContent });

  const tabMarkup = [
    approval
      ? `
        <button class="artifact-summary-tab artifact-mode-tab${mode === "summary" ? " is-active" : ""}" data-artifact-mode="summary" type="button" aria-pressed="${String(mode === "summary")}">
          <svg class="ui-icon" aria-hidden="true" viewBox="0 0 24 24"><path d="M4 7h11M4 12h7M4 17h11M18 9l3 3-3 3"/></svg>
          Summary
        </button>
      `
      : "",
    approval
      ? `
        <button class="artifact-file-tab artifact-mode-tab${mode === "canvas" ? " is-active" : ""}" data-artifact-mode="canvas" type="button" aria-pressed="${String(mode === "canvas")}">
          <span class="artifact-file-badge">${escapeHtml(kind.slice(0, 3).toUpperCase())}</span>
          Canvas
        </button>
      `
      : "",
    workspaceAssets.length
      ? `
        <button class="artifact-file-tab artifact-mode-tab${mode === "files" ? " is-active" : ""}" data-artifact-mode="files" type="button" aria-pressed="${String(mode === "files")}">
          <span class="artifact-file-badge artifact-file-badge-files">${workspaceAssets.length}</span>
          Files
        </button>
      `
      : "",
  ]
    .filter(Boolean)
    .join("");

  elements.artifactPanel.innerHTML = `
    <header class="artifact-header">
      <div class="artifact-tabs" aria-label="Artifact navigation">
        ${tabMarkup}
        <span class="artifact-tab-plus" aria-hidden="true">＋</span>
      </div>
      <div class="artifact-toolbar">
        <strong>${escapeHtml(clip(title, 42))}</strong>
        <span>${mode === "files" ? `${workspaceAssets.length} file${workspaceAssets.length === 1 ? "" : "s"}` : "P1/1"}</span>
        <button class="artifact-zoom" data-artifact-zoom type="button" aria-pressed="${String(state.artifactZoomActual)}" title="${escapeHtml(zoomTitle)}">${escapeHtml(zoomLabel)}⌄</button>
        ${approval ? `<button class="artifact-open" data-artifact-open="${escapeHtml(approval.id)}" type="button" aria-label="${escapeHtml(`Focus editor for ${title}`)}" title="${escapeHtml(focusTitle)}">↗ Focus</button>` : ""}
        <button class="artifact-close" data-artifact-close type="button" aria-label="Close workspace preview">Close</button>
      </div>
    </header>
    ${bodyMarkup}
  `;
  wireArtifactPanelActions(approval);
}

function wireArtifactPanelActions(approval) {
  const zoomButton = elements.artifactPanel.querySelector("[data-artifact-zoom]");
  const closeButton = elements.artifactPanel.querySelector("[data-artifact-close]");
  const openButtons = elements.artifactPanel.querySelectorAll("[data-artifact-open]");
  const modeButtons = elements.artifactPanel.querySelectorAll("[data-artifact-mode]");
  const assetButtons = elements.artifactPanel.querySelectorAll("[data-artifact-asset-id]");
  const fileStepButtons = elements.artifactPanel.querySelectorAll("[data-artifact-file-step]");
  for (const modeButton of modeButtons) {
    modeButton.addEventListener("click", () => {
      const requestedMode = modeButton.dataset.artifactMode;
      state.artifactMode = ["summary", "canvas", "files"].includes(requestedMode) ? requestedMode : "summary";
      renderArtifactPanel();
    });
  }
  for (const assetButton of assetButtons) {
    assetButton.addEventListener("click", () => {
      state.artifactSelectedAssetId = assetButton.dataset.artifactAssetId || null;
      state.artifactMode = "files";
      renderArtifactPanel();
    });
  }
  for (const stepButton of fileStepButtons) {
    stepButton.addEventListener("click", () => {
      const assets = activeWorkspaceAssets();
      if (assets.length < 2) {
        return;
      }
      const currentIndex = Math.max(
        0,
        assets.findIndex((asset) => asset.id && asset.id === state.artifactSelectedAssetId),
      );
      const step = Number(stepButton.dataset.artifactFileStep || 0);
      const nextIndex = (currentIndex + step + assets.length) % assets.length;
      state.artifactSelectedAssetId = assets[nextIndex]?.id || null;
      state.artifactMode = "files";
      renderArtifactPanel();
    });
  }
  if (zoomButton) {
    zoomButton.addEventListener("click", () => {
      state.artifactZoomActual = !state.artifactZoomActual;
      renderArtifactPanel();
    });
  }
  if (closeButton) {
    closeButton.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      if (isArtifactDrawerLayout()) {
        setMobileArtifactOpen(false);
      } else {
        state.artifactPanelCollapsed = true;
        renderArtifactPanel();
      }
    });
  }
  for (const openButton of openButtons) {
    openButton.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      const canvas = document.querySelector(`.approval-canvas-${CSS.escape(approval.tool_name)}`);
      if (isArtifactDrawerLayout()) {
        setMobileArtifactOpen(false);
      }
      if (canvas) {
        canvas.scrollIntoView({ behavior: "smooth", block: "center" });
        canvas.classList.add("is-attention");
        window.setTimeout(() => canvas.classList.remove("is-attention"), 900);
      }
    });
  }
}

function renderApprovalResult(result) {
  if (!result) {
    return "";
  }

  const resultBits = [];
  if (result.entity_type) {
    resultBits.push(`Saved ${escapeHtml(result.entity_type)}`);
  }
  if (result.title) {
    resultBits.push(`<strong>${escapeHtml(result.title)}</strong>`);
  }
  if (result.status) {
    resultBits.push(`${escapeHtml(humanizeRunStatus(result.status))}`);
  }

  if (!resultBits.length) {
    return `<pre class="approval-json">${escapeHtml(JSON.stringify(result, null, 2))}</pre>`;
  }

  const destination =
    result.destination_path
      ? `<div class="approval-result-path">${escapeHtml(result.destination_path)}</div>`
      : "";
  return `<div class="approval-result">${resultBits.join(" · ")}</div>${destination}`;
}

function humanizeRunStatus(status) {
  return String(status || "running")
    .split("_")
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function runStepProgress(run) {
  const plannedCount = run.plan_steps?.length || run.executed_steps?.length || 0;
  const executedCount = run.executed_steps?.length || 0;
  return `${executedCount}/${plannedCount || executedCount || 0} steps`;
}

function toolDraftLabel(toolName) {
  switch (toolName) {
    case "create_note":
      return "a note draft";
    case "create_report":
      return "a report draft";
    case "create_message_draft":
      return "a message draft";
    case "create_checklist":
      return "a checklist draft";
    case "create_task":
      return "a task draft";
    case "export_brief":
      return "a markdown export";
    case "log_observation":
      return "an observation draft";
    default:
      return "a local draft";
  }
}

function sanitizeRunSummary(summary, approval = null) {
  if (!summary) {
    return "";
  }

  const trimmed = String(summary).trim();
  if (!trimmed) {
    return "";
  }

  if (approval?.status === "pending") {
    return `Reviewed local material and prepared ${toolDraftLabel(approval.tool_name)}.`;
  }

  const replaced = trimmed
    .replace(/`create_note`/g, "a note draft")
    .replace(/`create_report`/g, "a report draft")
    .replace(/`create_message_draft`/g, "a message draft")
    .replace(/`create_checklist`/g, "a checklist draft")
    .replace(/`create_task`/g, "a task draft")
    .replace(/`export_brief`/g, "a markdown export")
    .replace(/`log_observation`/g, "an observation draft")
    .replace(/\/Users\/[^\s`]+/g, "this workspace")
    .replace(/workspace findings/gi, "local material");

  if (/workspace run completed without strong matching files/i.test(replaced)) {
    return "I did not find strong matching local files for that request.";
  }

  return replaced;
}

function runPrimarySummary(run, approval) {
  const summary = sanitizeRunSummary(run?.result_summary, approval);
  if (summary) {
    return summary;
  }
  if (approval?.status === "pending") {
    return `Reviewed local material and prepared ${toolDraftLabel(approval.tool_name)}.`;
  }
  if (run?.status === "completed") {
    return "Finished the local workspace review.";
  }
  if (run?.status === "failed" || run?.status === "blocked") {
    return "The local workspace review did not complete cleanly.";
  }
  return "Reviewing relevant local workspace material.";
}

function runFactBits(run, approval) {
  const bits = [];
  if (run.artifact_ids?.length) {
    bits.push(`${run.artifact_ids.length} artifact${run.artifact_ids.length === 1 ? "" : "s"}`);
  }
  return bits;
}

function presentRunStatus(status, approval) {
  if (approval?.status === "pending") {
    return "Needs approval";
  }
  switch (status) {
    case "completed":
      return "Done";
    case "failed":
      return "Issue";
    case "blocked":
      return "Blocked";
    case "awaiting_approval":
      return "Needs approval";
    default:
      return "Working locally";
  }
}

function presentRunStepTitle(step) {
  const title = String(step?.title || step?.kind || "Step");
  const normalized = title.toLowerCase();
  if (normalized.includes("inspect workspace")) {
    return "Checked the workspace";
  }
  if (normalized.includes("search workspace")) {
    return "Looked for relevant files";
  }
  if (normalized.includes("read candidate")) {
    return "Read matching documents";
  }
  if (normalized.includes("synthesize")) {
    return "Prepared a working summary";
  }
  if (normalized.includes("prepare durable")) {
    return "Prepared a draft for approval";
  }
  return title;
}

function renderAgentRunMarkup(run, approval) {
  if (!run) {
    return "";
  }

  const allSteps = run.executed_steps?.length ? run.executed_steps : run.plan_steps || [];
  const expanded = isRunExpanded(run);
  const steps = allSteps.slice(-8);
  const primarySummary = runPrimarySummary(run, approval);
  const stepMarkup = allSteps.length
    ? `
      <div class="agent-run-steps"${expanded ? "" : ' hidden'}>
        ${steps
          .map(
            (step) => `
              <div class="agent-run-step is-${escapeHtml(step.status || "planned")}">
                <div class="agent-run-step-header">
                  <strong>${escapeHtml(presentRunStepTitle(step))}</strong>
                  <span>${escapeHtml(humanizeRunStatus(step.status || "planned"))}</span>
                </div>
                ${
                  step.status === "failed" || step.status === "blocked"
                    ? step.detail
                      ? `<p>${escapeHtml(step.detail)}</p>`
                      : ""
                    : ""
                }
              </div>
            `,
          )
          .join("")}
      </div>
    `
    : "";

  const factBits = runFactBits(run, approval).join(" • ");
  const toggleMarkup = allSteps.length
    ? `<button class="agent-run-toggle" data-run-toggle="${run.id}" type="button">${expanded ? "Hide details" : "Details"}</button>`
    : "";

  return `
    <section class="agent-run-card is-${escapeHtml(run.status || "running")}">
      <div class="agent-run-header">
        <div class="agent-run-main">
          <span class="agent-run-kicker">Working locally</span>
          <h4>${escapeHtml(primarySummary)}</h4>
          ${factBits ? `<p class="agent-run-facts">${escapeHtml(factBits)}</p>` : ""}
        </div>
        <div class="agent-run-inline-actions">
          <span class="agent-run-status">${escapeHtml(presentRunStatus(run.status || "running", approval))}</span>
          ${toggleMarkup}
        </div>
      </div>
      ${stepMarkup}
    </section>
  `;
}

function renderConversations() {
  elements.conversationList.innerHTML = "";

  if (!state.conversations.length) {
    const empty = document.createElement("p");
    empty.className = "section-label";
    empty.textContent = "No saved sessions yet";
    elements.conversationList.append(empty);
    return;
  }

  for (const conversation of state.conversations) {
    const shell = document.createElement("div");
    shell.className = "conversation-row-shell";
    if (conversation.id === state.activeConversationId) {
      shell.classList.add("is-active");
    }

    const button = document.createElement("button");
    button.type = "button";
    button.className = "conversation-row";
    if (conversation.id === state.activeConversationId) {
      button.classList.add("is-active");
    }

    const age = formatRelativeAgeCompact(conversation.last_activity_at || conversation.created_at);
    const preview = conversationPreviewText(conversation);

    button.innerHTML = `
      <div class="conversation-row-main">
        <strong>${escapeHtml(clip(conversationLabel(conversation), 34))}</strong>
        <span class="conversation-age">${escapeHtml(age)}</span>
      </div>
      <span class="conversation-preview">${escapeHtml(preview)}</span>
    `;

    button.addEventListener("click", () => {
      openConversation(conversation.id);
      closeSidebar();
    });

    const deleteButton = document.createElement("button");
    deleteButton.type = "button";
    deleteButton.className = "conversation-row-delete";
    deleteButton.setAttribute("aria-label", `Delete ${conversationLabel(conversation)}`);
    deleteButton.innerHTML = "&times;";
    deleteButton.addEventListener("click", async (event) => {
      event.stopPropagation();
      await deleteConversation(conversation.id);
    });

    shell.append(button, deleteButton);
    elements.conversationList.append(shell);
  }
}

function renderAttachmentStrip() {
  elements.attachmentStrip.innerHTML = "";

  for (const attachment of state.pendingAttachments) {
    const card = document.createElement("section");
    const uploadState = attachment.uploadState || "queued";
    const progress = attachmentProgressValue(attachment);
    card.className = `attachment-draft is-${uploadState}`;
    const previewMarkup =
      attachment.kind === "image" && attachment.previewUrl
        ? `<img src="${escapeHtml(attachment.previewUrl)}" alt="${escapeHtml(attachment.displayName)}" />`
        : attachment.kind === "video" && attachment.previewUrl
          ? `<video src="${escapeHtml(attachment.previewUrl)}" muted playsinline preload="metadata"></video>`
          : "";
    const footerMarkup =
      attachment.kind === "image"
        ? `
          <label>
            Care context
            <select data-attachment-context="${attachment.localId}">
              <option value="general"${attachment.careContext === "general" ? " selected" : ""}>General image</option>
              <option value="medical"${attachment.careContext === "medical" ? " selected" : ""}>Medical image</option>
            </select>
          </label>
          <span class="attachment-draft-status">${escapeHtml(attachmentRouteCopy(attachment))}</span>
        `
        : `<span class="attachment-draft-status">${escapeHtml(attachmentRouteCopy(attachment))}</span>`;
    card.innerHTML = `
      ${previewMarkup}
      <div class="attachment-draft-header">
        <div>
          <strong>${escapeHtml(clip(attachment.displayName, 30))}</strong>
          <span>${escapeHtml(attachment.mediaType || attachment.kind)}${attachment.file.size ? ` • ${escapeHtml(formatBytes(attachment.file.size))}` : ""}</span>
        </div>
        <button class="attachment-remove" type="button" data-remove-attachment="${attachment.localId}" aria-label="Remove attachment">×</button>
      </div>
      <div class="attachment-draft-footer">
        ${footerMarkup}
      </div>
      <div class="attachment-progress" aria-label="${escapeHtml(attachmentStatusCopy(attachment))}">
        <span style="width: ${Math.round(progress * 100)}%"></span>
      </div>
      <p class="attachment-status-copy">${escapeHtml(attachmentStatusCopy(attachment))}${attachment.uploadError ? ` · ${escapeHtml(attachment.uploadError)}` : ""}</p>
    `;
    elements.attachmentStrip.append(card);
  }

  for (const removeButton of elements.attachmentStrip.querySelectorAll("[data-remove-attachment]")) {
    removeButton.addEventListener("click", () => {
      removePendingAttachment(removeButton.dataset.removeAttachment);
    });
  }

  for (const select of elements.attachmentStrip.querySelectorAll("[data-attachment-context]")) {
    select.addEventListener("change", (event) => {
      const localId = event.target.dataset.attachmentContext;
      const attachment = state.pendingAttachments.find((entry) => entry.localId === localId);
      if (!attachment) {
        return;
      }
      attachment.careContext = event.target.value;
      render();
    });
  }
}

function renderAssetMarkup(assets) {
  if (!assets?.length) {
    return "";
  }

  const cards = assets
    .map((asset) => {
      const href = escapeHtml(asset.content_url || "#");
      const preview = asset.preview_url
        ? asset.kind === "image"
          ? `<img src="${escapeHtml(asset.preview_url)}" alt="${escapeHtml(asset.display_name)}" />`
          : asset.kind === "video"
            ? `<video src="${escapeHtml(asset.preview_url)}" controls playsinline preload="metadata"></video>`
            : ""
        : "";
      const kindClass =
        asset.kind === "image" ? "image" : asset.kind === "video" ? "video" : "file";
      const metaBits = [asset.kind];
      if (asset.media_type) {
        metaBits.push(asset.media_type);
      }
      if (asset.care_context === "medical") {
        metaBits.push("medical");
      }
      const body = `
        ${preview}
        <div>
          <strong>${escapeHtml(clip(asset.display_name, 32))}</strong>
          <span>${escapeHtml(metaBits.join(" • "))}</span>
          ${asset.analysis_summary ? `<span>${escapeHtml(asset.analysis_summary)}</span>` : ""}
        </div>
      `;
      if (asset.kind === "image") {
        return `
          <a class="asset-card ${kindClass}" href="${href}" target="_blank" rel="noreferrer">
            ${body}
          </a>
        `;
      }
      return `
        <article class="asset-card ${kindClass}">
          ${body}
          ${asset.content_url ? `<a class="asset-open-link" href="${href}" target="_blank" rel="noreferrer">Open locally</a>` : ""}
        </article>
      `;
    })
    .join("");

  return `<div class="asset-gallery">${cards}</div>`;
}

function renderToolResultMarkup(result) {
  if (!result || !result.message) {
    return "";
  }

  const title = result.title ? `<strong>${escapeHtml(result.title)}</strong>` : "";
  return `
    <section class="tool-result-card">
      <span class="tool-result-kicker">Generated locally</span>
      ${title}
      <p>${escapeHtml(result.message)}</p>
    </section>
  `;
}

function renderMessages({ preserveScroll = false } = {}) {
  const messages = activeMessages();
  const previousScrollTop = elements.messageScroll.scrollTop;
  elements.messageList.innerHTML = "";
  elements.emptyState.classList.toggle("is-hidden", messages.length > 0);

  for (const message of messages) {
    if (shouldSuppressMessage(message)) {
      continue;
    }
    const visibleContent = messageDisplayContent(message);
    const activeWorkProduct = message.workProduct || message.approval;
    const row = document.createElement("article");
    row.className = [
      "message-row",
      message.role,
      message.loading ? "is-loading" : "",
      message.agentRun ? "has-agent-run" : "",
      activeWorkProduct ? "has-approval" : "",
    ]
      .filter(Boolean)
      .join(" ");

    const citations = (message.citations || [])
      .map(
        (citation) =>
          `<span class="citation-chip" title="${escapeHtml(citation.excerpt || "")}">${escapeHtml(citation.label)}</span>`,
      )
      .join("");

    const toolChip = message.proposedTool && !activeWorkProduct
      ? `<span class="tool-chip">Prepared ${escapeHtml(message.proposedTool)}</span>`
      : "";

    const approvalCard = renderApprovalMarkup(activeWorkProduct);
    const assetGallery = renderAssetMarkup(message.assets || []);
    const toolResultCard = renderToolResultMarkup(message.toolResult);
    const agentRunCard = renderAgentRunMarkup(message.agentRun, activeWorkProduct);
    const loadingShell = renderAssistantLoadingMarkup(message, visibleContent);
    const contentMarkup = renderMessageContent(message, visibleContent);

    row.innerHTML = `
      <div class="message-card">
        <div class="message-meta">
          <span>${formatRole(message.role)}</span>
        </div>
        ${agentRunCard}
        ${loadingShell}
        ${contentMarkup}
        ${toolResultCard}
        ${assetGallery}
        ${toolChip ? `<div class="citation-list">${toolChip}</div>` : ""}
        ${citations ? `<div class="citation-list">${citations}</div>` : ""}
        ${approvalCard}
      </div>
    `;

    elements.messageList.append(row);

    wireMessageCardActions(row, message);
    if (activeWorkProduct) {
      wireApprovalActions(row, activeWorkProduct);
    }
    if (message.agentRun) {
      wireRunCardActions(row, message.agentRun);
    }
  }

  queueMicrotask(() => {
    if (preserveScroll) {
      elements.messageScroll.scrollTop = previousScrollTop;
      return;
    }
    elements.messageScroll.scrollTop = messages.length ? elements.messageScroll.scrollHeight : 0;
  });
}

function renderApprovalPreviewSlot(approval) {
  return `<div data-approval-preview-slot>${renderApprovalPreview(approval)}</div>`;
}

function renderApprovalMarkup(approval) {
  if (!approval) {
    return "";
  }

  if (approvalUsesInlineCanvas(approval)) {
    return renderApprovalCanvas(approval);
  }

  const payload = approvalEffectivePayload(approval);
  const editorExpanded = approval.status === "pending" ? isApprovalSectionExpanded(approval, "editor") : false;
  const editToggle =
    approval.status === "pending"
      ? `
        <button
          class="approval-action edit"
          data-approval-section-toggle="editor"
          data-approval-id="${approval.id}"
          type="button"
        >
          ${editorExpanded ? "Close editor" : "Edit"}
        </button>
      `
      : "";

  const actions =
    approval.status === "pending"
      ? `
        <div class="approval-actions">
          ${editToggle}
          <button class="approval-action reject" data-approval-action="reject" data-approval-id="${approval.id}" type="button">Dismiss</button>
          <button class="approval-action approve" data-approval-action="approve" data-approval-id="${approval.id}" type="button">${escapeHtml(approvalPrimaryActionLabel(approval))}</button>
        </div>
      `
      : "";

  return `
    <section class="approval-card is-${escapeHtml(approval.status)}">
      <div class="approval-header approval-header-inline">
        <div class="approval-header-main">
          <div class="approval-heading-line">
            <span class="approval-kicker">${escapeHtml(approvalStatusKicker(approval.status))}</span>
            <h4>${escapeHtml(approvalHeadingText(approval, payload))}</h4>
          </div>
          <p class="approval-summary">${escapeHtml(approvalReasonCopy(approval))}</p>
        </div>
        ${
          approval.status === "pending"
            ? ""
            : `<div class="approval-toolbar"><div class="approval-status is-${escapeHtml(approval.status)}" data-approval-status>${escapeHtml(approvalStatusLabel(approval.status))}</div></div>`
        }
      </div>
      <div class="approval-section approval-section-preview">
        ${renderApprovalPreviewSlot(approval)}
      </div>
      ${
        approval.status === "pending"
          ? `
        <div class="approval-section approval-section-editor"${editorExpanded ? "" : " hidden"}>
          ${renderApprovalEditor(approval)}
        </div>
      `
          : ""
      }
      ${actions}
      ${renderApprovalResult(approval.result)}
    </section>
  `;
}

function collectApprovalEdit(container, approval, { silent = false } = {}) {
  const editor = container.querySelector(`[data-approval-editor="${approval.id}"]`);
  if (!editor) {
    return {};
  }

  const jsonField = editor.querySelector("[data-approval-json]");
  if (jsonField) {
    try {
      const parsed = JSON.parse(jsonField.value);
      if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
        return parsed;
      }
      if (!silent) {
        addSystemMessage("Approval edit must be a JSON object.");
      }
      return null;
    } catch (error) {
      if (!silent) {
        addSystemMessage("Approval edit is not valid JSON yet.");
      }
      return null;
    }
  }

  const editedPayload = {};
  for (const field of container.querySelectorAll("[data-approval-field]")) {
    const name = field.dataset.approvalField;
    if (!name) {
      continue;
    }
    editedPayload[name] = field.value;
  }
  if (Object.prototype.hasOwnProperty.call(editedPayload, "content")) {
    const basePayload = approvalEffectivePayload(approval);
    const effectiveTitle =
      editedPayload.title !== undefined ? editedPayload.title : basePayload.title || approval.payload?.title || "";
    editedPayload.content = approvalComposeCanvasContent(
      approval,
      basePayload,
      effectiveTitle,
      editedPayload.content,
    );
  }
  return editedPayload;
}

function refreshApprovalCardState(container, approval, collected = undefined) {
  const currentEdit = collected === undefined ? collectApprovalEdit(container, approval, { silent: true }) : collected;
  const previewSlot = container.querySelector("[data-approval-preview-slot]");
  const stateLabel = container.querySelector("[data-approval-draft-state]");
  const resetButton = container.querySelector("[data-approval-reset]");
  const approveButton = container.querySelector('[data-approval-action="approve"]');
  const errorLabel = container.querySelector("[data-approval-error]");
  const editor = container.querySelector(`[data-approval-editor="${approval.id}"]`);
  if (!editor) {
    return;
  }

  if (errorLabel) {
    const errorMessage = approvalErrorFor(approval.id);
    errorLabel.textContent = errorMessage;
    errorLabel.hidden = !errorMessage;
  }

  if (currentEdit === null) {
    editor.classList.add("has-invalid-draft");
    if (stateLabel) {
      stateLabel.textContent = approvalStateLabelText(approval, { invalid: true });
      stateLabel.classList.add("is-invalid");
      stateLabel.classList.remove("is-dirty");
    }
    if (approveButton) {
      approveButton.disabled = true;
    }
    return;
  }

  editor.classList.remove("has-invalid-draft");
  const dirty = approvalHasDraftChanges(approval, currentEdit);
  if (dirty) {
    saveApprovalDraft(approval.id, currentEdit);
    setApprovalSectionExpanded(approval.id, "editor", true);
  } else {
    clearApprovalDraft(approval.id);
  }

  if (previewSlot) {
    previewSlot.innerHTML = renderApprovalPreview(approval, currentEdit);
  }
  if (stateLabel) {
    stateLabel.textContent = approvalStateLabelText(approval, { dirty });
    stateLabel.classList.toggle("is-dirty", dirty);
    stateLabel.classList.remove("is-invalid");
  }
  if (resetButton) {
    resetButton.disabled = !dirty;
  }
  if (approveButton) {
    approveButton.disabled = false;
  }
  renderArtifactPanel();
}

function resizeApprovalTextareas(container) {
  for (const textarea of container.querySelectorAll(".approval-editor textarea")) {
    const inCanvas = Boolean(textarea.closest(".approval-editor-canvas"));
    const minHeight = textarea.dataset.approvalJson !== undefined ? 132 : inCanvas ? 320 : 96;
    const maxHeight = textarea.dataset.approvalJson !== undefined ? 320 : inCanvas ? (window.innerWidth <= 640 ? 520 : 760) : window.innerWidth <= 640 ? 220 : 280;
    textarea.style.height = "auto";
    const nextHeight = Math.min(Math.max(textarea.scrollHeight, minHeight), maxHeight);
    textarea.style.height = `${nextHeight}px`;
    textarea.classList.toggle("is-overflowing", textarea.scrollHeight > maxHeight + 4);
  }
}

function wireApprovalActions(container, approval) {
  const editor = container.querySelector(`[data-approval-editor="${approval.id}"]`);
  if (editor) {
    for (const field of container.querySelectorAll("[data-approval-field], [data-approval-json]")) {
      if (field.dataset.approvalField === "content") {
        field.addEventListener("select", () => rememberCanvasSelection(container, field, approval));
        field.addEventListener("mouseup", () => rememberCanvasSelection(container, field, approval));
        field.addEventListener("keyup", () => rememberCanvasSelection(container, field, approval));
      }
      field.addEventListener("input", () => {
        if (state.approvalErrors.has(approval.id)) {
          state.approvalErrors.delete(approval.id);
        }
        if (field.dataset.approvalField === "content") {
          rememberCanvasSelection(container, field, approval);
        }
        refreshApprovalCardState(container, approval);
        resizeApprovalTextareas(container);
      });
    }
    resizeApprovalTextareas(container);
    refreshApprovalCardState(container, approval);
  }

  const resetButton = container.querySelector("[data-approval-reset]");
  if (resetButton) {
    resetButton.addEventListener("click", () => {
      state.approvalErrors.delete(approval.id);
      clearApprovalDraft(approval.id);
      render();
    });
  }

  for (const canvasToggle of container.querySelectorAll("[data-approval-canvas-collapse]")) {
    canvasToggle.addEventListener("click", () => {
      setApprovalCanvasCollapsed(approval.id, !isApprovalCanvasCollapsed(approval));
      render({ preserveScroll: true });
    });
  }

  for (const toggle of container.querySelectorAll("[data-approval-section-toggle]")) {
    toggle.addEventListener("click", () => {
      const section = toggle.dataset.approvalSectionToggle;
      if (!section) {
        return;
      }
      setApprovalSectionExpanded(approval.id, section, !isApprovalSectionExpanded(approval, section));
      render({ preserveScroll: true });
    });
  }

  const buttons = container.querySelectorAll("[data-approval-action]");
  for (const button of buttons) {
    button.addEventListener("click", async () => {
      const action = button.dataset.approvalAction;
      let editedPayload = {};
      if (action === "approve") {
        const collected = collectApprovalEdit(container, approval);
        if (collected === null) {
          return;
        }
        editedPayload = collected;
      }
      await submitApprovalDecision(approval.id, action, editedPayload);
    });
  }
}

function wireRunCardActions(container, run) {
  const toggle = container.querySelector(`[data-run-toggle="${run.id}"]`);
  if (!toggle) {
    return;
  }
  toggle.addEventListener("click", () => {
    setRunExpanded(run.id, !isRunExpanded(run));
    render({ preserveScroll: true });
  });
}

function wireMessageCardActions(container, message) {
  const toggle = container.querySelector("[data-message-content-toggle]");
  if (!toggle) {
    return;
  }
  toggle.addEventListener("click", () => {
    const nextExpanded = !isMessagePanelExpanded(message, "context");
    setMessagePanelExpanded(message, "context", nextExpanded);
    render({ preserveScroll: true });
  });
}

function renderCameraSheet() {
  const { camera } = state;
  const isRecording = camera.recorder?.state === "recording";
  const hasClip = Boolean(camera.recordedFile);
  const hasLivePreview = Boolean(camera.stream);
  const isWatching = camera.watchActive;

  elements.cameraSheet.hidden = !camera.open;
  if (!camera.open) {
    elements.cameraPreview.pause();
    elements.cameraPreview.removeAttribute("controls");
    elements.cameraPreview.srcObject = null;
    elements.cameraPreview.removeAttribute("src");
    elements.cameraPreview.load();
    elements.cameraMonitorStrip.innerHTML = "";
    return;
  }

  elements.cameraStatusPill.textContent =
    camera.status === "recording"
      ? "Recording"
      : camera.status === "watching"
        ? "Watching"
      : camera.status === "ready"
        ? "Ready"
        : camera.status === "captured"
          ? "Clip ready"
          : camera.status === "error"
            ? "Unavailable"
            : "Opening";
  elements.cameraStatusCopy.textContent =
    (camera.status === "error"
      ? camera.error || "Camera access is unavailable. Use device capture or try live again."
      : camera.status === "captured"
        ? "Attach this clip to your next turn, or retake it."
      : camera.status === "watching"
        ? `Sampling locally every ${camera.cadenceSeconds}s. Tap a saved frame to attach it.`
      : camera.status === "recording"
        ? "Recording stays local until you attach the clip."
      : camera.status === "ready"
        ? "Capture a frame, analyze what is visible, or record a short clip."
        : "Requesting camera permission. You can still use device capture.");

  elements.cameraModeLabel.textContent = hasClip ? "Clip" : "Live";
  elements.cameraCadenceLabel.textContent = isWatching
    ? `${camera.cadenceSeconds}s`
    : "Manual";
  elements.cameraOutputLabel.textContent = hasClip
    ? "Clip ready"
    : camera.status === "error"
      ? "Use device capture"
    : isWatching
      ? "Watch frames"
      : "Frame or clip";

  elements.cameraSheet.classList.toggle("is-recording", isRecording);
  elements.cameraSheet.classList.toggle("is-watching", isWatching);
  elements.cameraSheet.classList.toggle("is-ready", hasLivePreview && !isRecording && !hasClip);
  elements.cameraSheet.classList.toggle("is-captured", hasClip);
  elements.cameraSheet.classList.toggle("is-error", camera.status === "error");
  elements.cameraLiveButton.textContent = camera.status === "error" ? "Try live" : "Open live";
  elements.cameraWatchButton.textContent = isWatching ? "Stop watch" : "Start watch";
  elements.cameraNativeButton.textContent = "Use device capture";
  const showLiveControls = hasLivePreview && !hasClip && !isRecording;
  const showRecoveryControls = !hasLivePreview && !hasClip && !isRecording;

  elements.cameraLiveButton.hidden = hasClip || isRecording || hasLivePreview;
  elements.cameraWatchButton.hidden = !showLiveControls;
  elements.cameraRecordButton.hidden = !showLiveControls;
  elements.cameraStopButton.hidden = !isRecording;
  elements.cameraRetakeButton.hidden = !hasClip;
  elements.cameraUseButton.hidden = !hasClip;
  elements.cameraNativeButton.hidden = isRecording || hasClip === true || hasLivePreview;
  elements.cameraSnapshotButton.hidden = !showLiveControls;
  elements.cameraAnalyzeButton.hidden = !showLiveControls;
  elements.cameraLiveButton.disabled = false;
  elements.cameraWatchButton.disabled = !hasLivePreview || Boolean(camera.error);
  elements.cameraSnapshotButton.disabled = !hasLivePreview || Boolean(camera.error);
  elements.cameraAnalyzeButton.disabled = !hasLivePreview || Boolean(camera.error) || state.streaming;
  elements.cameraRecordButton.disabled = !hasLivePreview || Boolean(camera.error);
  elements.cameraUseButton.disabled = !hasClip;
  if (showRecoveryControls) {
    elements.cameraLiveButton.hidden = false;
    elements.cameraNativeButton.hidden = false;
  }

  if (camera.recordedUrl) {
    if (elements.cameraPreview.src !== camera.recordedUrl) {
      elements.cameraPreview.srcObject = null;
      elements.cameraPreview.src = camera.recordedUrl;
      elements.cameraPreview.controls = true;
      elements.cameraPreview.loop = true;
      elements.cameraPreview.play().catch(() => {});
    }
  } else if (camera.stream) {
    if (elements.cameraPreview.srcObject !== camera.stream) {
      elements.cameraPreview.src = "";
      elements.cameraPreview.controls = false;
      elements.cameraPreview.srcObject = camera.stream;
      elements.cameraPreview.play().catch(() => {});
    }
  }

  elements.cameraMonitorStrip.innerHTML = "";
  if (camera.monitorFrames.length) {
    elements.cameraMonitorStrip.innerHTML = camera.monitorFrames
      .map(
        (frame) => `
          <button class="camera-monitor-card" type="button" data-camera-frame="${frame.id}">
            <img src="${escapeHtml(frame.previewUrl)}" alt="Captured monitor frame" />
            <span>${escapeHtml(formatRelativeTime(frame.capturedAt))}</span>
          </button>
        `,
      )
      .join("");
    for (const button of elements.cameraMonitorStrip.querySelectorAll("[data-camera-frame]")) {
      button.addEventListener("click", () => {
        const frame = state.camera.monitorFrames.find(
          (entry) => entry.id === button.dataset.cameraFrame,
        );
        if (!frame) {
          return;
        }
        addPendingAttachments([frame.file]);
        resizeComposer();
      });
    }
  }
}

function render(options = {}) {
  const activeConversation = state.conversations.find(
    (conversation) => conversation.id === state.activeConversationId,
  );
  elements.composer.classList.toggle("is-dragging", state.dragActive);
  if (elements.composerModelPill) {
    elements.composerModelPill.textContent = capabilityPillCopy(state.capabilities);
  }
  elements.conversationTitle.textContent = activeConversation
    ? clip(conversationLabel(activeConversation), 44)
    : "New conversation";

  renderConversations();
  renderAttachmentStrip();
  renderMessages(options);
  renderArtifactPanel();
  renderCameraSheet();
  renderStatusMenu();
  elements.sendButton.disabled =
    state.streaming ||
    (!elements.promptInput.value.trim() && state.pendingAttachments.length === 0);
}

async function requestJson(path, init = {}) {
  const response = await fetch(path, {
    headers: {
      "Content-Type": "application/json",
      ...(init.headers || {}),
    },
    ...init,
  });

  if (!response.ok) {
    const text = await response.text();
    let message = text || `Request failed: ${response.status}`;
    if (text) {
      try {
        const parsed = JSON.parse(text);
        if (typeof parsed?.detail === "string" && parsed.detail.trim()) {
          message = parsed.detail.trim();
        }
      } catch (error) {
        // Keep the raw response body when parsing fails.
      }
    }
    throw new Error(message);
  }

  if (response.status === 204) {
    return null;
  }

  const text = await response.text();
  return text ? JSON.parse(text) : null;
}

async function refreshConversations() {
  state.conversations = await requestJson("/v1/conversations");
  render();
}

async function loadCapabilities() {
  try {
    state.capabilities = await requestJson("/v1/system/capabilities");
    if (!state.capabilities.ffmpeg_available || !state.capabilities.tesseract_available) {
      addSystemMessage(
        `Capability check: ${capabilitySummary(state.capabilities)}. Some local media features may degrade gracefully.`,
      );
    }
  } catch (error) {
    state.capabilities = null;
  }
}

async function refreshAgentRuns(conversationId) {
  if (!conversationId) {
    return [];
  }
  const runs = await requestJson(`/v1/conversations/${conversationId}/runs`);
  state.agentRuns.set(conversationId, runs);
  hydrateAgentRunsIntoMessages(conversationId);
  render();
  return runs;
}

async function refreshConversationState(conversationId) {
  if (!conversationId) {
    return null;
  }
  const snapshot = await requestJson(`/v1/conversations/${conversationId}/state`);
  applyConversationState(conversationId, snapshot);
  render();
  return snapshot;
}

function scheduleConversationStateRefresh(conversationId, delay = 80) {
  if (!conversationId) {
    return;
  }
  const existing = scheduledConversationRefreshes.get(conversationId);
  if (existing) {
    return;
  }
  const timer = window.setTimeout(async () => {
    scheduledConversationRefreshes.delete(conversationId);
    if (inflightConversationRefreshes.has(conversationId)) {
      scheduleConversationStateRefresh(conversationId, delay);
      return;
    }
    inflightConversationRefreshes.add(conversationId);
    try {
      await refreshConversationState(conversationId);
    } catch (error) {
      // Ignore transient live-refresh failures and let the next full reload recover.
    } finally {
      inflightConversationRefreshes.delete(conversationId);
    }
  }, delay);
  scheduledConversationRefreshes.set(conversationId, timer);
}

async function openConversation(conversationId) {
  state.activeConversationId = conversationId;
  persistActiveConversation();
  await refreshConversationState(conversationId);
  pruneResolvedApprovalDrafts(state.transcripts.get(conversationId));
  render();
}

async function deleteConversation(conversationId) {
  const conversation = state.conversations.find((entry) => entry.id === conversationId);
  const label = conversationLabel(conversation || { title: "this conversation" });
  const confirmed = window.confirm(`Delete "${label}"? This removes the local transcript and run history.`);
  if (!confirmed) {
    return;
  }

  try {
    await requestJson(`/v1/conversations/${conversationId}`, { method: "DELETE" });
  } catch (error) {
    addSystemMessage(error.message || "Unable to delete that conversation.");
    return;
  }

  purgeConversationUiState(conversationId);
  state.conversations = state.conversations.filter((entry) => entry.id !== conversationId);

  if (state.activeConversationId === conversationId) {
    state.activeConversationId = state.conversations[0]?.id || null;
    persistActiveConversation();
    if (state.activeConversationId) {
      await openConversation(state.activeConversationId);
      return;
    }
  }

  render();
}

async function createConversation(title) {
  const conversation = await requestJson("/v1/conversations", {
    method: "POST",
    body: JSON.stringify({
      title,
      mode: state.currentMode,
    }),
  });
  state.activeConversationId = conversation.id;
  persistActiveConversation();
  state.conversations = [conversation, ...state.conversations];
  state.transcripts.set(conversation.id, []);
  state.agentRuns.set(conversation.id, []);
  render();
  return conversation;
}

function appendLocalMessage(message) {
  const messages = [...activeMessages(), message];
  setActiveMessages(messages);
  render();
}

function ensureAssistantMessage(turnId) {
  const messages = [...activeMessages()];
  let message = messages.find((entry) => entry.turnId === turnId && entry.role === "assistant");
  if (!message) {
    message = {
      id: `assistant-${turnId}`,
      role: "assistant",
      turnId,
      content: "",
      assets: [],
      citations: [],
      approval: null,
      workProduct: null,
      proposedTool: null,
      process: [],
      toolResult: null,
      loading: Boolean(state.streaming),
    };
    messages.push(message);
    setActiveMessages(messages);
  }
  return message;
}

function addSystemMessage(content) {
  appendLocalMessage({
    id: `system-${Date.now()}`,
    role: "system",
    content,
    assets: [],
    citations: [],
  });
}

function updateConversationPreview(conversationId, fallbackText) {
  const index = state.conversations.findIndex((item) => item.id === conversationId);
  if (index === -1) {
    return;
  }
  const conversation = state.conversations[index];
  const sanitizedPreview = sanitizeAssistantDisplayContent(
    stripAssistantApprovalBoilerplate(fallbackText || ""),
  );
  state.conversations[index] = {
    ...conversation,
    last_message_preview: sanitizedPreview || fallbackText || conversation.last_message_preview,
  };
}

function syncRunFromEvent(conversationId, assistantMessage, payload) {
  const run = payload?.run || payload?.item?.payload?.run || null;
  if (!run) {
    return null;
  }
  const stored = upsertAgentRun(conversationId, run);
  assistantMessage.agentRun = stored;
  return stored;
}

function syncItemFromEvent(conversationId, payload) {
  if (!conversationId) {
    return null;
  }
  const itemKeys = ["item", "approval_item", "work_product_item"];
  let latest = null;
  for (const key of itemKeys) {
    const item = payload?.[key];
    if (!item) {
      continue;
    }
    latest = upsertConversationItem(conversationId, item);
  }
  return latest;
}

async function uploadAttachment(attachment) {
  const formData = new FormData();
  formData.append("file", attachment.file, attachment.displayName);
  formData.append("care_context", attachment.careContext);

  return new Promise((resolve, reject) => {
    const request = new XMLHttpRequest();
    request.open("POST", "/v1/assets/upload");
    request.upload.addEventListener("progress", (event) => {
      if (!event.lengthComputable) {
        attachment.uploadProgress = Math.max(attachment.uploadProgress || 0, 0.12);
      } else {
        attachment.uploadProgress = event.loaded / event.total;
      }
      render();
    });
    request.addEventListener("load", () => {
      if (request.status < 200 || request.status >= 300) {
        reject(new Error(request.responseText || `Attachment upload failed with status ${request.status}`));
        return;
      }
      try {
        const payload = JSON.parse(request.responseText || "{}");
        resolve(payload.asset);
      } catch (error) {
        reject(new Error("Attachment upload completed, but the response was unreadable."));
      }
    });
    request.addEventListener("error", () => {
      reject(new Error("Attachment upload failed before reaching the local engine."));
    });
    request.addEventListener("abort", () => {
      reject(new Error("Attachment upload was cancelled."));
    });
    request.send(formData);
  });
}

async function uploadPendingAttachments() {
  if (!state.pendingAttachments.length) {
    return [];
  }

  updateStatus("thinking", "Uploading", "Saving attachments into the local workspace.");
  recordProcessEvent("upload", "Uploading attachments", "Saving files locally before analysis.");
  const uploadedAssets = [];
  for (const attachment of state.pendingAttachments) {
    attachment.uploadState = "uploading";
    attachment.uploadProgress = 0;
    attachment.uploadError = "";
    render();
    try {
      const uploaded = await uploadAttachment(attachment);
      attachment.uploadState = "done";
      attachment.uploadProgress = 1;
      uploadedAssets.push(uploaded);
      render();
    } catch (error) {
      attachment.uploadState = "failed";
      attachment.uploadError = error.message || "Unable to upload this file.";
      render();
      throw error;
    }
  }
  return uploadedAssets;
}

function clearPendingAttachments() {
  const staleAttachments = [...state.pendingAttachments];
  state.pendingAttachments = [];
  render();
  window.setTimeout(() => {
    for (const attachment of staleAttachments) {
      if (attachment.previewUrl) {
        URL.revokeObjectURL(attachment.previewUrl);
      }
    }
  }, 0);
}

function removePendingAttachment(localId) {
  const index = state.pendingAttachments.findIndex((attachment) => attachment.localId === localId);
  if (index === -1) {
    return;
  }
  const [attachment] = state.pendingAttachments.splice(index, 1);
  render();
  window.setTimeout(() => {
    if (attachment.previewUrl) {
      URL.revokeObjectURL(attachment.previewUrl);
    }
  }, 0);
}

function stopWatchMode() {
  if (state.camera.watchTimer) {
    window.clearInterval(state.camera.watchTimer);
  }
  state.camera.watchTimer = null;
  state.camera.watchActive = false;
}

function clearMonitorFrames() {
  for (const frame of state.camera.monitorFrames) {
    if (frame.previewUrl) {
      URL.revokeObjectURL(frame.previewUrl);
    }
  }
  state.camera.monitorFrames = [];
}

async function captureCameraFrameFile(labelPrefix = "camera-frame") {
  const video = elements.cameraPreview;
  const width = video.videoWidth;
  const height = video.videoHeight;
  if (!width || !height) {
    throw new Error("The live camera frame is not ready yet.");
  }

  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  const context = canvas.getContext("2d");
  if (!context) {
    throw new Error("The browser could not prepare a frame capture canvas.");
  }
  context.drawImage(video, 0, 0, width, height);
  const blob = await new Promise((resolve) => {
    canvas.toBlob(resolve, "image/jpeg", 0.9);
  });
  if (!blob) {
    throw new Error("The browser could not encode the live frame.");
  }

  return new File([blob], `${labelPrefix}-${timestampFileSlug()}.jpg`, {
    type: "image/jpeg",
  });
}

function storeMonitorFrame(file) {
  const previewUrl = URL.createObjectURL(file);
  const nextFrame = {
    id: `${Date.now()}-${Math.random().toString(16).slice(2)}`,
    file,
    previewUrl,
    capturedAt: new Date(),
  };
  const staleFrames = state.camera.monitorFrames.slice(3);
  for (const frame of staleFrames) {
    if (frame.previewUrl) {
      URL.revokeObjectURL(frame.previewUrl);
    }
  }
  state.camera.monitorFrames = [nextFrame, ...state.camera.monitorFrames.slice(0, 3)];
}

async function captureLiveSnapshot({ attach = true, monitor = true } = {}) {
  const file = await captureCameraFrameFile("live-frame");
  if (monitor) {
    storeMonitorFrame(file);
  }
  if (attach) {
    addPendingAttachments([file]);
    resizeComposer();
  } else {
    render();
  }
  return file;
}

function stopCameraStream() {
  const stream = state.camera.stream;
  if (stream) {
    for (const track of stream.getTracks()) {
      track.stop();
    }
  }
  state.camera.stream = null;
}

function clearCameraRecording() {
  if (state.camera.recordedUrl) {
    URL.revokeObjectURL(state.camera.recordedUrl);
  }
  state.camera.recordedUrl = null;
  state.camera.recordedFile = null;
  state.camera.mimeType = null;
}

function resetCameraState({ keepOpen = false } = {}) {
  stopWatchMode();
  if (state.camera.recorder && state.camera.recorder.state !== "inactive") {
    state.camera.recorder.stop();
  }
  state.camera.recorder = null;
  stopCameraStream();
  clearCameraRecording();
  clearMonitorFrames();
  state.camera.open = keepOpen;
  state.camera.status = "idle";
  state.camera.error = null;
  render();
}

async function openCameraPanel() {
  if (!hasLiveCameraSupport()) {
    elements.cameraCaptureInput.click();
    return;
  }

  resetCameraState({ keepOpen: true });
  state.camera.status = "opening";
  render();

  try {
    const stream = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: { ideal: "environment" } },
      audio: false,
    });
    state.camera.open = true;
    state.camera.stream = stream;
    state.camera.status = "ready";
    render();
  } catch (error) {
    const rawMessage = error?.message || "";
    const friendlyMessage =
      /permission|notallowed/i.test(rawMessage)
        ? "Live camera access was blocked. Grant permission or use native capture for stills and clips."
        : rawMessage || "The browser could not open the camera. You can still use native capture.";
    state.camera.open = true;
    state.camera.error = friendlyMessage;
    state.camera.status = "error";
    render();
  }
}

function closeCameraPanel() {
  resetCameraState({ keepOpen: false });
}

async function toggleWatchMode() {
  if (state.camera.watchActive) {
    stopWatchMode();
    state.camera.status = state.camera.stream ? "ready" : "idle";
    render();
    return;
  }

  if (!state.camera.stream) {
    await openCameraPanel();
  }
  if (!state.camera.stream) {
    return;
  }

  stopWatchMode();
  state.camera.watchActive = true;
  state.camera.status = "watching";
  try {
    await captureLiveSnapshot({ attach: false, monitor: true });
  } catch (error) {
    state.camera.error = error?.message || "Unable to capture a live monitoring frame.";
    state.camera.status = "error";
    state.camera.watchActive = false;
    render();
    return;
  }
  state.camera.watchTimer = window.setInterval(async () => {
    if (state.streaming || !state.camera.watchActive || state.camera.recorder?.state === "recording") {
      return;
    }
    try {
      await captureLiveSnapshot({ attach: false, monitor: true });
      state.camera.status = "watching";
    } catch (error) {
      stopWatchMode();
      state.camera.error = error?.message || "Watch mode stopped because a frame could not be sampled.";
      state.camera.status = "error";
      render();
    }
  }, state.camera.cadenceSeconds * 1000);
  render();
}

function finalizeCameraRecording(chunks, mimeType) {
  const resolvedType = mimeType || "video/webm";
  const extension = extensionForVideoType(resolvedType);
  const blob = new Blob(chunks, { type: resolvedType });
  const file = new File([blob], `camera-capture-${timestampFileSlug()}.${extension}`, {
    type: resolvedType,
  });
  clearCameraRecording();
  stopWatchMode();
  stopCameraStream();
  state.camera.recorder = null;
  state.camera.recordedFile = file;
  state.camera.recordedUrl = URL.createObjectURL(file);
  state.camera.mimeType = resolvedType;
  state.camera.status = "captured";
  state.camera.error = null;
  render();
}

function startCameraRecording() {
  if (!state.camera.stream) {
    openCameraPanel().catch(() => {});
    return;
  }
  if (!hasRecordingSupport()) {
    state.camera.error = "Recording is not supported in this browser. Use native capture instead.";
    state.camera.status = "error";
    render();
    return;
  }

  clearCameraRecording();
  stopWatchMode();
  const mimeType = preferredRecorderMimeType();
  const recorder = mimeType
    ? new MediaRecorder(state.camera.stream, { mimeType })
    : new MediaRecorder(state.camera.stream);
  const chunks = [];
  recorder.addEventListener("dataavailable", (event) => {
    if (event.data && event.data.size > 0) {
      chunks.push(event.data);
    }
  });
  recorder.addEventListener("stop", () => {
    finalizeCameraRecording(chunks, recorder.mimeType || mimeType);
  });
  recorder.start();
  state.camera.recorder = recorder;
  state.camera.status = "recording";
  state.camera.error = null;
  render();
}

function stopCameraRecording() {
  const recorder = state.camera.recorder;
  if (!recorder || recorder.state !== "recording") {
    return;
  }
  state.camera.status = "opening";
  recorder.stop();
  render();
}

async function retakeCameraRecording() {
  clearCameraRecording();
  await openCameraPanel();
}

function useCameraRecording() {
  if (!state.camera.recordedFile) {
    return;
  }
  addPendingAttachments([state.camera.recordedFile]);
  resizeComposer();
  closeCameraPanel();
}

async function attachCurrentCameraFrame() {
  try {
    await captureLiveSnapshot({ attach: true, monitor: true });
    state.camera.status = state.camera.watchActive ? "watching" : "ready";
    state.camera.error = null;
    render();
  } catch (error) {
    state.camera.error = error?.message || "Unable to capture the current live frame.";
    state.camera.status = "error";
    render();
  }
}

async function analyzeCurrentCameraFrame() {
  if (state.streaming) {
    return;
  }

  try {
    await captureLiveSnapshot({ attach: true, monitor: true });
    const prompt = elements.promptInput.value.trim() || cameraFramePrompt();
    elements.promptInput.value = "";
    resizeComposer();
    await submitTurn(prompt);
    updateStatus("ready", "Ready", "Live frame analysis complete.");
  } catch (error) {
    addSystemMessage(error.message || "Unable to analyze the current live frame.");
    updateStatus("error", "Camera", error.message || "Unable to analyze the current live frame.");
  } finally {
    state.streaming = false;
    render();
  }
}

async function ensureMedicalSession(conversationId) {
  const existing = state.medicalSessions.get(conversationId);
  if (existing) {
    return existing;
  }

  updateStatus("thinking", "Medical session", "Opening the explicit guarded medical workflow.");
  recordProcessEvent("medical", "Opening medical session", "Guarding the next turn before medical image analysis.");
  const session = await requestJson(
    `/v1/medical/sessions?conversation_id=${encodeURIComponent(conversationId)}`,
    {
      method: "POST",
    },
  );
  state.medicalSessions.set(conversationId, session);
  addSystemMessage(
    "Opened an explicit medical session for this conversation because a medical image was attached.",
  );
  return session;
}

function defaultPromptForAttachments(attachments) {
  if (attachments.some((asset) => asset.care_context === "medical")) {
    return "Please review the attached medical image conservatively.";
  }
  if (attachments.some((asset) => asset.kind === "video")) {
    return "Please review the attached video conservatively, noting visible tools, people, machines, and any process concerns without overclaiming.";
  }
  if (attachments.some((asset) => asset.kind === "image")) {
    return "Please review the attached image conservatively.";
  }
  return "Please review the attached file conservatively.";
}

async function submitTurn(prompt, options = {}) {
  state.streaming = true;
  state.processFeed = [];
  updateStatus("thinking", "Thinking", "Preparing the next turn locally.");
  recordProcessEvent("compose", "Preparing the turn", "Collecting attachments and opening the local stream.");
  render();

  let conversationId = state.activeConversationId;
  if (!conversationId) {
    const conversation = await createConversation(clip(prompt, 40));
    conversationId = conversation.id;
  }

  const uploadedAssets = await uploadPendingAttachments();
  const medicalAssets = uploadedAssets.filter((asset) => asset.care_context === "medical");
  let medicalSessionId = state.medicalSessions.get(conversationId)?.id || null;
  let turnMode = medicalSessionId ? "medical" : state.currentMode;

  if (medicalAssets.length > 0) {
    const session = await ensureMedicalSession(conversationId);
    medicalSessionId = session.id;
    turnMode = "medical";
  }

  appendLocalMessage({
    id: `user-${Date.now()}`,
    role: "user",
    content: prompt,
    assets: uploadedAssets,
    citations: [],
  });
  clearPendingAttachments();

  const response = await fetch(`/v1/conversations/${conversationId}/turns`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      conversation_id: conversationId,
      mode: turnMode,
      text: prompt,
      asset_ids: uploadedAssets.map((asset) => asset.id),
      enabled_knowledge_pack_ids: [],
      response_preferences: {
        style: "concise",
        citations: true,
        audio_reply: false,
      },
      medical_session_id: medicalSessionId,
      canvas_selection: options.canvasSelection || null,
    }),
  });

  if (!response.ok || !response.body) {
    const text = await response.text();
    throw new Error(text || `Turn failed with status ${response.status}`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
    const lines = buffer.split("\n");
    buffer = lines.pop() || "";

    for (const line of lines) {
      if (!line.trim()) {
        continue;
      }
      const event = JSON.parse(line);
      handleStreamEvent(event);
    }

    if (done) {
      break;
    }
  }

  await refreshConversations();
}

function selectedCanvasTurnContext(prompt) {
  if (state.pendingAttachments.length || state.streaming) {
    return null;
  }
  const action = selectedCanvasAction(prompt);
  if (!action) {
    return null;
  }
  const selection = currentCanvasSelection();
  if (!selection) {
    return null;
  }

  const collected = collectApprovalEdit(selection.container, selection.approval, { silent: true });
  if (collected === null) {
    return null;
  }

  const basePayload = approvalEffectivePayload(selection.approval);
  const currentPayload = { ...basePayload, ...(collected || {}) };
  currentPayload.content = selection.textarea.value;

  const titleField = selection.container.querySelector(
    `[data-approval-editor="${CSS.escape(selection.approval.id)}"] [data-approval-field="title"]`,
  );
  if (titleField) {
    currentPayload.title = titleField.value;
  }

  return {
    approval_id: selection.approvalId,
    field_name: selection.fieldName,
    start: selection.start,
    end: selection.end,
    text: selection.text,
    visible_content: selection.textarea.value,
    action,
    current_payload: currentPayload,
  };
}

function mergeAssets(existingAssets, newAssets) {
  const merged = [...(existingAssets || [])];
  const seen = new Set(merged.map((asset) => asset.id));
  for (const asset of newAssets || []) {
    if (!asset?.id || seen.has(asset.id)) {
      continue;
    }
    seen.add(asset.id);
    merged.push(asset);
  }
  return merged;
}

function handleStreamEvent(event) {
  const assistantMessage = event.turn_id ? ensureAssistantMessage(event.turn_id) : null;
  syncItemFromEvent(event.conversation_id, event.payload);

  if (event.type === "citation.added") {
    if (!assistantMessage) {
      render();
      return;
    }
    assistantMessage.loading = true;
    assistantMessage.citations.push(event.payload);
    const detail = `Added ${event.payload.label} as grounding context.`;
    mergeMessageProcess(assistantMessage, {
      kind: "retrieval",
      label: "Reviewing local material",
      detail,
    });
    recordProcessEvent("retrieval", "Reviewing local material", detail);
    updateStatus("thinking", "Working locally", detail);
  } else if (event.type === "turn.status") {
    if (!assistantMessage) {
      render();
      return;
    }
    assistantMessage.loading = true;
    syncRunFromEvent(event.conversation_id, assistantMessage, event.payload);
    mergeMessageProcess(assistantMessage, event.payload);
    recordProcessEvent(event.payload.kind || "turn", event.payload.label || "Working", event.payload.detail || "");
    updateStatus("thinking", event.payload.label || "Working", event.payload.detail || "");
  } else if (event.type === "assistant.delta") {
    if (!assistantMessage) {
      render();
      return;
    }
    assistantMessage.loading = true;
    assistantMessage.content += event.payload.text || "";
    updateStatus("thinking", "Writing", "Drafting the response from local context.");
  } else if (event.type === "assistant.message.completed") {
    if (!assistantMessage) {
      render();
      return;
    }
    assistantMessage.loading = false;
    assistantMessage.content = event.payload.text || assistantMessage.content;
    assistantMessage.assets = mergeAssets(assistantMessage.assets, event.payload.assets || []);
    assistantMessage.process = [];
    updateConversationPreview(event.conversation_id, assistantMessage.content);
    updateStatus("ready", "Ready", "Response complete.");
    scheduleConversationStateRefresh(event.conversation_id);
  } else if (event.type === "tool.proposed") {
    if (!assistantMessage) {
      render();
      return;
    }
    assistantMessage.loading = true;
    syncRunFromEvent(event.conversation_id, assistantMessage, event.payload);
    assistantMessage.proposedTool = event.payload.tool_name;
    const detail = approvalReviewDetail(event.payload);
    mergeMessageProcess(assistantMessage, {
      kind: "tool",
      label: "Prepared local action",
      detail,
    });
    recordProcessEvent("tool", "Prepared local action", detail);
  } else if (event.type === "tool.started") {
    if (!assistantMessage) {
      render();
      return;
    }
    assistantMessage.loading = true;
    syncRunFromEvent(event.conversation_id, assistantMessage, event.payload);
    assistantMessage.proposedTool = event.payload.tool_name;
    const detail = `Running ${humanizeToolName(event.payload.tool_name)} inside the local engine.`;
    mergeMessageProcess(assistantMessage, {
      kind: "tool",
      label: "Running local helper",
      detail,
    });
    recordProcessEvent("tool", "Running local helper", detail);
    updateStatus("thinking", "Processing", detail);
  } else if (event.type === "tool.completed") {
    if (!assistantMessage) {
      render();
      return;
    }
    assistantMessage.loading = true;
    syncRunFromEvent(event.conversation_id, assistantMessage, event.payload);
    assistantMessage.toolResult = event.payload.result || null;
    assistantMessage.assets = mergeAssets(assistantMessage.assets, event.payload.assets || []);
    const detail = event.payload.result?.message || `Finished ${humanizeToolName(event.payload.tool_name)}.`;
    mergeMessageProcess(assistantMessage, {
      kind: "tool",
      label: "Local helper complete",
      detail,
    });
    recordProcessEvent("tool", "Local helper complete", detail);
  } else if (event.type === "document.edited") {
    if (!assistantMessage) {
      render();
      return;
    }
    assistantMessage.loading = true;
    const detail = "Recorded the selected canvas edit in the thread item ledger.";
    mergeMessageProcess(assistantMessage, {
      kind: "tool",
      label: "Document edit recorded",
      detail,
    });
    recordProcessEvent("tool", "Document edit recorded", detail);
  } else if (event.type === "approval.required") {
    if (!assistantMessage) {
      render();
      return;
    }
    assistantMessage.loading = false;
    const approvalPayload = { ...event.payload };
    const runPayload = approvalPayload.run || null;
    delete approvalPayload.run;
    clearApprovalDraft(approvalPayload.id);
    if (state.canvasSelection?.approvalId === approvalPayload.id) {
      state.canvasSelection = null;
    }
    if (runPayload) {
      upsertAgentRun(event.conversation_id, runPayload);
    } else {
      syncRunFromEvent(event.conversation_id, assistantMessage, event.payload);
    }
    state.approvals.set(approvalPayload.id, approvalPayload);
    state.artifactPanelCollapsed = false;
    state.artifactMode = "summary";
    assistantMessage.approval = approvalPayload;
    assistantMessage.workProduct = null;
    assistantMessage.proposedTool = approvalPayload.tool_name;
    assistantMessage.toolResult = approvalPayload.result || null;
    const detail = approvalReviewDetail(approvalPayload);
    mergeMessageProcess(assistantMessage, {
      kind: "tool",
      label: "Approval needed",
      detail,
    });
    recordProcessEvent("tool", "Approval needed", detail);
  } else if (event.type === "warning") {
    addSystemMessage(event.payload.message || event.payload.text || "Warning");
  } else if (event.type === "error") {
    if (assistantMessage) {
      assistantMessage.loading = false;
    }
    addSystemMessage(event.payload.message || event.payload.text || "Error");
    updateStatus("error", "Error", event.payload.message || event.payload.text || "The local engine hit an error.");
  }

  render();
}

async function submitApprovalDecision(approvalId, action, editedPayload = {}) {
  try {
    const approval = await requestJson(`/v1/approvals/${approvalId}/decisions`, {
      method: "POST",
      body: JSON.stringify({
        action,
        edited_payload: editedPayload,
      }),
    });

    clearApprovalDraft(approvalId);
    state.approvalErrors.delete(approvalId);
    state.approvals.set(approvalId, approval);
    if (approval.item && state.activeConversationId) {
      upsertConversationItem(state.activeConversationId, approval.item);
    }
    if (approval.work_product_item && state.activeConversationId) {
      upsertConversationItem(state.activeConversationId, approval.work_product_item);
    }
    if (approval.run && state.activeConversationId) {
      upsertAgentRun(state.activeConversationId, approval.run);
    }
    if (state.activeConversationId) {
      scheduleConversationStateRefresh(state.activeConversationId, 30);
    }
    render();
  } catch (error) {
    state.approvalErrors.set(approvalId, error.message || "Unable to save that draft.");
    render({ preserveScroll: true });
    addSystemMessage(error.message || "Unable to save that draft.");
  }
}

function closeSidebar() {
  state.mobileSidebarOpen = false;
  elements.sidebar.classList.remove("is-open");
  elements.backdrop.classList.remove("is-open");
  applySidebarState();
}

function openSidebar() {
  state.mobileSidebarOpen = true;
  elements.sidebar.classList.add("is-open");
  elements.backdrop.classList.add("is-open");
  applySidebarState();
}

function applySidebarState() {
  const drawerLayout = isSidebarDrawerLayout();
  elements.appShell.classList.toggle("is-sidebar-collapsed", !drawerLayout && state.sidebarCollapsed);
  if (drawerLayout) {
    elements.sidebar.classList.toggle("is-open", state.mobileSidebarOpen);
    elements.backdrop.classList.toggle("is-open", state.mobileSidebarOpen);
  } else {
    elements.sidebar.classList.remove("is-open");
    elements.backdrop.classList.remove("is-open");
  }
  const expanded = drawerLayout ? state.mobileSidebarOpen : !state.sidebarCollapsed;
  elements.sidebarToggle.setAttribute("aria-expanded", String(expanded));
}

function toggleSidebar() {
  if (!isSidebarDrawerLayout()) {
    state.sidebarCollapsed = !state.sidebarCollapsed;
    applySidebarState();
    return;
  }
  if (state.mobileSidebarOpen) {
    closeSidebar();
  } else {
    openSidebar();
  }
}

function runSidebarCommand(command) {
  switch (command) {
    case "search":
      elements.promptInput.focus();
      updateStatus("ready", "Search ready", "Type in the composer to search or ask across this local workspace.");
      break;
    case "plugins":
      addSystemMessage("Plugins will live here as local tools become installable from the workbench.");
      updateStatus("ready", "Plugins", "Opened the plugins placeholder.");
      break;
    case "automations":
      addSystemMessage("Automations will live here once scheduled local tasks are enabled for this workbench.");
      updateStatus("ready", "Automations", "Opened the automations placeholder.");
      break;
    default:
      return;
  }
  closeSidebar();
}

function resizeComposer() {
  elements.promptInput.style.height = "auto";
  elements.promptInput.style.height = `${Math.min(elements.promptInput.scrollHeight, 180)}px`;
  elements.sendButton.disabled =
    state.streaming ||
    (!elements.promptInput.value.trim() && state.pendingAttachments.length === 0);
}

function updateResponsiveChrome() {
  elements.promptInput.placeholder = window.innerWidth <= 640 ? "Ask locally" : "Ask the local assistant";
  if (window.innerWidth > 1080 && state.mobileSidebarOpen) {
    closeSidebar();
  } else {
    applySidebarState();
  }
  if (!isArtifactDrawerLayout() && state.mobileArtifactOpen) {
    setMobileArtifactOpen(false);
  } else {
    renderArtifactPanel();
  }
}

function addPendingAttachments(files) {
  for (const file of files) {
    const kind = guessAssetKind(file.type, file.name);
    state.pendingAttachments.push({
      localId: `${Date.now()}-${Math.random().toString(16).slice(2)}`,
      file,
      displayName: file.name,
      mediaType: file.type || null,
      kind,
      careContext: "general",
      previewUrl: kind === "image" || kind === "video" ? URL.createObjectURL(file) : null,
      uploadState: "queued",
      uploadProgress: 0,
      uploadError: "",
    });
  }
  render();
}

function hasFileTransfer(event) {
  return Array.from(event.dataTransfer?.types || []).includes("Files");
}

function setAttachmentDragActive(active) {
  if (state.dragActive === Boolean(active)) {
    return;
  }
  state.dragActive = Boolean(active);
  render();
}

function handleAttachmentDrop(event) {
  if (!hasFileTransfer(event)) {
    return;
  }
  event.preventDefault();
  event.stopPropagation();
  setAttachmentDragActive(false);
  const files = Array.from(event.dataTransfer?.files || []);
  if (!files.length) {
    return;
  }
  addPendingAttachments(files);
  resizeComposer();
  updateStatus("ready", "Attached", `${files.length} file${files.length === 1 ? "" : "s"} queued for local review.`);
}

async function onSubmit(event) {
  event.preventDefault();
  const fallbackPrompt = defaultPromptForAttachments(
    state.pendingAttachments.map((attachment) => ({
      kind: attachment.kind,
      care_context: attachment.careContext,
    })),
  );
  const prompt = elements.promptInput.value.trim() || fallbackPrompt;
  if ((!prompt && state.pendingAttachments.length === 0) || state.streaming) {
    return;
  }

  elements.promptInput.value = "";
  resizeComposer();

  try {
    const canvasSelection = selectedCanvasTurnContext(prompt);
    await submitTurn(prompt, { canvasSelection });
    updateStatus("ready", "Ready", canvasSelection ? "Canvas draft updated." : "Response complete.");
  } catch (error) {
    addSystemMessage(error.message || "Unable to complete turn.");
    updateStatus("error", "Error", error.message || "Unable to complete turn.");
  } finally {
    state.streaming = false;
    render();
  }
}

function attachEventHandlers() {
  elements.composer.addEventListener("submit", onSubmit);
  elements.newChatButton.addEventListener("click", () => {
    state.activeConversationId = null;
    persistActiveConversation();
    state.draftMessages = [];
    state.processFeed = [];
    state.canvasSelection = null;
    state.artifactPanelCollapsed = false;
    clearPendingAttachments();
    closeCameraPanel();
    updateStatus("ready", "Ready", "Ready for a new conversation.");
    render();
    closeSidebar();
  });
  for (const commandButton of elements.sidebarCommands) {
    commandButton.addEventListener("click", () => {
      runSidebarCommand(commandButton.dataset.sidebarCommand);
    });
  }
  elements.promptInput.addEventListener("input", resizeComposer);
  elements.promptInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      elements.composer.requestSubmit();
    }
  });
  elements.sidebarToggle.addEventListener("click", toggleSidebar);
  elements.backdrop.addEventListener("click", closeSidebar);
  if (elements.artifactToggle) {
    elements.artifactToggle.addEventListener("click", () => {
      if (isArtifactDrawerLayout()) {
        setMobileArtifactOpen(!state.mobileArtifactOpen);
        return;
      }
      state.artifactPanelCollapsed = !state.artifactPanelCollapsed;
      renderArtifactPanel();
    });
  }
  elements.statusButton.addEventListener("click", (event) => {
    event.stopPropagation();
    toggleStatusMenu();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") {
      return;
    }
    if (state.mobileSidebarOpen) {
      closeSidebar();
    }
    if (state.mobileArtifactOpen) {
      setMobileArtifactOpen(false);
    }
    toggleStatusMenu(false);
  });
  document.addEventListener("click", (event) => {
    if (!elements.statusMenu.contains(event.target) && !elements.statusButton.contains(event.target)) {
      toggleStatusMenu(false);
    }
  });
  elements.attachmentButton.addEventListener("click", () => {
    elements.fileInput.click();
  });
  elements.composer.addEventListener("dragenter", (event) => {
    if (!hasFileTransfer(event)) {
      return;
    }
    event.preventDefault();
    setAttachmentDragActive(true);
  });
  elements.composer.addEventListener("dragover", (event) => {
    if (!hasFileTransfer(event)) {
      return;
    }
    event.preventDefault();
    event.dataTransfer.dropEffect = "copy";
    setAttachmentDragActive(true);
  });
  elements.composer.addEventListener("dragleave", (event) => {
    if (!elements.composer.contains(event.relatedTarget)) {
      setAttachmentDragActive(false);
    }
  });
  elements.composer.addEventListener("drop", handleAttachmentDrop);
  elements.cameraButton.addEventListener("click", () => {
    openCameraPanel().catch((error) => {
      addSystemMessage(error.message || "Unable to open the local camera.");
      updateStatus("error", "Camera", error.message || "Unable to open the local camera.");
    });
  });
  elements.cameraCloseButton.addEventListener("click", closeCameraPanel);
  elements.cameraLiveButton.addEventListener("click", () => {
    openCameraPanel().catch((error) => {
      addSystemMessage(error.message || "Unable to refresh the live camera.");
    });
  });
  elements.cameraWatchButton.addEventListener("click", () => {
    toggleWatchMode().catch((error) => {
      addSystemMessage(error.message || "Unable to start live watch mode.");
    });
  });
  elements.cameraNativeButton.addEventListener("click", () => {
    elements.cameraCaptureInput.click();
  });
  elements.cameraSnapshotButton.addEventListener("click", () => {
    attachCurrentCameraFrame().catch((error) => {
      addSystemMessage(error.message || "Unable to capture the current frame.");
    });
  });
  elements.cameraAnalyzeButton.addEventListener("click", () => {
    analyzeCurrentCameraFrame().catch((error) => {
      addSystemMessage(error.message || "Unable to analyze the current frame.");
    });
  });
  elements.cameraRecordButton.addEventListener("click", startCameraRecording);
  elements.cameraStopButton.addEventListener("click", stopCameraRecording);
  elements.cameraRetakeButton.addEventListener("click", () => {
    retakeCameraRecording().catch((error) => {
      addSystemMessage(error.message || "Unable to reopen the camera.");
    });
  });
  elements.cameraUseButton.addEventListener("click", useCameraRecording);
  elements.fileInput.addEventListener("change", () => {
    const files = Array.from(elements.fileInput.files || []);
    if (files.length) {
      addPendingAttachments(files);
      resizeComposer();
    }
    elements.fileInput.value = "";
  });
  elements.cameraCaptureInput.addEventListener("change", () => {
    const files = Array.from(elements.cameraCaptureInput.files || []);
    if (files.length) {
      addPendingAttachments(files);
      resizeComposer();
    }
    elements.cameraCaptureInput.value = "";
    closeCameraPanel();
  });
  elements.voiceButton.addEventListener("click", () => {
    addSystemMessage(
      "Voice capture is the next layer. The placeholder is here so the shell keeps the right interaction shape.",
    );
  });
  window.addEventListener("beforeunload", () => {
    stopWatchMode();
    stopCameraStream();
    clearCameraRecording();
    clearMonitorFrames();
  });
  window.addEventListener("resize", updateResponsiveChrome);
}

async function bootstrap() {
  loadPersistedUiState();
  attachEventHandlers();
  updateResponsiveChrome();
  resizeComposer();
  updateStatus("ready", "Ready", "Ready for the next turn.");
  try {
    await loadCapabilities();
    await refreshConversations();
    const preferredConversation = state.activeConversationId;
    if (preferredConversation && state.conversations.some((conversation) => conversation.id === preferredConversation)) {
      await openConversation(preferredConversation);
    } else if (state.conversations.length) {
      await openConversation(state.conversations[0].id);
    } else {
      persistActiveConversation();
    }
  } catch (error) {
    updateStatus("error", "Offline", "The local engine is unavailable.");
    addSystemMessage("The chat shell could not reach the local engine. Start the FastAPI server and reload.");
  }
}

bootstrap();
