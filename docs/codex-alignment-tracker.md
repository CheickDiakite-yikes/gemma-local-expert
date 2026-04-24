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
| Thread / turn / item state | partial | turn ids everywhere; internal turn record + item ledger exist, are inspectable through API read paths, now back approval ownership/read state, now feed a canonical conversation state surface, now surface item snapshots during assistant completion, tool proposal, tool completion, approval, and agent-run streaming milestones, and now persist dedicated `work_product` items for active drafts | streaming still mixes item snapshots with transcript-shaped local mutation instead of a full item/event replay contract |
| Workspace binding | partial | workspace root exists; bounded workspace runs exist; turn policy now carries workspace binding; conversation state now persists thread-level workspace binding and fork lineage | no isolated background worktree model yet |
| Turn policy | partial | explicit turn policy now exists and is inspectable through turn state, now carries typed permission classes, typed approval category, confirmation intent, and approval summary, and now cleanly distinguishes plain chat, durable writes, audited exports, workspace runs, and guarded medical specialist turns | policy is still not yet the single source of truth for all runtime permission decisions |
| Memory layering | partial | `AGENTS.md`, continuity snapshot, derived conversation memory, evidence memory, memory focus, and thread compaction summaries now exist | no formal idle-thread memory lifecycle or eligibility rules |
| Permissions system | partial | engine policy + approval gating + bounded workspace root, plus typed turn-level permission classes, typed approval categories, and approval metadata persisted on approval state, approval items, and tool descriptors | not yet a full typed permission model comparable to Codex execpolicy + approval categories |
| Document/canvas UX | partial | inline canvas is replacing preview-plus-hidden-editor patterns, and selected canvas text can now be shortened, rewritten, neutralized, or explained from chat through backend-persisted approval/work-product revisions plus `document_edit` item events | still textarea-first and not yet a full rich document surface |
| App-server style client seam | partial | current local API now exposes transcript, turns, items, approvals, runs, and a canonical `/state` surface; the web client now loads from that single state read on open/refresh, now consumes canonical item snapshots during key live stream events, now gets canonical approval item/run snapshots back from approval resolution, and now receives canonical tool proposal/result item snapshots too | still too web-chat shaped and not yet a true item/event replay protocol |
| Worktree-backed background work | missing | bounded workspace agent exists | no true isolated worktree/local clone system |
| Thread ops: fork/archive/rollback/compact | partial | delete, archive, conversation detail, fork, safe rollback, explicit compact, and explicit steer now exist; steer now influences workspace-agent planning and active run goals, and compaction summaries now get promoted more strongly when bounded history drops older topic cues | compact and steer still need richer live control semantics and stronger pruning/replay behavior |

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
  - tool proposals
  - tool results
  - approvals
  - agent runs
- approval items now carry full approval snapshots
- transcript approval ownership is now rehydrated from approval items instead of only from approval table joins
- public `ConversationState` now exposes conversation, messages, turns, items, and runs in one read model
- the web chat now opens and refreshes conversations from that canonical `/state` surface instead of stitching together separate messages/runs/items fetches
- assistant completion, approval-required, and agent-run status stream events now carry canonical item snapshots
- tool proposal and direct tool completion stream events now carry canonical item snapshots too
- the web chat now merges those item snapshots into live state instead of inventing local approval items during streaming
- approval decisions now return canonical approval item snapshots and run snapshots too, so the client can merge resolved state before the next full `/state` reconciliation
- active draft canvases now have dedicated `work_product` items persisted alongside approval lifecycle changes
- the web chat now hydrates active draft/canvas state from `work_product` items first, with approval rows as compatibility fallback
- CLI headless smokes now assert these same state contracts across tool approvals, workspace draft refinement, thread controls, long mixed conversation recall, and canonical `work_product` ownership
- live browser QA now verifies that active draft/canvas state stays stable through friend-like supportive detours, explicit task pivots, and return-to-draft turns

### Missing

- streaming/live-update paths are now more item-first, but still not a full item/event replay contract
- no item-level streaming/event replay contract yet

### Acceptance criteria for `done`

- every meaningful turn artifact is represented as an item
- approvals and draft canvases can be reconstructed from item state
- at least one client surface can render from thread/turn/item state instead of message-special-case logic

### Next slice

- keep moving the client toward a single item/event replay model for active work-product state
- reduce the remaining transcript-shaped local mutation during streaming

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
  - approval category
  - active profile
  - typed permission classes
  - requires-confirmation flag
  - approval summary

### Missing

- network policy is currently static
- approval policy is richer now, but approval execution still is not fully driven from stored turn policy
- some runtime decisions still depend on legacy route/tool heuristics instead of policy as the single source of truth

