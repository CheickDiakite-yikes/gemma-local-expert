# Gemma Local Agent Architecture Brief

Date: April 17, 2026

## Why this exists

Goal: design a strong local-first AI assistant for real-world field use, especially in African regions with unreliable or no internet, and for missionary or care-oriented trips where privacy, offline capability, and practical task execution matter more than benchmark demos.

This brief is meant to answer a practical question:

What is the right way to build a serious local agent around the Gemma ecosystem on MLX without creating a fragile "everything talks to everything" science project?

## Executive take

The product should not be "one mega model" that tries to do chat, tool use, retrieval, vision, medicine, translation, and speech equally well.

It should be a local routed system:

- `Gemma 4 E4B-it` as the default general assistant and orchestrator
- `EmbeddingGemma` for local retrieval and memory
- `FunctionGemma` only as a specialized tool-calling component after task-specific tuning
- `PaliGemma 2` only when you need fine-tuned visual extraction or structured visual outputs
- `MedGemma 1.5 4B` as an explicit medical mode, not the default assistant
- `TranslateGemma` and speech components as optional field modules

The most important architectural decision is this:

Use a strong single-agent core with specialist routes, not a swarm-first system.

## First correction: the current model landscape

Your phrasing was directionally right, but the current landscape needs a precise update:

- `Gemma 4` was officially announced on April 2, 2026.
- The small edge-friendly Gemma 4 model is `E4B`, not a plain legacy-style "4B" naming scheme.
- Google describes Gemma 4 as purpose-built for reasoning and agentic workflows, with function calling, structured JSON output, and system instruction support.
- `EmbeddingGemma` is a separate 300M embedding model, trained on 100+ spoken languages.
- `FunctionGemma` is built on Gemma 3 270M and is explicitly positioned as a foundation to fine-tune for function calling. It is not meant to be your main chat assistant.
- `PaliGemma 2` remains important for vision tasks, but it is best thought of as a task-specialized visual model family rather than your default multimodal chat brain.
- `MedGemma 1.5 4B` is now the best small offline medical-specialist candidate in the family for image and records-adjacent use cases.
- `MedASR` exists as a separate 105M medical speech-to-text model for dictation-style workflows.

## Product thesis

If this product is going to be useful in the field, it needs to optimize for:

- Offline-first behavior
- Low-memory graceful degradation
- Clear user trust boundaries
- Strong note-taking and artifact creation
- Practical tool execution
- Local knowledge packs
- Multilingual support
- Explicit medical and non-medical separation

That means the product should feel more like:

"an offline field operating system with an assistant inside it"

than:

"a chatbot with too many model endpoints"

## What each model should do

## 1. Gemma 4 E4B-it

Role:
- Primary assistant
- Conversation manager
- Planner
- Summarizer
- Reasoning and response model
- Light multimodal entrypoint

Why:
- This is the best default center of gravity for the product.
- It keeps the system simple.
- It aligns with the newest Gemma architecture instead of forcing the product to remain centered on Gemma 3-era components.

What not to do:
- Do not make Gemma 4 solve every specialist task directly if a smaller specialist model can do it more reliably.
- Do not let it call tools without a policy layer and mode-specific permissions.

## 2. EmbeddingGemma

Role:
- Local semantic retrieval
- Memory indexing
- Search across notes, manuals, patient-safe materials, protocols, field guides, PDFs, and user knowledge packs

Why:
- Retrieval is the difference between a toy assistant and a working assistant.
- For offline deployments, a small dedicated embedding model is better than trying to force the chat model to do approximate retrieval in-context.

Recommended use:
- Pair it with local SQLite plus vector search.
- Build searchable stores for:
  - user notes
  - mission manuals
  - local language glossaries
  - care protocols
  - forms
  - device manuals
  - offline medical references approved for use

## 3. FunctionGemma

Role:
- Structured tool-call generation
- Tool schema routing
- Low-latency edge planner for restricted actions

Why:
- Google explicitly says it is intended to be fine-tuned for your specific function-calling task, including multi-turn use cases.
- That means it is valuable, but only after you define your tool surface.

Recommended use:
- Fine-tune it on your exact action schemas.
- Keep its tool universe small and operational:
  - create note
  - search knowledge base
  - summarize document
  - translate text
  - extract fields from form
  - schedule reminder
  - log patient-safe observation
  - generate supply checklist

What not to do:
- Do not use FunctionGemma as the main conversational model.
- Do not expose a huge arbitrary tool registry to it.

