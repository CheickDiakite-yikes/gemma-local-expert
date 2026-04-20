const state = {
  conversations: [],
  activeConversationId: null,
  currentMode: "general",
  streaming: false,
  mobileSidebarOpen: false,
  statusMenuOpen: false,
  draftMessages: [],
  pendingAttachments: [],
  transcripts: new Map(),
  agentRuns: new Map(),
  approvals: new Map(),
  approvalDrafts: new Map(),
  approvalPanels: new Map(),
  messagePanels: new Map(),
  runPanels: new Map(),
  capabilities: null,
  medicalSessions: new Map(),
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
  approvalPanels: "field-assistant.approval-panels.v1",
  messagePanels: "field-assistant.message-panels.v1",
  runPanels: "field-assistant.run-panels.v2",
  activeConversation: "field-assistant.active-conversation.v1",
};

const elements = {
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
  sidebarToggle: document.getElementById("sidebar-toggle"),
  statusButton: document.getElementById("status-button"),
  statusDot: document.getElementById("status-dot"),
  statusMenu: document.getElementById("status-menu"),
  statusPill: document.getElementById("status-pill"),
  statusRuntimeCopy: document.getElementById("status-runtime-copy"),
  processList: document.getElementById("process-list"),
  voiceButton: document.getElementById("voice-button"),
};

function activeMessages() {
  if (!state.activeConversationId) {
    return state.draftMessages;
  }
  return conversationTranscript(state.activeConversationId);
}

