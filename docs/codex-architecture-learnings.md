# Codex Architecture Learnings

This document captures what this repository should learn from the upstream
[`openai/codex`](https://github.com/openai/codex) project without copying it
blindly.

The goal is not to recreate the cloud product feature-for-feature.

The goal is to adopt the parts of Codex that make it feel coherent:

- explicit state
- explicit workspace binding
- explicit permissions
- memory as a derived layer
- a clear seam between agent core and client surfaces

This repo is trying to build the local-first, multimodal version of that
discipline.

The living implementation status for these learnings is tracked in
[docs/codex-alignment-tracker.md](/Users/cheickdiakite/Codex/gemma-local-expert/docs/codex-alignment-tracker.md).

## Why Codex Matters

Codex is useful to study because it is not just a chat UI on top of tool calls.

Its public docs and open-source repo make a few design choices very clear:

- the canonical unit is not "just a transcript"; it is thread, turn, and item
- client surfaces are downstream of an app-server contract
- workspaces are explicit runtime objects, not vague context
- permissions are modeled separately from content collaboration
- memories are generated from prior work, not treated as the source of truth

Those choices are directly relevant to the current gaps in this repository.

## Core Codex Primitives

### 1. Thread, turn, item

Codex treats conversation state as a ledger-like model:

- thread
- turn
- item

That is a stronger model than "messages plus some side tables."

It means the system can reason about:

- what happened in the thread overall
- what policy applied to a specific turn
- which concrete items belong to that turn
- where approvals, tool calls, outputs, and edits attach

This is one of the biggest architectural lessons for this repository.

### 2. App-server seam

Codex has a clear app-server seam between agent runtime and clients.

That matters because:

- web, desktop, CLI, and future clients can share the same state model
- approvals and tool events become protocol events instead of UI-specific hacks
- client work can iterate without redefining agent state each time

This repository already has a local API, but the long-term direction should be
closer to a client-neutral evented seam than to a chat-only web API.

### 3. Per-turn policy

Codex exposes policy at the turn level, not just as a global app setting.

Examples include:

- current working directory
- sandbox mode
- writable roots
- approval policy
- model/runtime selection

That makes the runtime truthful and inspectable.

This repository should move in the same direction.

## Workspaces in Codex

The most important thing to understand is that Codex workspaces are not
"whatever the agent happens to remember."

They are concrete execution environments.

### What Codex means by workspace

In practice, Codex uses a combination of:

- thread-bound `cwd`
- explicit writable roots
- local or worktree-backed execution
- local environment setup for a project

The filesystem location and policy are explicit runtime inputs.

### Worktrees

Codex app worktrees are one of the strongest ideas to borrow.

They give background work a real isolated workspace instead of overloading the
foreground checkout.

Key properties:

- a thread can be associated with a worktree
- the same worktree can persist across time
- worktree-backed work is isolated from the user's current local checkout
- worktrees are a filesystem/runtime isolation primitive, not just a UI label

### Local environments

Codex also supports local-environment setup so a workspace is not just a folder
but a reproducible execution target.

That is a useful pattern for:

- dependency setup
- environment bootstrapping
- known good actions
- turning a project root into a repeatable agent workspace

### Subagents are not the workspace abstraction

This is a key point.

Subagents in Codex are not automatically new workspaces.

They are additional agent executions that inherit or use runtime policy unless
you explicitly give them a different environment.

That means:

- subagent != worktree
- subagent != new sandbox
- subagent != durable state boundary

For this repository, that is an important design rule:

> separate workspace isolation from agent orchestration

### Translation for this repository

The right local equivalent is:

- conversation thread: the user-facing continuity container
- turn: the execution unit with policy
- item: the durable record of outputs, approvals, evidence, and runs
- workspace binding: an explicit per-thread or per-turn filesystem context
- background workspace: optional isolated worktree/local clone for bounded agent runs

This is stronger than the current implicit model where workspace identity is
spread across settings, approvals, and run records.

## Memory in Codex

Codex memory is layered.

That is a very important lesson.

### 1. `AGENTS.md` is not memory

Codex treats `AGENTS.md` as durable instruction/configuration context.

It is discovered by scope, and more local files override broader ones.

That means:

- required repo rules live in `AGENTS.md`
- project conventions live in `AGENTS.md`
- generated memories do not replace explicit instruction files

This is the right split.

### 2. Generated memories are derived, not canonical

Codex generated memories:

- are off by default
- are created for eligible idle threads
- are stored locally
- skip active or short-lived sessions
- redact secrets
- are controlled with explicit config switches

That is a stronger pattern than "save lots of transcript and hope reranking
will solve it."

The important rule is:

> thread history is canonical; memory is a derived recall aid

### 3. Chronicle is opt-in multimodal memory

Chronicle adds another layer by generating memories from recent screen context.

That is interesting for this repository because we are explicitly building a
multimodal local assistant.

The key lessons are:

- it is optional
- it is privacy-sensitive
- it is sandboxed
- the generated memories are still local artifacts, not silent cloud state

### Translation for this repository

We should adopt the same layered view:

1. `AGENTS.md` and repo docs for durable explicit rules
2. canonical thread/turn/item ledger as source of truth
3. derived conversation memories from eligible completed/idle threads
4. optional richer multimodal memory later, with explicit privacy controls

This also reinforces something we have already learned here:

continuity failures are often foreground-selection failures, not "we need more
memory" failures.

## Permissions in Codex

Codex cleanly separates permissions from collaboration UX.

That is exactly where this repository has been weakest.

### Sandbox mode

Codex models technical execution risk using sandbox mode, such as:

- read-only
- workspace-write
- danger-full-access

This is about what the agent is technically allowed to touch.

### Approval policy

Codex separately models when it must stop and ask.

Examples include:

- on-request
- untrusted
- never
- more granular category-based policy

This is about when the user must explicitly approve behavior.

### Exec policy

Codex also has a real exec-policy rule system for commands:

- prefix rules
- allow / prompt / forbidden
- host executable metadata
- stricter result wins across matches

That is much stronger than scattered ad hoc approvals.

### What this means for our UX

The most important product lesson is:

> permissions are not the same thing as document collaboration

In this repository, we have repeatedly let pending drafts feel like permission
walls.

That is the wrong abstraction.

Permissions should primarily apply to:

- filesystem writes with lasting consequences
- network access
- leaving the sandbox
- risky command execution
- boundary-crossing tool calls

They should not be the dominant interaction pattern for:

- seeing a draft
- reading a draft
- editing a draft
- iterating on document content

That is why the inline canvas direction is the right next UX move.

## Canvas and Document Surface Lessons

Codex Canvas is useful to study because it treats the document as the primary
surface and chat as collaboration around it.

That is a much better model than:

- assistant message
- preview card
- hidden editor
- approval buttons

For this repository, the lesson is:

- use one document surface as the source of truth
- let chat issue instructions against that surface
- keep save/export actions secondary
- do not make "Edit" responsible for basic visibility

This does not mean we must copy the exact UI.

It does mean we should copy the interaction principle.

## Ours vs Codex

| Area | Codex pattern | Current state here | What we should do |
| --- | --- | --- | --- |
| Canonical state | thread / turn / item | conversation / message / approval / run tables | converge on an internal thread-turn-item ledger |
| Workspace model | explicit cwd + worktree + environment | workspace root plus bounded run state | add explicit workspace binding per thread/turn and isolated background workspaces |
| Memory | `AGENTS.md` + derived memories + optional Chronicle | `AGENTS.md`, continuity snapshot, derived memories, evidence memory | formalize thread-canonical vs memory-derived split |
| Permissions | sandbox mode + approval policy + execpolicy | approval gating plus engine policy | make turn policy explicit and separate security approvals from document editing |
| Client seam | app-server contract | local API, web-first contract | evolve toward a client-neutral event seam |
| Draft UX | document surface with collaboration around it | improving inline canvas, still chat-heavy | keep moving toward document-first canvas behavior |

## What We Should Adopt Now

### 1. Internal thread / turn / item ledger

Without changing the entire UI first, we should create a stronger internal state
model where items include things like:

- user message
- assistant message
- evidence packet
- approval request
- approval decision
- tool call
- tool result
- run step
- draft canvas
- compaction marker

That would reduce many current transcript/UI mismatches.

### 2. Explicit workspace binding

Each thread and turn should be able to say:

- current workspace id or root
- current cwd
- writable roots
- local profile
- whether execution is local, bounded background, or isolated background

This is especially important for future workspace agent hardening.

### 3. Turn policy object

This repository should move toward a typed turn policy that includes:

- workspace binding
- sandbox mode
- network policy
- approval mode
- active model/profile
- expected output shape

That will make the runtime easier to reason about and much easier to test.

### 4. Derived memory pipeline

We already have stronger continuity and memory than before.

The next step is not "save more."

It is to formalize:

- which threads are eligible for memory extraction
- when extraction runs
- what memory can override and what it cannot
- how canonical thread history and derived memory interact

### 5. Canvas separate from security approvals

We should continue to evolve pending drafts into a real canvas surface.

Security approvals should remain important, but they should be:

- subtle
- secondary
- tied to durable execution

not the primary interaction shell for reading and editing content.

## What We Should Not Copy Blindly

There are also things we should be careful not to copy mechanically.

### 1. Coding-first assumptions

Codex has strong coding and shell DNA.

This repository is broader:

- multimodal conversation
- field workflows
- documents
- local outputs
- workspace synthesis

We should borrow the state model, not narrow the product to coding tasks.

### 2. Cloud-first assumptions

This repository is intentionally local-first and offline-first.

Any Codex-inspired design needs to preserve:

- local processing
- local storage
- graceful low-memory fallback
- truthful capability display

### 3. Subagent overuse

Codex has subagents, but the right lesson is not "use more subagents."

For this repository, the better lesson is:

- keep one strong orchestrator
- use specialist routes where they clearly help
- use subagents only when they solve a real separation problem

### 4. Permission-heavy UX

Codex permissions are disciplined, but they are not meant to make ordinary
content editing feel bureaucratic.

We should strengthen security policy without turning every draft into a workflow
obstacle.

## Proposed Adoption Slices

### Slice 1: state model hardening

- introduce internal item ledger
- attach approvals and canvases to items and turns
- add explicit turn ownership for pending drafts

### Slice 2: workspace model

- add explicit workspace binding to thread/turn state
- formalize foreground vs background workspace runs
- add optional isolated background workspace support

### Slice 3: policy model

- add typed turn policy object
- separate content-edit flows from security approvals
- formalize sandbox/network/approval policy in one place

### Slice 4: memory model

- formalize derived-memory generation lifecycle
- define eligibility and consolidation rules
- preserve hard priority:
  - explicit referent
  - grounded evidence
  - workspace context
  - derived memory

### Slice 5: client seam

- evolve the local API toward a more item/event-driven contract
- reduce UI-specific logic hidden in transcript shape
- let multiple clients share the same state semantics

## Open Questions for This Repository

These are the main architecture questions worth answering next:

1. How much of the thread/turn/item model should be internal first vs public API?
2. Should workspace isolation use Git worktrees, local clones, or both?
3. What is the minimal turn-policy shape that meaningfully improves safety?
4. When should a thread become memory-eligible?
5. How should inline canvas and optional side-by-side canvas share the same draft state?

## Source References

Primary sources used for this comparison:

- [openai/codex repository](https://github.com/openai/codex)
- [Codex App Server](https://developers.openai.com/codex/app-server)
- [Codex Worktrees](https://developers.openai.com/codex/app/worktrees)
- [Codex Local environments](https://developers.openai.com/codex/app/local-environments)
- [Codex Subagents](https://developers.openai.com/codex/subagents)
- [Codex Memories](https://developers.openai.com/codex/memories)
- [Codex Chronicle](https://developers.openai.com/codex/memories/chronicle)
- [Codex AGENTS.md guide](https://developers.openai.com/codex/guides/agents-md)
- [Codex Config reference](https://developers.openai.com/codex/config-reference)
- [Codex execpolicy README](https://github.com/openai/codex/blob/main/codex-rs/execpolicy/README.md)

This document should be treated as a translation layer:

- what Codex appears to do
- what matters for this repository
- what we should adopt deliberately

not as an argument to make this project identical to Codex.