## 4. PaliGemma 2

Role:
- Specialist visual extraction
- OCR-like tasks
- reading text from images
- visual question answering on images and short videos
- object detection and segmentation when needed

Why:
- PaliGemma 2 is built for fine-tune performance on structured visual tasks.
- It is especially useful when the product needs reliable image understanding beyond general chat-level vision.

Recommended use:
- Keep it behind explicit tools:
  - read poster or sign
  - extract table or form from photo
  - detect objects in training or field imagery
  - parse educational materials

Important note:
- Since Gemma 4 is already multimodal, PaliGemma should not be in the default path for every image.
- Use Gemma 4 first for general image conversation.
- Route to PaliGemma 2 only when the task needs specialized structured vision behavior.

## 5. MedGemma 1.5 4B

Role:
- Medical mode assistant
- Clinical image interpretation support
- medical document extraction support
- medical reasoning aid for trained users in bounded workflows

Why:
- Google positions the 1.5 4B update as a compute-efficient starting point that is small enough to run offline.
- That is directly relevant to your rural and intermittent-connectivity use case.

How to use it safely:
- Make medical mode explicit, not ambient.
- Require a mode switch or domain trigger.
- Log provenance for every medical answer.
- Separate:
  - observation
  - extraction
  - possible interpretation
  - recommendation
- Require review language such as "assistive" or "for review" rather than authoritative diagnosis language.

What not to do:
- Do not run MedGemma in the default general chat loop.
- Do not let the product blur into diagnosis automation.

## 6. TranslateGemma

Role:
- Cross-language communication
- text translation
- text-in-image translation

Why it matters:
- For the Africa and rural field scenario, translation is not optional.
- Google launched TranslateGemma in January 2026 across 55 languages.

Recommendation:
- Treat this as a likely required module, not a nice-to-have.
- Verify your target language coverage early, because "supports many languages" is not the same as "supports the exact languages and dialects your teams need."

## 7. MedASR and general speech

Medical speech:
- `MedASR` is relevant if you want dictation or structured medical voice workflows in English.

General speech:
- For Apple hardware, `WhisperKit` is a strong on-device speech recognition candidate.
- For TTS, `Piper` is attractive technically, but its current `OHF-Voice/piper1-gpl` repo is GPL-3.0, so licensing needs review before commercial bundling.

## Recommended architecture

## Core principle

One orchestrator. Many bounded specialists. Minimal hidden magic.

## Current implemented agent run model

The repo now implements a concrete version of that principle:

- one conversational front door
- one orchestrator per turn
- one optional bounded workspace run inside that turn
- typed local tools for durable writes
- explicit approval before risky writes

The workspace run is intentionally constrained.

It can:

- inspect the configured workspace root
- search text-like files
- read bounded excerpts
- synthesize structured findings
- prepare a durable note, checklist, or task for approval

It cannot:

- execute arbitrary shell commands
- escape the configured workspace root
- become an always-on autonomous computer-use agent

That is the right shape for this product right now. It gives you real agentic
behavior over local files without turning the system into an opaque swarm or an
unsafe shell controller.

## System layers

### 1. Experience layer

- Chat UI
- Voice UI
- Camera / image intake
- Document intake
- Task inbox
- Notes and report generation

### 2. Agent runtime layer

- Conversation state manager
- Retrieval manager
- Planner
- Tool router
- Execution policy and approvals
- Memory writer
- Audit logger
- Safety and domain gates

### 3. Model layer

- `Gemma 4 E4B-it`: general orchestrator
- `EmbeddingGemma`: retrieval
- `FunctionGemma`: structured tool routing
- `PaliGemma 2`: specialist vision
- `MedGemma 1.5 4B`: medical mode
- `TranslateGemma 4B`: translation mode
- `MedASR` or general STT engine

### 4. Local data layer

- SQLite database
- FTS5 for lexical search
- vector index for semantic search
- encrypted local file store
- knowledge pack manifests
- local task and event log

### 5. Optional sync layer

- Sync only when internet is available
- Explicit conflict handling
- Sync notes, tasks, reports, and model telemetry summaries
- Never require sync for core operation

## Recommendation for local storage and retrieval

Start simple:

- SQLite
- FTS5
- `sqlite-vec`
- file-backed Markdown and JSON artifacts

Why:
- This is easier to ship and debug than running a separate vector database in an offline field product.
- `sqlite-vec` is small and portable, but it is still pre-v1, so treat it as a pragmatic default rather than a forever guarantee.

