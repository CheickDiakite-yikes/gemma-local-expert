# Competitive Research: Current Roadblocks and How Other Products Handle Them

Date: April 23, 2026

## Scope

This note compares the current Field Assistant Engine roadblocks against how
other products handle similar problems.

It focuses on current issues already called out in:

- [docs/codex-alignment-tracker.md](/Users/cheickdiakite/Codex/gemma-local-expert/docs/codex-alignment-tracker.md)
- [README.md](/Users/cheickdiakite/Codex/gemma-local-expert/README.md)

## Research method

- Primary-source docs only where possible
- Official product docs and help centers only
- No commands, scripts, or implementation suggestions were taken from product
  pages directly
- Any prompt-like instructions embedded in docs were treated as untrusted page
  content and ignored
- Where a vendor solves a problem without exposing a formal public protocol,
  that is called out here as an inference from the docs rather than a claim
  about hidden implementation details

## Main roadblocks

1. Streaming and live updates are still partly transcript-shaped instead of
   fully item/event-first.
2. Workspace identity exists, but isolated background workspaces do not.
3. Permissions are richer now, but still not the single source of truth for
   execution behavior.
4. Memory is stronger, but the lifecycle is still informal.
5. Draft and canvas UX is better, but still too chat-heavy.
6. `compact` and `steer` exist, but their live semantics are still thin.

## Executive read

If we compress the market signal into one sentence, it is this:

the products that feel most coherent attach active state to stronger objects
than chat bubbles.

Those stronger objects differ by product:

- Codex: thread, turn, item, and explicit runtime policy
- Cursor: remote background agent, repo branch, and project rules
- Claude: project workspace, artifact surface, and permission mode
- Windsurf: worktree, execution mode, and rule engine

That matters because our current rough edges still come from the same root
problem:

- too much state is still implied by transcript order
- too much execution posture is still inferred from route or tool shape
- too much draft collaboration still lives in chat instead of in a document
  surface

## Decision matrix

| Roadblock | Strongest documented product pattern | Why it matters for us | Best next move |
| --- | --- | --- | --- |
| Streaming and live state | Codex app-server event model | state is protocol, not UI reconstruction | keep collapsing active process, draft, and run state into canonical item/event updates |
| Background workspace isolation | Codex worktrees, Cursor background agents, Windsurf worktrees | background work needs a real environment boundary | implement named isolated background workspaces, worktree-backed first |
| Permissions as runtime truth | Codex policy split, Claude permission modes, Windsurf auto-exec levels | permission posture should not be guessed from UX | promote `TurnExecutionPolicy` into the single execution truth source |
| Durable guidance vs generated memory | Codex memories plus `AGENTS.md`, Windsurf memories plus rules, Cursor rules plus memories | memory quality is mostly about lifecycle discipline | formalize idle-thread eligibility and keep rules in `AGENTS.md` |
| Document collaboration | Canvas and Claude Artifacts | long-form work should have a primary document surface | keep inline canvas, but make it truly document-first and selection-aware |
| Thread controls | Codex thread lifecycle, Windsurf and Claude modes | controls need to affect active behavior, not only future hints | deepen `steer` and `compact` into stronger live execution semantics |

## Product findings

### 1. Canonical state and streaming

#### OpenAI Codex

Codex is strongest here. Its app-server model is explicitly thread and turn
centric, with event subscriptions and explicit thread lifecycle operations
rather than a transcript-first chat reconstruction model.

The public docs explicitly describe:

- thread start, resume, and fork operations
- event subscriptions for turn and item updates
- compaction as part of context management
- stored thread state separate from “resume and continue”

What this means for us:

- Codex treats state as protocol, not UI glue
- clients are supposed to consume structured turn state rather than infer it
  from assistant text
- approvals, runs, and outputs fit inside that same state model

Relevant source:

