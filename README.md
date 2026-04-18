# Field Assistant Scaffold

This repository now contains the first executable scaffold for the local-first
Gemma field assistant described in the workspace research and architecture
documents.

Current scope:

- Python local engine with FastAPI entrypoints
- Typed request and response contracts
- Routing, policy, retrieval, audit, and orchestration seams
- SQLite persistence with migrations
- Chunked knowledge-pack ingestion
- Hybrid lexical plus embedding retrieval
- Sample eval fixtures for routing and retrieval
- Placeholder macOS app workspace for the future SwiftUI shell

This is not a production implementation yet. It is the build surface for:

- model adapters
- SQLite persistence
- MLX inference
- document ingestion
- approvals
- medical mode isolation
- export flows

Current retrieval note:

- the repository now persists chunk embeddings and uses hybrid search
- the default embedder is still a deterministic local hash-based fallback for
  fast deterministic tests
- a live `EmbeddingGemma` MLX adapter is now implemented and can auto-resolve a
  locally cached `google/embeddinggemma-300m` snapshot

Current assistant runtime note:

- the orchestrator now runs through a real assistant runtime boundary
- the default assistant backend is `mock` for deterministic local tests
- an `mlx` backend is wired and can auto-resolve known local Gemma caches such
  as `google/gemma-4-E4B-it`

Current multimodal note:

- image attachments now persist through the API, transcript, and web chat shell
- `PaliGemma` and `MedGemma` are wired as a specialist visual-analysis stage
- the default specialist backend is `auto`, which uses a locally cached MLX VLM
  model when available and falls back to explicit metadata-only warnings when it
  is not
- a live `PaliGemma` MLX path now works with
  `mlx-community/paligemma2-3b-mix-224-4bit`

## Repo layout

```text
apps/
  desktop-macos/
contracts/
  events/
  openapi/
docs/
engine/
  api/
  audit/
  config/
  contracts/
  models/
  orchestrator/
  persistence/
  policy/
  retrieval/
  routing/
  tools/
evals/
  retrieval/
  routing/
scripts/
tests/
```

## Quickstart

1. Install dependencies:

```bash
uv sync
```

2. Apply migrations:

```bash
uv run python scripts/migrate.py
```

3. Run the engine:

```bash
uv run uvicorn engine.api.app:create_app --factory --reload
```

4. Hit the health endpoint:

```bash
curl http://127.0.0.1:8000/v1/system/health
```

5. Run the starter evals:

```bash
uv run python scripts/run_local_eval.py routing
uv run python scripts/run_local_eval.py retrieval
```

6. Export the OpenAPI snapshot:

```bash
uv run python scripts/export_openapi.py
```

7. Run an end-to-end smoke turn:

```bash
uv run python scripts/smoke_chat.py --backend mock
```

To try the live MLX path once you have a compatible model available:

```bash
uv run python scripts/smoke_retrieval.py --backend mlx
uv run python scripts/smoke_chat.py --backend mlx --embedding-backend mlx --model-name gemma-4-e4b-it
```

If your laptop is unstable under the full `E4B + PaliGemma` stack, use the lower-memory field profile instead:

```bash
bash scripts/run_low_memory_server.sh
```

That profile keeps live chat on `gemma-4-e2b-it-4bit`, uses `tesseract` for text-heavy image specialist work, and avoids loading `PaliGemma` by default.

8. Run the approval and tool-execution smoke path:

```bash
uv run python scripts/smoke_tool_approval.py
```

9. Run an image-backed smoke turn:

```bash
uv run python scripts/smoke_asset_turn.py --care-context general
uv run python scripts/smoke_asset_turn.py \
  --care-context general \
  --specialist-backend mlx \
  --vision-model-source mlx-community/paligemma2-3b-mix-224-4bit
```

If you want to override the local cache auto-resolution, pass explicit sources:

```bash
uv run python scripts/smoke_chat.py \
  --backend mlx \
  --embedding-backend mlx \
  --assistant-model-source <model-path-or-repo> \
  --embedding-model-source <embedding-model-path-or-repo>
```

For multimodal specialist models, use:

```bash
FIELD_ASSISTANT_SPECIALIST_BACKEND=auto \
uv run uvicorn engine.api.app:create_app --factory --reload

FIELD_ASSISTANT_SPECIALIST_BACKEND=mlx \
FIELD_ASSISTANT_VISION_MODEL_SOURCE=mlx-community/paligemma2-3b-mix-224-4bit \
uv run uvicorn engine.api.app:create_app --factory --reload
```

For OCR-first low-memory testing, use:

```bash
FIELD_ASSISTANT_ASSISTANT_MODEL_NAME=gemma-4-e2b-it-4bit \
FIELD_ASSISTANT_SPECIALIST_BACKEND=ocr \
uv run uvicorn engine.api.app:create_app --factory --reload
```

## Current architecture choice

This scaffold follows the research conclusion already written in this workspace:

- one orchestrator
- explicit routing
- explicit policy checks
- bounded tool surface
- retrieval before specialist routing
- no swarm-first orchestration

Related docs:

- [Gemma Local Agent Architecture Brief](gemma-local-agent-architecture.md)
- [Offline Field Assistant v1 Product Spec](offline-field-assistant-v1-product-spec.md)
- [Offline Field Assistant v1 Technical Architecture](offline-field-assistant-v1-technical-architecture.md)
- [Gemma Local Expert Research Synthesis](gemma-local-expert-research-synthesis-2026-04-17.md)