function conversationTranscript(conversationId) {
  return state.transcripts.get(conversationId) ?? [];
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

  for (const approvalId of approvalIds) {
    state.approvalDrafts.delete(approvalId);
    state.approvalPanels.delete(approvalPanelKey(approvalId, "draft"));
    state.approvalPanels.delete(approvalPanelKey(approvalId, "edit"));
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
  state.agentRuns.delete(conversationId);
  state.medicalSessions.delete(conversationId);
  persistApprovalDrafts();
  persistApprovalPanels();
  persistMessagePanels();
  persistRunPanels();
}

function runsForConversation(conversationId) {
  return state.agentRuns.get(conversationId) || [];
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
  const binaryBits = [];
  binaryBits.push(capabilities.tesseract_available ? "tesseract" : "no tesseract");
  binaryBits.push(capabilities.ffmpeg_available ? "ffmpeg" : "no ffmpeg");
  const profile = capabilities.low_memory_profile ? "low-memory profile" : "full profile";
  return `${capabilities.assistant_backend} / ${capabilities.embedding_backend} / ${capabilities.specialist_backend} / ${capabilities.tracking_backend} • ${binaryBits.join(" • ")} • ${profile}`;
}

function approvalDraftFor(approvalId) {
  return state.approvalDrafts.get(approvalId) || null;
}

function approvalEditableFields(approval) {
  switch (approval?.tool_name) {
    case "create_task":
      return ["title", "details", "status"];
    case "create_note":
    case "create_checklist":
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

function approvalPanelKey(approvalId, section) {
  return `${approvalId}:${section}`;
}

function approvalPanelPreference(approvalId, section) {
  return state.approvalPanels.get(approvalPanelKey(approvalId, section));
}

function isApprovalSectionExpanded(approval, section) {
  const saved = approvalPanelPreference(approval.id, section);
  if (typeof saved === "boolean") {
    return saved;
  }
  return false;
}

function setApprovalSectionExpanded(approvalId, section, expanded) {
  state.approvalPanels.set(approvalPanelKey(approvalId, section), Boolean(expanded));
  persistApprovalPanels();
}

function approvalStatusLabel(status) {
  switch (status) {
    case "pending":
      return "Ready to save";
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
      return "Draft ready";
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
    case "create_checklist":
      return "Save checklist";
    case "create_task":
      return "Save task";
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
    case "create_checklist":
      return "checklist";
    case "create_task":
      return "task";
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
    return "The local write completed and the result is now saved in this workspace.";
  }
  if (approval.status === "rejected") {
    return "The draft was reviewed but not saved locally.";
  }
  if (approval.status === "failed") {
    return "The local write did not finish cleanly.";
  }
  switch (approval.tool_name) {
    case "create_checklist":
      return "Review or refine the checklist before it is saved locally.";
    case "create_task":
      return "Review or refine the task before it is saved locally.";
    case "log_observation":
      return "Review or refine the observation before it is saved locally.";
    case "create_note":
      return "Review or refine the note before it is saved locally.";
    default:
      return "Review this local draft before it is saved.";
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

function approvalMeaningfulLines(text) {
  return String(text || "")
    .replace(/\r\n?/g, "\n")
    .split("\n")
    .map((line) => stripMarkdownToText(line))
    .map((line) => line.trim())
    .filter(Boolean)
    .filter(
      (line) =>
        !/^(goal|workspace scope|top-level scope entries|workspace findings|related docs|related local docs|date|status):/i.test(
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

function approvalPayloadMeta(approval, payload) {
  const bits = [];
  if (approval?.tool_name === "create_task" && payload?.status) {
    bits.push(`Status: ${humanizeRunStatus(payload.status)}`);
  }
  if (payload?.content) {
    const lineCount = String(payload.content)
      .split(/\r?\n/)
      .map((line) => line.trim())
      .filter(Boolean).length;
    if (lineCount > 1) {
      bits.push(`${lineCount} lines`);
    }
    if (approval?.tool_name === "create_checklist") {
      const itemCount = String(payload.content)
        .split(/\r?\n/)
        .map((line) => line.trim())
        .filter((line) => /^[-*+]\s+/.test(line) || /^\d+\.\s+/.test(line)).length;
      if (itemCount) {
        bits.push(`${itemCount} items`);
      }
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
      /^please approve\b/i.test(normalized) ||
      /^approval required:?/i.test(normalized) ||
      /^please confirm if you approve this action\b/i.test(normalized) ||
      /^please confirm if you want me to proceed\b/i.test(normalized) ||
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
  return plain === "workspace agent actions are limited to the configured local workspace scope.";
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
      ${
        collapsible
          ? `<button class="message-content-toggle" data-message-content-toggle="${escapeHtml(messagePanelKey(message, "context"))}" type="button">${expanded ? "Hide context" : "Context"}</button>`
          : ""
      }
      <div class="message-content${richTextRoles.has(message.role) ? " rich-text" : ""}">${body}</div>
    </div>
  `;
}

function renderApprovalPreview(approval, overridePayload = undefined) {
  const payload = approvalEffectivePayload(approval, overridePayload);
  if (!payload || !Object.keys(payload).length) {
    return "";
  }
  const previewTitle = payload.title
    ? `<div class="approval-preview-title">${escapeHtml(payload.title)}</div>`
    : "";
  const previewSummary = approvalPayloadExcerpt(approval, payload);
  const meta = approvalPayloadMeta(approval, payload)
    .map((bit) => `<span>${escapeHtml(bit)}</span>`)
    .join("");
  const helperCopy =
    approval.status === "pending"
      ? "Open Edit to inspect or refine the full draft before saving."
      : "This is the saved draft summary for the completed action.";

  return `
    <section class="approval-preview">
      ${previewTitle}
      ${previewSummary ? `<p class="approval-preview-summary">${escapeHtml(previewSummary)}</p>` : ""}
      ${meta ? `<div class="approval-preview-meta">${meta}</div>` : ""}
      <p class="approval-preview-note">${escapeHtml(helperCopy)}</p>
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
  if (approval.tool_name === "create_task") {
    return `
      <section class="approval-editor approval-editor-task" data-approval-editor="${approval.id}">
        <div class="approval-editor-header">
          <div class="approval-editor-copy">
            <strong>Edit draft</strong>
            <span>Changes stay local until you approve the write.</span>
          </div>
          <div class="approval-editor-controls">
            <span class="approval-editor-state${isDirty ? " is-dirty" : ""}" data-approval-draft-state>${draftStateText}</span>
            <button class="approval-editor-reset" data-approval-reset type="button"${isDirty ? "" : " disabled"}>Revert</button>
          </div>
        </div>
        <div class="approval-editor-grid approval-editor-grid-task">
          <label class="approval-field approval-field-full">
            <span>Title</span>
            <input data-approval-field="title" type="text" value="${escapeHtml(payload.title || "")}" />
          </label>
          <label class="approval-field approval-field-full">
            <span>Details</span>
            <textarea data-approval-field="details" rows="5">${escapeHtml(payload.details || "")}</textarea>
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

  if (["create_note", "create_checklist", "log_observation"].includes(approval.tool_name)) {
    const helperCopy =
      approval.tool_name === "create_checklist"
        ? "Adjust the saved checklist title or items before it is written locally."
        : "Adjust the saved draft before it is written locally.";
    return `
      <section class="approval-editor approval-editor-simple" data-approval-editor="${approval.id}">
        <div class="approval-editor-header">
          <div class="approval-editor-copy">
            <strong>Edit draft</strong>
            <span>${escapeHtml(helperCopy)}</span>
          </div>
          <div class="approval-editor-controls">
            <span class="approval-editor-state${isDirty ? " is-dirty" : ""}" data-approval-draft-state>${draftStateText}</span>
            <button class="approval-editor-reset" data-approval-reset type="button"${isDirty ? "" : " disabled"}>Revert</button>
          </div>
        </div>
        <div class="approval-editor-grid">
          <label class="approval-field approval-field-full">
            <span>Title</span>
            <input data-approval-field="title" type="text" value="${escapeHtml(payload.title || "")}" />
          </label>
          <label class="approval-field approval-field-full">
            <span>${approval.tool_name === "create_checklist" ? "Checklist content" : "Content"}</span>
            <textarea data-approval-field="content" rows="${approval.tool_name === "create_checklist" ? "6" : "5"}">${escapeHtml(payload.content || "")}</textarea>
          </label>
        </div>
      </section>
    `;
  }

  return `
    <section class="approval-editor approval-editor-advanced" data-approval-editor="${approval.id}">
      <div class="approval-editor-header">
        <div class="approval-editor-copy">
          <strong>Edit payload</strong>
          <span>Advanced fields stay local until you approve the write.</span>
        </div>
        <div class="approval-editor-controls">
          <span class="approval-editor-state${isDirty ? " is-dirty" : ""}" data-approval-draft-state>${draftStateText}</span>
          <button class="approval-editor-reset" data-approval-reset type="button"${isDirty ? "" : " disabled"}>Revert</button>
        </div>
      </div>
      <div class="approval-editor-grid">
        <label class="approval-field approval-field-code approval-field-full">
          <span>Payload JSON</span>
          <textarea data-approval-json rows="7">${escapeHtml(JSON.stringify(payload, null, 2))}</textarea>
        </label>
      </div>
    </section>
  `;
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

  return `<div class="approval-result">${resultBits.join(" · ")}</div>`;
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
    case "create_checklist":
      return "a checklist draft";
    case "create_task":
      return "a task draft";
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
    .replace(/`create_checklist`/g, "a checklist draft")
    .replace(/`create_task`/g, "a task draft")
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
    card.className = "attachment-draft";
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
        `
        : `<span>${attachment.kind === "video" ? "Video upload" : "Local file"}</span>`;
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
    const row = document.createElement("article");
    row.className = [
      "message-row",
      message.role,
      message.loading ? "is-loading" : "",
      message.agentRun ? "has-agent-run" : "",
      message.approval ? "has-approval" : "",
    ]
      .filter(Boolean)
      .join(" ");

    const citations = (message.citations || [])
      .map(
        (citation) =>
          `<span class="citation-chip" title="${escapeHtml(citation.excerpt || "")}">${escapeHtml(citation.label)}</span>`,
      )
      .join("");

    const toolChip = message.proposedTool && !message.approval
      ? `<span class="tool-chip">Prepared ${escapeHtml(message.proposedTool)}</span>`
      : "";

    const approvalCard = renderApprovalMarkup(message.approval);
    const assetGallery = renderAssetMarkup(message.assets || []);
    const toolResultCard = renderToolResultMarkup(message.toolResult);
    const agentRunCard = renderAgentRunMarkup(message.agentRun, message.approval);
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
    if (message.approval) {
      wireApprovalActions(row, message.approval);
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

  const previewExpanded = isApprovalSectionExpanded(approval, "preview");
  const editorExpanded = approval.status === "pending" ? isApprovalSectionExpanded(approval, "editor") : false;
  const sectionControls = `
    <div class="approval-view-switch">
      <button
        class="approval-view-toggle${previewExpanded ? " is-active" : ""}"
        data-approval-section-toggle="preview"
        data-approval-id="${approval.id}"
        type="button"
      >
        Draft
      </button>
      ${
        approval.status === "pending"
          ? `
        <button
          class="approval-view-toggle${editorExpanded ? " is-active" : ""}"
          data-approval-section-toggle="editor"
          data-approval-id="${approval.id}"
          type="button"
        >
          Edit
        </button>
      `
          : ""
      }
    </div>
  `;

  const actions =
    approval.status === "pending"
      ? `
        <div class="approval-actions">
          <button class="approval-action approve" data-approval-action="approve" data-approval-id="${approval.id}" type="button">Save locally</button>
          <button class="approval-action reject" data-approval-action="reject" data-approval-id="${approval.id}" type="button">Not now</button>
        </div>
      `
      : "";

  return `
    <section class="approval-card is-${escapeHtml(approval.status)}">
      <div class="approval-header approval-header-inline">
        <div class="approval-header-main">
          <div class="approval-heading-line">
            <span class="approval-kicker">${approvalStatusKicker(approval.status)}</span>
            <h4>${escapeHtml(approvalSurfaceTitle(approval.tool_name))}</h4>
          </div>
          <p class="approval-summary">${escapeHtml(approvalSummaryText(approval))}</p>
        </div>
        <div class="approval-toolbar">
          <div class="approval-status is-${escapeHtml(approval.status)}" data-approval-status>${escapeHtml(approvalStatusLabel(approval.status))}</div>
          ${sectionControls}
          ${actions}
        </div>
      </div>
      <div class="approval-section approval-section-preview"${previewExpanded ? "" : " hidden"}>
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
  for (const field of editor.querySelectorAll("[data-approval-field]")) {
    const name = field.dataset.approvalField;
    if (!name) {
      continue;
    }
    editedPayload[name] = field.value;
  }
  return editedPayload;
}

function refreshApprovalCardState(container, approval, collected = undefined) {
  const currentEdit = collected === undefined ? collectApprovalEdit(container, approval, { silent: true }) : collected;
  const previewSlot = container.querySelector("[data-approval-preview-slot]");
  const stateLabel = container.querySelector("[data-approval-draft-state]");
  const resetButton = container.querySelector("[data-approval-reset]");
  const approveButton = container.querySelector('[data-approval-action="approve"]');
  const editor = container.querySelector(`[data-approval-editor="${approval.id}"]`);
  if (!editor) {
    return;
  }

  if (currentEdit === null) {
    editor.classList.add("has-invalid-draft");
    if (stateLabel) {
      stateLabel.textContent = approvalDraftStateText({ invalid: true });
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
    stateLabel.textContent = approvalDraftStateText({ dirty });
    stateLabel.classList.toggle("is-dirty", dirty);
    stateLabel.classList.remove("is-invalid");
  }
  if (resetButton) {
    resetButton.disabled = !dirty;
  }
  if (approveButton) {
    approveButton.disabled = false;
  }
}

function resizeApprovalTextareas(container) {
  for (const textarea of container.querySelectorAll(".approval-editor textarea")) {
    const minHeight = textarea.dataset.approvalJson !== undefined ? 132 : 96;
    const maxHeight = window.innerWidth <= 640 ? 220 : 280;
    textarea.style.height = "auto";
    const nextHeight = Math.min(Math.max(textarea.scrollHeight, minHeight), maxHeight);
    textarea.style.height = `${nextHeight}px`;
    textarea.classList.toggle("is-overflowing", textarea.scrollHeight > maxHeight + 4);
  }
}

function wireApprovalActions(container, approval) {
  const editor = container.querySelector(`[data-approval-editor="${approval.id}"]`);
  if (editor) {
    for (const field of editor.querySelectorAll("[data-approval-field], [data-approval-json]")) {
      field.addEventListener("input", () => {
        refreshApprovalCardState(container, approval);
        resizeApprovalTextareas(container);
      });
    }
    const resetButton = editor.querySelector("[data-approval-reset]");
    if (resetButton) {
      resetButton.addEventListener("click", () => {
        clearApprovalDraft(approval.id);
        render();
      });
    }
    resizeApprovalTextareas(container);
    refreshApprovalCardState(container, approval);
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
      ? "Recording locally"
      : camera.status === "watching"
        ? "Watching locally"
      : camera.status === "ready"
        ? "Camera ready"
        : camera.status === "captured"
          ? "Clip ready"
          : camera.status === "error"
            ? "Camera unavailable"
            : "Opening camera";
  elements.cameraStatusCopy.textContent =
    camera.error ||
    (camera.status === "captured"
      ? "Use the clip to attach it to the next turn, or retake it."
      : camera.status === "watching"
        ? `Sampling one frame every ${camera.cadenceSeconds}s on-device. Use a monitor frame or capture a fresh one for analysis.`
      : camera.status === "recording"
        ? "Recording stays on-device until you choose to attach it."
        : "Previewing the local feed. Capture a frame, analyze it immediately, or fall back to native device capture.");

  elements.cameraModeLabel.textContent = hasClip ? "Clip review" : "Live review";
  elements.cameraCadenceLabel.textContent = isWatching
    ? `${camera.cadenceSeconds}s sampling`
    : "Manual";
  elements.cameraOutputLabel.textContent = hasClip
    ? "Attach a recorded clip"
    : camera.status === "error"
      ? "Use native capture or retry live"
    : isWatching
      ? "Recent local watch frames"
      : "Attach frames or clips";

  elements.cameraSheet.classList.toggle("is-recording", isRecording);
  elements.cameraSheet.classList.toggle("is-watching", isWatching);
  elements.cameraLiveButton.textContent = hasLivePreview ? "Retry live" : "Open live";
  elements.cameraWatchButton.textContent = isWatching ? "Stop watch" : "Start watch";
  const showLiveControls = hasLivePreview && !hasClip && !isRecording;
  const showRecoveryControls = !hasLivePreview && !hasClip && !isRecording;

  elements.cameraLiveButton.hidden = hasClip || isRecording;
  elements.cameraWatchButton.hidden = !showLiveControls;
  elements.cameraRecordButton.hidden = !showLiveControls;
  elements.cameraStopButton.hidden = !isRecording;
  elements.cameraRetakeButton.hidden = !hasClip;
  elements.cameraUseButton.hidden = !hasClip;
  elements.cameraNativeButton.hidden = isRecording || hasClip === true;
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
  elements.conversationTitle.textContent = activeConversation
    ? clip(conversationLabel(activeConversation), 44)
    : "New conversation";

  renderConversations();
  renderAttachmentStrip();
  renderMessages(options);
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
    throw new Error(text || `Request failed: ${response.status}`);
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

async function openConversation(conversationId) {
  state.activeConversationId = conversationId;
  persistActiveConversation();
  if (!state.transcripts.has(conversationId)) {
    const [transcript, runs] = await Promise.all([
      requestJson(`/v1/conversations/${conversationId}/messages`),
      requestJson(`/v1/conversations/${conversationId}/runs`),
    ]);
    state.agentRuns.set(conversationId, runs);
    const runsByTurn = new Map(
      runs
        .filter((run) => run?.turn_id)
        .map((run) => [run.turn_id, run]),
    );
    state.transcripts.set(
      conversationId,
      transcript.map((message) => ({
        id: message.id,
        role: message.role,
        turnId: message.turn_id || null,
        content: message.content,
        assets: message.assets || [],
        citations: [],
        approval: message.approval || null,
        proposedTool: message.approval?.tool_name || null,
        process: [],
        toolResult: message.approval?.result || null,
        agentRun:
          message.role === "assistant" && message.turn_id ? runsByTurn.get(message.turn_id) || null : null,
        loading: false,
      })),
    );
    pruneResolvedApprovalDrafts(state.transcripts.get(conversationId));
  } else {
    await refreshAgentRuns(conversationId);
    pruneResolvedApprovalDrafts(state.transcripts.get(conversationId));
  }
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
  const run = payload?.run || null;
  if (!run) {
    return null;
  }
  const stored = upsertAgentRun(conversationId, run);
  assistantMessage.agentRun = stored;
  return stored;
}

async function uploadAttachment(attachment) {
  const formData = new FormData();
  formData.append("file", attachment.file, attachment.displayName);
  formData.append("care_context", attachment.careContext);

  const response = await fetch("/v1/assets/upload", {
    method: "POST",
    body: formData,
  });

  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `Attachment upload failed with status ${response.status}`);
  }

  const payload = await response.json();
  return payload.asset;
}

async function uploadPendingAttachments() {
  if (!state.pendingAttachments.length) {
    return [];
  }

  updateStatus("thinking", "Uploading", "Saving attachments into the local workspace.");
  recordProcessEvent("upload", "Uploading attachments", "Saving files locally before analysis.");
  const uploadedAssets = [];
  for (const attachment of state.pendingAttachments) {
    uploadedAssets.push(await uploadAttachment(attachment));
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

async function submitTurn(prompt) {
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
  } else if (event.type === "tool.proposed") {
    if (!assistantMessage) {
      render();
      return;
    }
    assistantMessage.loading = true;
    syncRunFromEvent(event.conversation_id, assistantMessage, event.payload);
    assistantMessage.proposedTool = event.payload.tool_name;
    const detail = `Draft ready for ${approvalSurfaceNoun(event.payload.tool_name)} review.`;
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
  } else if (event.type === "approval.required") {
    if (!assistantMessage) {
      render();
      return;
    }
    assistantMessage.loading = false;
    syncRunFromEvent(event.conversation_id, assistantMessage, event.payload);
    const approvalPayload = { ...event.payload };
    delete approvalPayload.run;
    assistantMessage.approval = approvalPayload;
    state.approvals.set(approvalPayload.id, approvalPayload);
    const detail = "A durable action is ready for review and approval.";
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
  const approval = await requestJson(`/v1/approvals/${approvalId}/decisions`, {
    method: "POST",
    body: JSON.stringify({
      action,
      edited_payload: editedPayload,
    }),
  });

  clearApprovalDraft(approvalId);
  state.approvals.set(approvalId, approval);
  const messages = activeMessages();
  for (const message of messages) {
    if (message.approval && message.approval.id === approvalId) {
      message.approval = approval;
    }
  }
  if (state.activeConversationId) {
    await refreshAgentRuns(state.activeConversationId);
  }
  render();
}

function closeSidebar() {
  state.mobileSidebarOpen = false;
  elements.sidebar.classList.remove("is-open");
  elements.backdrop.classList.remove("is-open");
}

function openSidebar() {
  state.mobileSidebarOpen = true;
  elements.sidebar.classList.add("is-open");
  elements.backdrop.classList.add("is-open");
}

function toggleSidebar() {
  if (state.mobileSidebarOpen) {
    closeSidebar();
  } else {
    openSidebar();
  }
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
    });
  }
  render();
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
    await submitTurn(prompt);
    updateStatus("ready", "Ready", "Response complete.");
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
    clearPendingAttachments();
    closeCameraPanel();
    updateStatus("ready", "Ready", "Ready for a new conversation.");
    render();
    closeSidebar();
  });
  elements.promptInput.addEventListener("input", resizeComposer);
  elements.promptInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      elements.composer.requestSubmit();
    }
  });
  elements.sidebarToggle.addEventListener("click", toggleSidebar);
  elements.backdrop.addEventListener("click", closeSidebar);
  elements.statusButton.addEventListener("click", (event) => {
    event.stopPropagation();
    toggleStatusMenu();
  });
  document.addEventListener("click", (event) => {
    if (!elements.statusMenu.contains(event.target) && !elements.statusButton.contains(event.target)) {
      toggleStatusMenu(false);
    }
  });
  elements.attachmentButton.addEventListener("click", () => {
    elements.fileInput.click();
  });
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