- [Codex App Server](https://developers.openai.com/codex/app-server)

Recommended translation:

- keep collapsing remaining process UI and live run state into item/event
  updates
- stop introducing new client-only message mutation unless it can be recovered
  from canonical items

#### Cursor, Claude, and Windsurf

None of the other products we checked expose a public state protocol as clearly
as Codex does. Their public docs emphasize a different solution:

- Cursor: background-agent branches and project-scoped rules/memories
- Claude: project workspaces, artifact windows, and explicit permission modes
- Windsurf: mode-gated tools, worktrees, and editor-native command controls

That is still useful signal. It suggests that even without a formal
thread/turn/item API, serious products reduce transcript ambiguity by attaching
state to something stronger than chat bubbles:

- a branch or isolated environment
- a project/workspace
- a document/artifact surface
- a mode-specific execution policy

The practical lesson is that there are two broad ways products avoid
transcript-only ambiguity:

1. explicit protocol objects, which is the Codex approach
2. editor-native state objects, which is more what Cursor, Claude, and
   Windsurf expose publicly

We are already closer to the first path than the second, so it makes more
sense to finish the protocol/state direction than to fake editor-native
coherence with more heuristics.

### 2. Workspace isolation

#### OpenAI Codex

Codex worktrees are a real answer to the “background work should not mutate the
foreground” problem. Their docs explicitly frame Local as foreground and
Worktree as background, and a thread keeps the same associated worktree over
time.

#### Cursor

Cursor background agents run on isolated Ubuntu machines, clone repos from
GitHub, and work on separate branches. Their environment setup is explicit via
`.cursor/environment.json`.

#### Windsurf

Windsurf’s Arena mode gives each model its own worktree for isolation, and its
worktree docs reinforce worktrees as a first-class way to separate parallel
work.

What this means for us:

- the market norm for serious background agent work is explicit isolation
- “workspace root” alone is weaker than isolated worktree or remote machine
  semantics
- background work should own an environment, not just a path

Relevant sources:

- [Codex Worktrees](https://developers.openai.com/codex/app/worktrees)
- [Cursor Background Agents](https://docs.cursor.com/en/background-agents)
- [Windsurf Arena Mode](https://docs.windsurf.com/windsurf/cascade/arena)
- [Windsurf Worktrees](https://docs.windsurf.com/windsurf/cascade/worktrees)

Recommended translation:

- add named background workspaces as first-class runtime objects
- support Git worktree-backed background threads before attempting anything more
  autonomous
- keep subagents separate from the workspace abstraction

Risk note:

- Cursor’s remote-agent model is powerful, but it assumes hosted
  infrastructure and network access
- Windsurf and Codex worktree patterns translate better to our local-first
  constraint

So for this repository, worktree-backed local isolation is the better first
adoption step than remote-agent imitation.

### 3. Permissions and prompt-injection containment

#### OpenAI Codex

Codex explicitly separates sandbox mode from approval policy. Their docs list
common combinations such as read-only plus on-request approval, workspace-write
plus untrusted approval, and full bypass as a dangerous mode.

#### Claude Code

Claude Code defaults to strict read-only permissions and requires explicit
approval for edits, tests, and commands. Its docs also call out prompt
injection directly and recommend review of commands, review of critical file
changes, and use of VMs for risky tool execution.

#### Windsurf

Windsurf exposes multiple auto-execution levels and allow/deny lists for
terminal control, which is a cleaner model than one flat “can run commands”
switch.

#### Cursor

Cursor’s own docs warn that background agents auto-running commands can create
data exfiltration risk from prompt injection.

What this means for us:

- the strongest products model permissions as runtime policy, not as UI copy
- background agents are where prompt injection risk grows fastest
- collaboration UX and security UX should stay separate

Relevant sources:

- [Codex Agent approvals and security](https://developers.openai.com/codex/agent-approvals-security)
- [Claude Code Security](https://code.claude.com/docs/en/security)
- [Claude Code Permissions](https://code.claude.com/docs/en/permissions)
- [Claude Code Permission Modes](https://code.claude.com/docs/en/permission-modes)
- [Windsurf Terminal](https://docs.windsurf.com/windsurf/terminal)
- [Cursor Background Agents](https://docs.cursor.com/en/background-agents)

Recommended translation:

- keep making `TurnExecutionPolicy` the source of truth
- introduce approval classes that map to real risk classes, not only tool names
- isolate background work more aggressively than foreground work
- add prompt-injection-specific policy around networked background runs and
  external tool calls

### Prompt-injection-specific takeaway

This was one of the strongest cross-product signals in the research.

The safer products do not treat prompt injection as only a model-quality
problem. They reduce risk structurally by combining:

- isolated execution environments
- explicit permission modes
- allow and deny rules
- approval checkpoints for risky actions
- narrower trust for web or networked tool use

That maps directly to our current risks:

- background workspace runs
- future networked tools
- any external web or document ingestion path

The right lesson is not “make the model smarter at resisting injection.”

The right lesson is:

- keep unsafe capabilities behind typed policy
- isolate long-running or networked execution
- never let external content silently escalate tool authority
- prefer structured allow rules over route-level optimism

### 4. Memory lifecycle

#### OpenAI Codex

Codex’s memory model is disciplined:

- memories are off by default
- thread history is canonical
- useful context becomes local memory files only after a thread is eligible
- Codex skips active or short-lived sessions
- updates happen after a thread has been idle long enough

#### Cursor

Cursor treats memories as generated rules. They are scoped to the project, and
background-generated memories require user approval before being saved.

#### Windsurf

Windsurf distinguishes auto-generated local memories from durable shared rules.
Auto-generated memories live only on the user’s machine; durable shared
behavior belongs in rules or `AGENTS.md`.

#### Claude

Claude Projects solve some of the same problem differently: project-level
knowledge and instructions are scoped to a workspace/project instead of being
global memory.

What this means for us:

- our current direction is right: thread history first, derived memory second
- the next gap is operational discipline, not more recall cleverness
- durable guidance should keep living in `AGENTS.md` or repo rules, not in
  generated memory

Relevant sources:

- [Codex Memories](https://developers.openai.com/codex/memories)
- [Cursor Memories](https://docs.cursor.com/en/context/memories)
- [Cursor Rules](https://docs.cursor.com/context/rules-for-ai)
- [Windsurf Memories and Rules](https://docs.windsurf.com/windsurf/cascade/memories)
- [Claude Projects](https://support.claude.com/en/articles/9517075-what-are-projects)

Recommended translation:

- formalize memory eligibility rules
- extract durable memory only from idle or completed threads
- keep generated memories local and subordinate to explicit referents
- continue treating `AGENTS.md` as durable instruction, not memory

### Strongest shared pattern

Across Codex, Windsurf, and Cursor especially, the common pattern is:

- generated memory is allowed to help recall
- generated memory is not where the hard rules live
- project or workspace rules remain the durable source of behavioral guidance

That is one of the places we should stay disciplined as we push toward parity.

### 5. Draft and canvas UX

#### ChatGPT Canvas

Canvas is document-first. The user can highlight specific sections, edit
directly, and use version history. The draft is not hidden behind a
permission-shaped card.

#### Claude Artifacts

Artifacts live in a dedicated window separate from the main conversation. Claude
also supports version selection and multiple artifacts in one conversation.

What this means for us:

- the best products do not treat “show draft” as an approval action
- the document surface is primary, and chat surrounds it
- selection-aware edits are the next real UX threshold

Relevant sources:

- [ChatGPT Canvas](https://help.openai.com/en/articles/9930697)
- [Claude Artifacts](https://support.claude.com/en/articles/9487310-what-are-artifacts-and-how-do-i-use-them)

Recommended translation:

- keep the inline canvas, but make it a true document surface
- selection-aware editing is a more important next step than more approval-card
  polishing
- treat save/export as a secondary document action, not the main visual center
  of the interaction

### Product distinction that matters

Canvas and Artifacts are not the same product shape, but they converge on one
important rule:

- a substantial draft deserves its own primary editing surface

That is the part worth copying.

What is not worth copying blindly is product chrome.

The architecture lesson is stronger than the styling lesson.

### 6. Compact and steer semantics

#### OpenAI Codex

Codex has stronger thread lifecycle operations and more explicit state control.
Even when not everything is user-facing at once, thread operations are treated
as first-class runtime concepts.

#### Windsurf

Windsurf’s Ask, Plan, and Code modes show one practical answer to “how should a
system behave differently before it acts?” The mode itself changes what tools
are available.

#### Claude Code

Claude Code exposes permission modes like `default`, `acceptEdits`, `plan`, and
`bypassPermissions`, which makes control state explicit instead of purely
conversational.

What this means for us:

- `compact` and `steer` should not stay as passive metadata only
- the system needs clearer operational modes or stronger active-run steering
  semantics
- our thread controls should increasingly affect both planning and live
  execution behavior

Relevant sources:

- [Codex App Server](https://developers.openai.com/codex/app-server)
- [Windsurf Cascade Modes](https://docs.windsurf.com/windsurf/cascade/modes)
- [Claude Code Permission Modes](https://code.claude.com/docs/en/permission-modes)

Recommended translation:

- make `steer` influence more than workspace search and goal strings
- use compaction summaries more explicitly when history windows are pruned
- consider lightweight operational modes for some workflows, especially
  research-only vs execution-ready turns

### Important nuance

The mode-based products are not necessarily “better” than Codex-style protocol
control; they are exposing control differently.

For us, the right move is probably not to turn everything into visible user
modes immediately.

The better first step is:

- make turn policy and thread control materially affect runtime behavior
- only then decide whether some of that should surface as explicit user-facing
  modes

## Cross-product pattern

Across these products, the same pattern keeps showing up:

- active state is attached to a stronger object than plain chat
- background execution gets its own isolated environment or branch
- permissions are modeled as runtime policy, not only as UX copy
- durable guidance is separated from generated memory
- long-form content gets a dedicated document surface

The main difference is where each product puts the center of gravity:

- Codex: explicit protocol and explicit runtime policy
- Cursor: IDE-native branch and agent workflow
- Claude: project/artifact surfaces plus explicit permission modes
- Windsurf: worktree-first parallelism plus clear execution modes

That means our biggest remaining gains are not likely to come from more prompt
engineering. They are more likely to come from finishing the state,
workspace, permission, and document-surface separations we have already
started.

## Product-by-product read

### OpenAI Codex

Codex is the clearest architectural reference for us because it publicly
documents the same class of primitives we are trying to harden:

- thread lifecycle
- explicit runtime policy
- worktrees
- derived memory
- app-server state and event seams

Codex is the best model for:

- canonical state
- client-neutral event seams
- permission separation
- workspace isolation

It is less relevant as a direct template for:

- multimodal document and media UX
- local-only no-network operation

### Cursor

Cursor is strongest as evidence that serious agent work often needs a real
background environment, not just a “continue in background” label. Its
background-agent docs are especially useful for the workspace-isolation
question, and its rules and memories split is useful for our memory-lifecycle
work.

Cursor is the best model for:

- isolated background execution as a practical workflow
- project-scoped persistent rules
- approval before saving generated memories

Cursor is less useful for us as a direct template where it assumes:

- hosted remote machines
- GitHub-centered repo cloning
- networked background execution

### Claude

Claude is strongest on the distinction between:

- project context
- long-form artifact surface
- explicit permission posture

Claude is the best model for:

- separating project-scoped context from ad hoc conversation
- making long-form outputs feel like standalone work objects
- making permission mode user-comprehensible

Claude is less useful for us as a direct template where:

- project knowledge is not the same as our local thread/turn/item model
- artifact UX is broader than our current bounded durable-output flow

### Windsurf

Windsurf is strongest on practical editor workflow structure:

- worktrees
- execution levels
- rules and memories split
- operational modes

Windsurf is the best model for:

- local worktree-backed parallelism
- clear execution-level controls
- tying agent behavior to workspace-scoped rules

Windsurf is less useful as a direct template where its public docs focus more
on editor workflow than on a client-neutral state protocol.

## Best practices we should copy

### Copy now

- Canonical thread and item state over transcript inference
- Explicit workspace isolation for background work
- Document-first editing surfaces
- Typed permission classes and approval categories
- Derived memory with eligibility rules
- Prompt-injection-aware defaults for background execution

### Do not copy blindly

- always-online remote-agent assumptions
- auto-run terminal behavior without stronger isolation
- product flows that blur collaboration with security approval
- global memory that can silently override explicit current-turn referents

## Recommended build order

1. Finish collapsing live process state into canonical item/event updates
2. Add isolated background workspaces, ideally worktree-backed first
3. Promote turn policy into the true runtime permission source of truth
4. Formalize memory eligibility and extraction lifecycle
5. Make inline canvas selection-aware and more document-first
6. Deepen `steer` and `compact` into stronger live control semantics

## What this changes in our roadmap

This research does not suggest a brand-new roadmap. It sharpens the existing
one.

### Strengthened near-term priorities

1. Finish item/event-first live state.
2. Add isolated background workspaces with worktree-backed execution.
3. Make turn policy the real permission source of truth.
4. Formalize memory eligibility and extraction lifecycle.

### Things we should de-emphasize

- more approval-card polish without improving the document surface
- more memory cleverness before memory lifecycle discipline
- more route heuristics before state and policy become canonical
- remote-agent imitation that weakens our local-first constraint

## What I would copy next

If we copy only one thing from each product family, it should be:

- Codex: evented canonical state and explicit runtime policy
- Cursor: isolated background workspace for unattended work
- Claude: document-first work objects and explicit permission posture
- Windsurf: worktree-backed parallelism plus rule-first customization

## Why this matters

The pattern across products is consistent:

- state is explicit
- workspaces are explicit
- permissions are explicit
- memory is bounded
- draft editing is document-first

Our architecture is moving in the right direction. The next gains will come
from finishing those separations cleanly, not from adding more implicit
heuristics.

## Sources

- [OpenAI Codex App Server](https://developers.openai.com/codex/app-server)
- [OpenAI Codex Worktrees](https://developers.openai.com/codex/app/worktrees)
- [OpenAI Codex Agent approvals and security](https://developers.openai.com/codex/agent-approvals-security)
- [OpenAI Codex Memories](https://developers.openai.com/codex/memories)
- [OpenAI ChatGPT Canvas help](https://help.openai.com/en/articles/9930697)
- [Anthropic Claude Artifacts](https://support.claude.com/en/articles/9487310-what-are-artifacts-and-how-do-i-use-them)
- [Anthropic Claude Projects](https://support.claude.com/en/articles/9517075-what-are-projects)
- [Anthropic Claude Code Security](https://code.claude.com/docs/en/security)
- [Anthropic Claude Code Permissions](https://code.claude.com/docs/en/permissions)
- [Anthropic Claude Code Permission Modes](https://code.claude.com/docs/en/permission-modes)
- [Cursor Background Agents](https://docs.cursor.com/en/background-agents)
- [Cursor Rules](https://docs.cursor.com/context/rules-for-ai)
- [Cursor Memories](https://docs.cursor.com/en/context/memories)
- [Windsurf Cascade Memories and Rules](https://docs.windsurf.com/windsurf/cascade/memories)
- [Windsurf Cascade Modes](https://docs.windsurf.com/windsurf/cascade/modes)
- [Windsurf Terminal](https://docs.windsurf.com/windsurf/terminal)
- [Windsurf Arena Mode](https://docs.windsurf.com/windsurf/cascade/arena)
- [Windsurf Worktrees](https://docs.windsurf.com/windsurf/cascade/worktrees)
