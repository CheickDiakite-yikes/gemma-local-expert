# Codex Alignment Tracker

This file is the working checklist for closing the gap between the current
Field Assistant Engine architecture and the parts of Codex worth adopting.

It is not a generic roadmap.

It is a comparison-and-adoption tracker with explicit status, acceptance
criteria, current evidence, and next missing slices.

## How To Use This Tracker

Use this file as the single place to answer:

- what have we already adopted?
- what is partially implemented but still weak?
- what is still missing?
- what should we build next?
- what proof do we actually have?

### Status legend

- `done`: implemented and validated enough to rely on as current architecture
- `partial`: real implementation exists, but the model/UI/runtime contract still has important gaps
- `missing`: not implemented yet in a meaningful way
- `deferred`: known target, intentionally not in the current slice

### Evidence standard

Do not mark an area `done` because the code "kind of has it."

For each area, try to keep all three forms of evidence:

- code artifact
- targeted test or eval
- live UX or runtime validation where relevant

## Current Snapshot

| Area | Status | What exists now | Biggest gap |
| --- | --- | --- | --- |
| Thread / turn / item state | partial | turn ids everywhere; internal turn record + item ledger exist and are now inspectable through API read paths | not yet the canonical public state contract for clients |
| Workspace binding | partial | workspace root exists; bounded workspace runs exist; turn policy now carries workspace binding; conversation state now persists thread-level workspace binding and fork lineage | no isolated background worktree model yet |
| Turn policy | partial | explicit turn policy now exists and is inspectable through turn state | still minimal and not yet the single source of truth for all permission decisions |
| Memory layering | partial | `AGENTS.md`, continuity snapshot, derived conversation memory, evidence memory, memory focus | no formal idle-thread memory lifecycle or eligibility rules |
| Permissions system | partial | engine policy + approval gating + bounded workspace root | not yet a full typed permission model comparable to Codex execpolicy + approval categories |
| Document/canvas UX | partial | inline canvas is replacing preview-plus-hidden-editor patterns | still not a true document-first surface with selection-aware edits |
| App-server style client seam | partial | current local API now exposes transcript, turns, items, approvals, and runs as explicit state surfaces | still too web-chat shaped and not yet item/event-first |
| Worktree-backed background work | missing | bounded workspace agent exists | no true isolated worktree/local clone system |
| Thread ops: fork/archive/rollback/compact | partial | delete, archive, conversation detail, and fork now exist | no rollback, compact, or steer model yet |

## Domain Checklists

## 1. Canonical State Model

### Goal

Move from "messages plus side tables" toward a real internal ledger:

- thread
- turn
- item

### Current status

`partial`

### Implemented

- conversation threads already exist
- `turn_id` already flows through the engine
- turn records now exist internally
- item records now exist internally for:
  - user messages
  - assistant messages
  - evidence packets
  - approvals
  - agent runs

### Missing

- item ledger is not yet the canonical read model for clients
- approvals/runs are still also reconstructed from legacy side-table joins
- no item-level streaming/event replay contract yet

### Acceptance criteria for `done`

- every meaningful turn artifact is represented as an item
- approvals and draft canvases can be reconstructed from item state
- at least one client surface can render from thread/turn/item state instead of message-special-case logic

### Next slice

- add item-backed read helpers for approvals/canvas ownership
- stop treating assistant message rows as the only anchor for active draft surfaces

## 2. Workspace Model

### Goal

Make workspace identity explicit runtime state, not just a setting.

### Current status

`partial`

### Implemented

- configured `workspace_root`
- bounded workspace agent runs scoped to workspace root
- explicit workspace binding in internal turn policy
- conversation state now persists thread-level workspace binding
- forked threads now retain workspace lineage

### Missing

- multiple named workspaces
- background isolated workspaces
- worktree-backed thread execution
- explicit per-thread workspace switching model

### Acceptance criteria for `done`

- a thread can declare its active workspace binding
- background agent work can run in an isolated workspace
- workspace identity is inspectable in runtime state and testable

### Next slice

- define `workspace_binding` object and thread-level association
- prototype isolated background workspace execution

## 3. Turn Policy

### Goal

Make execution policy a typed runtime object per turn.

### Current status

`partial`

### Implemented

- internal `TurnExecutionPolicy`
- turn policy is now visible through the turns API
- current fields:
  - workspace root
  - cwd
  - sandbox mode
  - network access
  - approval mode
  - active profile

### Missing

- network policy is currently static
- approval policy is still much simpler than Codex category-based approval controls
- some runtime decisions still depend on legacy route/tool heuristics instead of policy as the single source of truth

### Acceptance criteria for `done`

- policy is visible and testable for every turn
- policy is the source of truth for approval/sandbox behavior
- UI does not have to infer permission posture from draft shape

### Next slice

- expose turn policy through internal/state inspection APIs
- tie more approval and canvas logic directly to policy

## 4. Memory Layering