### Acceptance criteria for `done`

- policy is visible and testable for every turn
- policy is the source of truth for approval/sandbox behavior
- UI does not have to infer permission posture from draft shape

### Next slice

- keep expanding turn policy until it is the real source of truth for runtime permission posture
- tie more approval execution and canvas logic directly to stored policy/approval metadata instead of route heuristics

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
- explicit turn-adaptation classification for casual detours, true task pivots, and returns to the foreground anchor
- thread compaction summaries that can feed future continuity snapshots

### Missing

- explicit memory eligibility lifecycle for idle/completed threads
- formal idle-thread memory eligibility and consolidation process
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
- typed turn-level permission classes and confirmation intent
- typed approval categories on tool descriptors, approval state, and approval items

### Missing

- no richer command/exec policy comparable to Codex execpolicy
- no granular command/exec approval controls beyond current tool and workflow categories
- draft UX still leaks approval concepts into normal editing behavior in places

### Acceptance criteria for `done`

- risky execution policy is modeled independently from document editing UX
- the UI can distinguish "editable draft" from "security approval required"
- command or tool boundary rules are typed and centrally auditable

### Next slice

- formalize richer approval categories and risky capability classes on top of the new typed turn policy
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
- selected canvas text can be captured in the browser and sent as turn metadata
- selected canvas edits now update pending approval/work-product state on the backend instead of only mutating local UI state
- selected canvas edits now emit a dedicated `document_edit` item and `document.edited` stream event with before/after text and visible-content snapshots
- the canvas now renders a compact edit-history strip from recent `document_edit` items
- the visible canvas keeps save/export approval separate from ordinary draft edits

### Missing

- still textarea-first, not rich document-first
- selection-aware edits are deterministic document operations, not model-backed editing yet
- document-edit history is visible but not yet interactive: no inspect drawer, restore action, or per-edit approval controls
- toolbar and document surface are still heavier than they should be

### Acceptance criteria for `done`

- one primary draft surface
- chat acts on the document rather than duplicating it
- edit/read/save feel like document operations, not approval-card operations

### Next slice

- richer document rendering
- model-backed selection-aware rewrite operations
- optional side-by-side expanded canvas on desktop

## 7. Client-Neutral App-Server Seam

### Goal

Stop letting the web chat surface define the state model.

### Current status

`partial`

### Implemented

- local HTTP API
- streaming events for turn progress
- turns API
- items API
- archive API
- canonical `GET /v1/conversations/{conversation_id}/state`
- web chat conversation load/refresh now consumes that state surface directly
- key live stream milestones now carry canonical item snapshots for assistant messages, approvals, and agent runs

### Missing

- full item/event-first thread contract
- richer thread operations
- streaming/live updates still merge canonical items with transcript-shaped local mutation

### Acceptance criteria for `done`

- multiple clients can consume the same thread/turn/item semantics
- web-specific assumptions are not baked into state ownership

### Next slice

- keep collapsing live-update ownership toward items instead of ad hoc message mutation
- make one more client path consume the same state semantics without web-specific assumptions

## 8. Thread Operations

### Goal

Support stronger thread lifecycle than create/delete/list.

### Current status

`partial`

### Implemented

- archive
- fork
- safe rollback built on lineage plus source-thread archiving
- explicit compact operation that writes a compaction marker into thread state
- explicit steer operation that writes active thread guidance into thread state
- conversation detail/read path for thread lineage and workspace binding
- steer now influences active workspace-agent planning and stored run goals
- compaction summaries now get promoted into continuity more aggressively when recent topic cues are weak

### Missing

- richer live control semantics for steer during active streaming/runs
- compaction-aware pruning/selection beyond the current summary note

### Why this matters

Codex feels stronger partly because thread operations are explicit.

This repo still handles many continuity problems by heuristic recovery inside a
single long thread.

### Next slice

- keep extending steer into richer active-run control beyond the current workspace-agent path
- push compaction markers deeper into pruning/replay behavior beyond the current summary promotion

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

For state and continuity work, we should also keep a fourth proof:

- `CLI headless green`
- `live browser-shaped green`

That means the smoke harnesses fail hard on broken item ownership, approval
categories, thread controls, or long-horizon continuity instead of only dumping
logs for manual reading.

The new browser-shaped proof is especially important for draft/canvas work:
headless API tests can prove the transcript contract, but they cannot prove the
visible canvas stayed editable, preserved local edits, and let the user return
to the foreground draft after a normal human detour.

### Missing

- tracker-linked eval evidence for each domain area
- explicit checklist of known live failures that are allowed vs blocked for release

