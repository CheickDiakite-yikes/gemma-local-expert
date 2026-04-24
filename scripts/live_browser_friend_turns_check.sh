#!/usr/bin/env bash
set -euo pipefail

PORT="${FIELD_ASSISTANT_PORT:-8765}"
BASE_URL="${FIELD_ASSISTANT_BASE_URL:-http://127.0.0.1:${PORT}}"
OUTPUT_DIR="${FIELD_ASSISTANT_BROWSER_QA_OUTPUT_DIR:-output/playwright/friend-turns}"
START_SERVER="${FIELD_ASSISTANT_BROWSER_QA_START_SERVER:-1}"
HEADLESS="${FIELD_ASSISTANT_BROWSER_HEADLESS:-0}"
CODEX_HOME="${CODEX_HOME:-${HOME}/.codex}"
PWCLI="${PLAYWRIGHT_CLI:-${CODEX_HOME}/skills/playwright/scripts/playwright_cli.sh}"
SESSION_NAME="${FIELD_ASSISTANT_BROWSER_QA_SESSION:-faft$$${RANDOM}}"
TMP_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/field-assistant-browser-qa.XXXXXX")"
SERVER_PID=""
BROWSER_OPENED="0"

cleanup() {
  if [[ -n "${SERVER_PID}" ]]; then
    kill "${SERVER_PID}" >/dev/null 2>&1 || true
    wait "${SERVER_PID}" >/dev/null 2>&1 || true
  fi
  if [[ "${BROWSER_OPENED}" == "1" && -x "${PWCLI}" ]]; then
    "${PWCLI}" --session "${SESSION_NAME}" close >/dev/null 2>&1 || true
  fi
  if [[ "${FIELD_ASSISTANT_BROWSER_QA_KEEP_TMP:-0}" == "1" ]]; then
    echo "Kept browser QA temp root: ${TMP_ROOT}"
  else
    rm -rf "${TMP_ROOT}"
  fi
}
trap cleanup EXIT

wait_for_server() {
  for _ in {1..80}; do
    if curl -fsS "${BASE_URL}/v1/system/health" >/dev/null 2>&1; then
      return 0
    fi
    if [[ -n "${SERVER_PID}" ]] && ! kill -0 "${SERVER_PID}" >/dev/null 2>&1; then
      echo "Field Assistant server exited before becoming ready. Log:"
      sed -n '1,220p' "${OUTPUT_DIR}/server.log" || true
      return 1
    fi
    sleep 0.25
  done

  echo "Timed out waiting for ${BASE_URL}/v1/system/health. Log:"
  sed -n '1,220p' "${OUTPUT_DIR}/server.log" || true
  return 1
}

mkdir -p "${OUTPUT_DIR}"

if [[ "${START_SERVER}" == "1" ]]; then
  WORKSPACE_ROOT="${TMP_ROOT}/workspace"
  UPLOAD_ROOT="${TMP_ROOT}/uploads"
  mkdir -p "${WORKSPACE_ROOT}" "${UPLOAD_ROOT}"
  cat > "${WORKSPACE_ROOT}/field-assistant-architecture.md" <<'DOC'
Field Assistant architecture overview
Local-first assistant built on Gemma.
Uses bounded routing, retrieval, vision, approvals, and explicit draft ownership.
DOC
  cat > "${WORKSPACE_ROOT}/conversation-contracts.md" <<'DOC'
Conversation contract
Friend-like turns should be answered naturally without dragging active drafts back into the reply.
Pending draft canvases should remain available when the user returns to the work.
DOC

  FIELD_ASSISTANT_ENV="browser-qa" \
  FIELD_ASSISTANT_DB_PATH="${TMP_ROOT}/field-assistant.db" \
  FIELD_ASSISTANT_ASSET_STORAGE_DIR="${UPLOAD_ROOT}" \
  FIELD_ASSISTANT_WORKSPACE_ROOT="${WORKSPACE_ROOT}" \
  FIELD_ASSISTANT_ASSISTANT_BACKEND="mock" \
  FIELD_ASSISTANT_SPECIALIST_BACKEND="mock" \
  FIELD_ASSISTANT_TRACKING_BACKEND="mock" \
  FIELD_ASSISTANT_EMBEDDING_BACKEND="hash" \
  UV_CACHE_DIR="${FIELD_ASSISTANT_UV_CACHE_DIR:-${TMP_ROOT}/uv-cache}" \
    uv run uvicorn engine.api.app:create_app \
      --factory \
      --host 127.0.0.1 \
      --port "${PORT}" \
      > "${OUTPUT_DIR}/server.log" 2>&1 &
  SERVER_PID="$!"
  wait_for_server
fi

export FIELD_ASSISTANT_BASE_URL="${BASE_URL}"

if [[ ! -x "${PWCLI}" ]]; then
  echo "Missing Playwright CLI wrapper at ${PWCLI}."
  echo "Set PLAYWRIGHT_CLI to a playwright-cli compatible executable and retry."
  exit 1
fi

OPEN_ARGS=(--session "${SESSION_NAME}" open "${BASE_URL}/chat/")

if [[ ! "${HEADLESS}" =~ ^(1|true|yes)$ ]]; then
  OPEN_ARGS+=(--headed)
fi

"${PWCLI}" "${OPEN_ARGS[@]}" > "${OUTPUT_DIR}/open.log"
BROWSER_OPENED="1"
SCENARIO_LOG="${OUTPUT_DIR}/scenario.log"
"${PWCLI}" \
  --session "${SESSION_NAME}" \
  run-code \
  --filename scripts/live_browser_friend_turns_check.scenario.js \
  | tee "${SCENARIO_LOG}"

if grep -q "^### Error" "${SCENARIO_LOG}"; then
  exit 1
fi

echo "Live browser friend-turn canvas check: PASS"