## Tool surface design

Do not give the assistant a vague "do anything" interface.

Give it a compact, explicit tool API:

- `create_note`
- `update_note`
- `search_memory`
- `summarize_document`
- `extract_image_text`
- `translate_text`
- `extract_form_fields`
- `create_checklist`
- `log_observation`
- `draft_message`
- `draft_report`
- `queue_sync`

If you later add:

- `medical_triage_assist`
- `med_image_review`
- `med_dictation_transcribe`

those should be in a separate medical tool namespace with stronger guardrails and audit logging.

## Mode design

This product should have clear modes.

Recommended modes:

### General mode

- Notes
- planning
- writing
- knowledge search
- messaging
- translation

### Field mode

- offline first
- aggressive caching
- low-latency models only
- shorter outputs
- battery-aware behavior

### Research mode

- long-form synthesis
- document processing
- cross-source comparison
- report generation

### Medical mode

- explicit entry
- medical model routing
- stronger disclaimers
- provenance and review logging
- no silent blending into general mode

## Architecture patterns worth borrowing from open-source agent systems

## Codex

What to borrow:
- local-first execution
- explicit workspace context files like `AGENTS.md`
- constrained tool access
- practical, artifact-oriented workflow

Why it matters:
- This is closer to the product shape you want than abstract multi-agent demos.

## Claude Code

What to borrow:
- terminal and workspace awareness
- strong extension surface
- natural language task execution against a real local environment

Why it matters:
- It reinforces the idea that a useful agent is not just a chat model; it is a controlled operator over tools and files.

## OpenAI Agents SDK

What to borrow:
- handoffs as explicit delegation
- sessions for memory
- guardrails around inputs, outputs, and tools
- tracing and workflow visibility

Why it matters:
- This gives a clean conceptual model for specialist routing without making everything a swarm.

## LangGraph

What to borrow:
- graph-based stateful workflows
- resumable long-running flows
- explicit nodes and transitions for complex tasks

Why it matters:
- Good fit for workflows like:
  - ingest documents
  - extract facts
  - retrieve references
  - draft report
  - request approval
  - export final artifact

## DeepAgents

What to borrow:
- planning
- filesystem backend
- subagent pattern
- batteries-included harness mentality

Why it matters:
- It is a strong reference for "single main agent plus bounded specialists."

## Swarms

What to borrow:
- orchestration vocabulary
- hierarchical and parallel patterns when truly needed

What not to copy by default:
- swarm-heavy architecture as the baseline product design

Why:
- In low-connectivity, high-trust, field settings, complexity is a tax.
- More agents means more routing errors, more memory fragmentation, more latency variance, and harder debugging.

## Strong recommendation: avoid swarm-first architecture

For this product, the default should be:

1. One main orchestrator agent
2. Retrieval before reasoning
3. Explicit specialist tool routes
4. Human approval on risky actions
5. Clear audit trail

Not:

1. many always-on agents
2. hidden delegation everywhere
3. overlapping memories
4. free-form tool calling

## A realistic v1 stack

If I had to define the first serious version now, I would build:

- `Gemma 4 E4B-it` on MLX as the default assistant
- `EmbeddingGemma` for retrieval
- SQLite + FTS5 + `sqlite-vec`
- `FunctionGemma` fine-tuned on a narrow task API
- `TranslateGemma 4B` for translation
- `WhisperKit` for Apple STT
- `PaliGemma 2` behind image extraction tools
- `MedGemma 1.5 4B` as explicit medical mode
- `Docling` for offline document parsing

I would not start with:

- a large multi-agent swarm
- a general-purpose vector database server
- always-on medical routing
- cloud-dependent search as a core dependency

## Build roadmap

## Phase 1: core offline assistant

- chat
- notes
- task drafting
- retrieval over local files
- translation
- document summarization

## Phase 2: multimodal field assistant

- image intake
- OCR
- form extraction
- sign/poster/manual understanding
- voice input

## Phase 3: domain specialist modules

- medical mode
- field research packs
- country-specific workflows
- localized terminology packs
- offline sync and supervisor dashboards

## Biggest design risks

- Overloading one assistant with too many silent specialist behaviors
- Confusing chat quality with task reliability
- Treating FunctionGemma like a finished tool caller instead of a tuning base
- Using PaliGemma everywhere when Gemma 4 can already handle general multimodal conversation
- Letting medical flows operate without explicit boundaries and provenance
- Building a swarm because it sounds advanced rather than because the workflow demands it