### Next slice

- add links from future eval docs back into this tracker
- maintain a short "known live failures" block during active hardening
- keep adding browser-shaped checks for product-critical flows where DOM state,
  visible draft state, scroll, or responsive layout matter

## Known High-Priority Gaps Right Now

- inline canvas is much better than the old approval card, but still not truly document-first
- active draft continuity is now stronger, and selection-aware local canvas edits exist, but richer model-backed document editing is still next
- workspace identity is now explicit per turn and persisted on the thread, but it is still not a full named-workspace/worktree model
- turn policy exists and is inspectable, but it is still minimal
- item ledger exists, is inspectable, now backs approval ownership, and now feeds a canonical `/state` surface, but streaming/live-update paths still lean on transcript-era heuristics
- we still do not have isolated background workspaces/worktrees
- compact and steer now exist, but they are still backend-first thread controls rather than polished product operations

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
- moved approval/canvas ownership onto approval item snapshots in the persistence + web client path
- added a canonical conversation `/state` surface and switched the web conversation open/refresh path to use it
- added a safe rollback operation that restores an earlier turn into a replacement thread and archives the source thread
- added explicit compact and steer thread operations and fed them into the continuity snapshot/prompting path
- upgraded the CLI smoke harnesses so they now assert canonical item snapshots, grounded workspace draft refinement, thread protocol controls, and deep mixed conversation continuity
- added explicit turn-adaptation classification for casual detours, true task pivots, and returns to a foreground anchor
- added a live browser-shaped draft/canvas validation harness for friend-like conversational turns during active canvas work
- made mock/browser QA boot without eager MLX/Metal initialization by lazily importing MLX runtimes only when selected
- added first-pass selection-aware inline canvas edits that rewrite visible selected text locally from chat commands
- moved selection-aware canvas edits through the turn API so the backend persists updated approval/work-product snapshots and transcript replies
- added `document_edit` items and `document.edited` stream events for selected canvas edit replay/audit state

## Last Thread Analysis: Active Draft / Friend-Like Turns

The last thread strengthened a very specific product contract:

- a user can have an active draft/canvas open
- they can briefly talk like a person, ask for reassurance, or pivot to a different conceptual question
- the assistant should answer that turn naturally instead of dragging the draft back into the reply
- the draft/canvas should still be visible, editable, and available when the user returns

That is a product-level distinction, not just a memory heuristic. It separates
foreground ownership from response style: the system preserves the active work
object while allowing the conversation to breathe.

### What This Proves Now

- continuity can preserve a foreground draft without forcing every reply to be about that draft
- task pivots can suppress stale draft/media context without destroying the active anchor
- local canvas edits survive the detour in the real browser surface
- return-to-draft language still resolves back to the pending work product

### Product Implication

The next build slice should move from "the assistant remembers the draft" to
"the assistant can operate on the draft like a document." That means the next
highest-leverage UX work is selection-aware canvas editing and document-first
draft actions, not another broad memory pass.

### Completed Follow-On Slice

- add selection capture in the inline canvas
- expose small document actions such as rewrite selection, shorten selection,
  make selection more neutral, and explain selection
- send selected-canvas edit context through the turn API instead of treating it as a local-only UI shortcut
- persist the revised pending draft through approval/work-product item snapshots
- persist a dedicated document-edit event for the selected range, action, before text, after text, and visible draft before/after
- keep approvals focused on durable save/export, not ordinary draft reading or editing
- add a browser-shaped validation that selects text in the canvas, sends a chat
  edit command, verifies the visible document changes in place, and confirms a
  `document_edit` item exists through the live API

### Next Slice After That

- move selection-aware edits from deterministic local transforms to model-backed
  draft operations with a grounded edit preview
- make document-edit history interactive so users can inspect or restore recent edits
- keep the visible canvas as the source of truth while streaming catches up to
  a fuller item/event replay model

### Gaps Noted After Live Testing

- the live browser path now proves visual canvas preservation, selected-text editing, visible edit history, and backend `document_edit` item creation
- edit history is now visible in the canvas, but it is read-only and compact rather than a full revision inspector
- deterministic edit actions are useful for smoke coverage, but model-backed rewrites still need grounded preview/validation
- `document_edit` currently covers selected canvas mutations, not arbitrary manual typing or title edits
- browser automation for text selection should keep dispatching human-like select, mouse, and key events because a bare programmatic range update can miss the canvas selection hint path

## Operating Rule Going Forward

When we ship a meaningful architecture slice, update this file with:

- the new status
- what evidence exists now
- what is still missing
- the next smallest real slice

That is how we avoid losing track of what remains while the product keeps moving.
