# Contributing to Field Assistant Engine

Thanks for contributing.

This repository is aiming for a high bar:

- local-first by default
- offline-first where practical
- bounded and auditable agent behavior
- one unified assistant surface, not a pile of separate bots
- clear separation between UI, orchestration, persistence, and model runtime

If your change makes the project more useful while preserving those constraints,
it is likely a good fit.

## First Principles

Contributions should preserve these invariants:

1. The engine owns persistence, routing, retrieval, approvals, and model
   selection.
2. UI clients must not write to SQLite directly.
3. Durable actions must remain explicit and inspectable.
4. Medical flows must remain gated and clearly separated from general chat.
5. Fallback behavior must be honest.
6. Local practicality matters as much as raw capability.

## Good Areas to Contribute

- retrieval quality and benchmark coverage
- improved ingestion and document understanding
- better local model adapters
- better low-memory behavior on Apple Silicon
- richer native macOS or iOS shell work
- camera and video UX
- accessibility improvements
- approval workflow polish
- API contract quality
- audit trail improvements
- local benchmarking and eval harnesses

## Before You Start

1. Read the root [README.md](README.md).
2. Review the architecture docs if your change touches core behavior:
   - [offline-field-assistant-v1-technical-architecture.md](offline-field-assistant-v1-technical-architecture.md)
   - [offline-field-assistant-v1-product-spec.md](offline-field-assistant-v1-product-spec.md)
3. Prefer discussing large architectural shifts before implementing them.

## Development Setup

### Install dependencies

```bash
uv sync
```

### Apply migrations

```bash
uv run python scripts/migrate.py
```

### Run the engine

```bash
uv run uvicorn engine.api.app:create_app --factory --reload
```

### Open the local chat shell

Open [http://127.0.0.1:8000/chat/](http://127.0.0.1:8000/chat/).

## Recommended Development Modes

### Low-memory mode

If you are working on UX, approvals, routing, or basic local flows, prefer the
safer profile:

```bash
bash scripts/run_low_memory_server.sh
```

### Full live local mode

If you are working on MLX inference paths and already have local compatible
model weights:

```bash
FIELD_ASSISTANT_ASSISTANT_BACKEND=mlx \
FIELD_ASSISTANT_EMBEDDING_BACKEND=mlx \
FIELD_ASSISTANT_SPECIALIST_BACKEND=auto \
uv run uvicorn engine.api.app:create_app --factory --reload
```

## Testing Expectations

If behavior changes, run the relevant checks.

### Baseline

```bash
uv run pytest
python3 -m compileall engine tests scripts
```

### Evals

```bash
uv run python scripts/run_local_eval.py routing
uv run python scripts/run_local_eval.py retrieval
```

### Smoke tests

Use targeted smoke scripts when your change affects the end-to-end flow:

```bash
uv run python scripts/smoke_chat.py --backend mock
uv run python scripts/smoke_tool_approval.py
uv run python scripts/smoke_asset_turn.py --care-context general
```

If your change affects video workflows, run the local video path you changed.
If your change affects a low-memory path, verify that path specifically.

## Documentation Expectations

If you change:

- routing behavior
- tool behavior
- safety boundaries
- environment variables
- client surfaces
- major workflows

then update the relevant docs in the same pull request.

At minimum, that usually means:

- the root [README.md](README.md)
- architecture docs if contracts changed
- smoke or eval docs if the verification path changed

## Coding Expectations

### Keep boundaries clean

- put durable writes in `engine/persistence`
- keep orchestration in `engine/orchestrator`
- keep route decisions in `engine/routing`
- keep backend-specific model logic in `engine/models`
- keep UI concerns in `apps/*`

### Prefer explicitness

- prefer typed payloads over loose dictionaries when practical
- prefer clear warnings to silent fallback
- prefer visible approval state to hidden action execution

### Avoid premature framework expansion

This repo does not need more abstraction just because abstraction is possible.
If a new layer does not clearly simplify the product, avoid it.

### Design for weak hardware

If your contribution increases memory pressure, startup cost, or simultaneous
model loading, document the tradeoff and provide a lighter path when possible.

## Pull Request Checklist

Before opening a PR, check all of these:

- the change matches the local-first and offline-first direction
- safety and approval boundaries still make sense
- tests or smoke coverage were run
- docs were updated if behavior changed
- the change does not silently bypass fallbacks or warnings
- UI changes remain compatible with mobile-sized layouts where relevant

## What Not to Do

Please avoid contributions that:

- make cloud dependency the hidden default
- turn the main UI into a collection of fragmented assistant modes
- add silent unsafe powers
- mix persistence logic into UI code
- hide degraded behavior behind polished wording
- overfit for benchmark demos while making real local use worse

## Reporting Issues

Good issues include:

- what you expected
- what happened
- whether you were in `mock`, low-memory, or full MLX mode
- what model/backend settings were used
- whether the problem affects text, retrieval, image, video, or tool flows
- screenshots or logs when helpful

## Architectural Changes

If you want to propose a bigger architectural shift, frame it in terms of:

- the user problem it solves
- the runtime cost
- the offline/local impact
- the safety impact
- what code boundary would change
- how it would be tested

This repository values coherent systems work over novelty for its own sake.

## Final Note

The best contributions make the assistant:

- more trustworthy
- more usable offline
- more testable
- more graceful on modest hardware
- more unified at the UX layer
- more explicit in the engine layer

That is the standard to build against.