### Goal

Keep canonical thread state, derived memories, and explicit repo guidance separate.

### Current status

`partial`

### Implemented

- `AGENTS.md` and docs as explicit guidance
- continuity snapshot
- conversation memory entries
- evidence-backed memory reuse
- bounded `MemoryFocus`

### Missing

- explicit memory eligibility lifecycle for idle/completed threads
- formal compaction or consolidation process
- stronger distinction between short-horizon continuity vs durable memory extraction
- multimodal memory extension comparable to Chronicle is still future work

### Acceptance criteria for `done`

- memory generation has explicit lifecycle rules
- derived memory never overrides explicit referents or grounded evidence
- memory extraction is bounded, inspectable, and testable

### Next slice

- define thread memory eligibility rules
- add tracker-backed checklist for memory extraction readiness

## 5. Permissions and Security Boundaries

### Goal

Separate security approvals from content collaboration.

### Current status

`partial`

### Implemented

- approval-gated durable writes
- bounded workspace agent
- explicit medical-mode boundary
- truthful capability reporting
- internal turn policy with sandbox/approval fields

### Missing

- no richer command/exec policy comparable to Codex execpolicy
- no granular approval categories beyond current heuristics
- draft UX still leaks approval concepts into normal editing behavior in places

### Acceptance criteria for `done`

- risky execution policy is modeled independently from document editing UX
- the UI can distinguish "editable draft" from "security approval required"
- command or tool boundary rules are typed and centrally auditable

### Next slice

- formalize approval categories and risky capability classes
- continue demoting save-gating chrome from the draft-reading/editing experience

## 6. Document / Canvas Surface

### Goal

Make draft work feel like document collaboration, not a permission workflow.

### Current status

`partial`

### Implemented

- inline canvas direction exists
- pending draft is visible by default
- draft updates can re-anchor to the latest assistant turn

### Missing

- no selection-aware edits
- still textarea-first, not rich document-first
- chat still duplicates too much of the drafting flow
- toolbar and document surface are still heavier than they should be

### Acceptance criteria for `done`

- one primary draft surface
- chat acts on the document rather than duplicating it
- edit/read/save feel like document operations, not approval-card operations

### Next slice

- richer document rendering
- selection-aware rewrite operations
- optional side-by-side expanded canvas on desktop

## 7. Client-Neutral App-Server Seam

### Goal

Stop letting the web chat surface define the state model.

### Current status

`missing`

### Implemented

- local HTTP API
- streaming events for turn progress
- turns API
- items API
- archive API

### Missing

- item/event-first thread contract
- client-neutral state inspection model
- richer thread operations

### Acceptance criteria for `done`

- multiple clients can consume the same thread/turn/item semantics
- web-specific assumptions are not baked into state ownership

### Next slice

- define an internal item/event read model before attempting a broader API refactor

## 8. Thread Operations

### Goal

Support stronger thread lifecycle than create/delete/list.

### Current status

`partial`

### Implemented

- archive
- fork
- conversation detail/read path for thread lineage and workspace binding

### Missing

- rollback
- compact
- steer

### Why this matters

Codex feels stronger partly because thread operations are explicit.

This repo still handles many continuity problems by heuristic recovery inside a
single long thread.

### Next slice

- define what `turn steer` should mean in this product before building it
- add rollback/compact semantics on top of the new fork lineage

## 9. Evaluation Discipline

### Goal

Track progress with stronger standards than "tests green."

### Current status

`partial`

### Current standard we should keep using

For any important architecture or UX slice, try to maintain:

- `backend green`
- `transcript green`
- `live UX green`

### Missing

- tracker-linked eval evidence for each domain area
- explicit checklist of known live failures that are allowed vs blocked for release

### Next slice

- add links from future eval docs back into this tracker
- maintain a short "known live failures" block during active hardening

## Known High-Priority Gaps Right Now

- inline canvas is much better than the old approval card, but still not truly document-first
- workspace identity is now explicit per turn and persisted on the thread, but it is still not a full named-workspace/worktree model
- turn policy exists and is inspectable, but it is still minimal
- item ledger exists and is inspectable, but the client still mostly reconstructs state through older transcript conventions
- we still do not have isolated background workspaces/worktrees
- we still do not have richer thread operations like rollback/compact/steer

## Completed In This Slice

- added Codex architecture learnings doc
- added Codex alignment tracker
- added internal conversation turn records
- added internal conversation item ledger
- added explicit internal turn policy with workspace binding
- started treating turn policy and item state as architecture, not just implementation detail
- exposed turn and item inspection through the conversation API
- added thread archiving as the first real thread lifecycle operation
- added conversation detail and fork operations with thread lineage + workspace binding

## Operating Rule Going Forward

When we ship a meaningful architecture slice, update this file with:

- the new status
- what evidence exists now
- what is still missing
- the next smallest real slice

That is how we avoid losing track of what remains while the product keeps moving.