## My recommendation in one sentence

Build an offline-first field assistant with `Gemma 4 E4B` as the orchestrator, `EmbeddingGemma` as memory, `FunctionGemma` as a tuned tool router, `PaliGemma 2` and `MedGemma` as gated specialists, and a simple local storage and approval architecture instead of a swarm-first system.

## Sources

- Gemma 4 announcement: [blog.google/innovation-and-ai/technology/developers-tools/gemma-4](https://blog.google/innovation-and-ai/technology/developers-tools/gemma-4/)
- Gemma 4 Hugging Face models: [huggingface.co/google/gemma-4-E4B-it](https://huggingface.co/google/gemma-4-E4B-it)
- EmbeddingGemma model card: [ai.google.dev/gemma/docs/embeddinggemma/model_card](https://ai.google.dev/gemma/docs/embeddinggemma/model_card)
- FunctionGemma model card: [ai.google.dev/gemma/docs/functiongemma/model_card](https://ai.google.dev/gemma/docs/functiongemma/model_card)
- FunctionGemma launch post: [blog.google/innovation-and-ai/technology/developers-tools/functiongemma](https://blog.google/innovation-and-ai/technology/developers-tools/functiongemma/)
- PaliGemma 2 model card: [ai.google.dev/gemma/docs/paligemma/model-card-2](https://ai.google.dev/gemma/docs/paligemma/model-card-2)
- MedGemma launch/update posts:
  - [research.google/blog/medgemma-our-most-capable-open-models-for-health-ai-development](https://research.google/blog/medgemma-our-most-capable-open-models-for-health-ai-development/)
  - [research.google/blog/next-generation-medical-image-interpretation-with-medgemma-15-and-medical-speech-to-text-with-medasr](https://research.google/blog/next-generation-medical-image-interpretation-with-medgemma-15-and-medical-speech-to-text-with-medasr/)
- MedASR model card: [huggingface.co/google/medasr](https://huggingface.co/google/medasr)
- TranslateGemma launch/model card:
  - [blog.google/innovation-and-ai/technology/developers-tools/translategemma](https://blog.google/innovation-and-ai/technology/developers-tools/translategemma/)
  - [huggingface.co/google/translategemma-4b-it](https://huggingface.co/google/translategemma-4b-it)
- MLX core and tooling:
  - [github.com/ml-explore/mlx](https://github.com/ml-explore/mlx)
  - [github.com/ml-explore/mlx-lm](https://github.com/ml-explore/mlx-lm)
  - [github.com/Blaizzy/mlx-vlm](https://github.com/Blaizzy/mlx-vlm)
- Example MLX conversions:
  - [huggingface.co/mlx-community/functiongemma-270m-it-bf16](https://huggingface.co/mlx-community/functiongemma-270m-it-bf16)
  - [huggingface.co/mlx-community/embeddinggemma-300m-bf16](https://huggingface.co/mlx-community/embeddinggemma-300m-bf16)
  - [huggingface.co/mlx-community/medgemma-1.5-4b-it-4bit](https://huggingface.co/mlx-community/medgemma-1.5-4b-it-4bit)
- Agent architecture references:
  - [github.com/openai/codex](https://github.com/openai/codex)
  - [code.claude.com/docs/en/overview](https://code.claude.com/docs/en/overview)
  - [github.com/anthropics/claude-code](https://github.com/anthropics/claude-code)
  - [github.com/openai/openai-agents-python](https://github.com/openai/openai-agents-python)
  - [openai.github.io/openai-agents-python/handoffs](https://openai.github.io/openai-agents-python/handoffs/)
  - [openai.github.io/openai-agents-python/guardrails](https://openai.github.io/openai-agents-python/guardrails/)
  - [github.com/langchain-ai/langgraph](https://github.com/langchain-ai/langgraph)
  - [github.com/langchain-ai/deepagents](https://github.com/langchain-ai/deepagents)
  - [github.com/kyegomez/swarms](https://github.com/kyegomez/swarms)
- Retrieval and document tooling:
  - [github.com/asg017/sqlite-vec](https://github.com/asg017/sqlite-vec)
  - [github.com/docling-project/docling](https://github.com/docling-project/docling)
- Speech candidates:
  - [github.com/argmaxinc/WhisperKit](https://github.com/argmaxinc/WhisperKit)
  - [github.com/OHF-Voice/piper1-gpl](https://github.com/OHF-Voice/piper1-gpl)
