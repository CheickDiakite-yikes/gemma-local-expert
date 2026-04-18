# Gemma Local Expert Research Synthesis

Date: April 17, 2026
Status: Working research memo

Related local docs:
- [Gemma Local Agent Architecture Brief](gemma-local-agent-architecture.md)
- [Offline Field Assistant v1 Product Spec](offline-field-assistant-v1-product-spec.md)
- [Offline Field Assistant v1 Technical Architecture](offline-field-assistant-v1-technical-architecture.md)

## Why this memo exists

This memo validates the current workspace direction against current external sources and sharpens the architecture for a serious offline local assistant built around the Gemma ecosystem on Apple Silicon with MLX.

It is written for a specific mission:

- useful without internet
- practical in rural or low-connectivity environments
- safe for care-adjacent and research workflows
- strong for African language and field-work use cases
- grounded in real local agent patterns instead of generic "multi-agent" hype

## Executive summary

Your current direction is broadly right, but six things need to be made more explicit.

### 1. Do not confuse the product mission with the runtime choice

`MLX` is an excellent runtime for an Apple Silicon product you control.

It is not, by itself, a continent-scale deployment strategy for Africa.

That means you should think in terms of at least two product tracks:

- `Field Assistant Pro`: premium Apple Silicon workstation app, full local multimodal stack, best for mission teams, field researchers, clinicians, coordinators, and org staff carrying Mac hardware
- `Field Assistant Lite`: later lower-cost deployment path for broader field use, likely not MLX-first, and likely not feature-parity with the Pro stack

If you keep treating "MLX product" and "Africa product" as the same thing, the architecture will drift.

### 2. Gemma 4 E4B-it should be the center of gravity

As of April 2, 2026, Gemma 4 is the strongest open Gemma family center for this product. `E4B-it` is small enough to matter on-device while still bringing long context, multimodal input, reasoning support, and native function-calling support.

This strengthens the current workspace recommendation to use a single orchestrator with bounded specialists.

### 3. FunctionGemma should not be mandatory in v1

This is the biggest practical correction.

Google explicitly positions `FunctionGemma` as a 270M foundation to fine-tune for your own function-calling task. That makes it valuable, but only after your tool schemas are stable.

For v1, it is likely cleaner to:

- start with `Gemma 4 E4B-it` generating structured tool intents and JSON
- keep tool schemas small and typed
- add `FunctionGemma` later if you need lower latency, smaller edge planning, or better consistency after task-specific tuning

### 4. PaliGemma 2 should not be in the default path

This also matches your current docs, but it is worth making more forcefully.

Gemma 4 already supports image understanding, OCR-like tasks, and document parsing workflows. `PaliGemma 2` should be held behind specialist extraction tools for cases where you need structured, fine-tuned visual behavior.

### 5. MedASR is not your general Africa voice input answer

`MedASR` is strong, but it is:

- medical dictation oriented
- English only
- trained mostly on US English, mostly high-quality microphones

So `MedASR` belongs in explicit medical dictation flows, not as the default offline voice layer for multilingual African field use.

### 6. Africa-specific language support cannot be assumed

The strongest architecture risk is not model reasoning. It is language coverage and real-world robustness.

You should assume you need a language evaluation matrix from day one for:

- translation
- retrieval
- note drafting
- medical language
- voice transcription

The Google Gemma family gives you a strong starting point, but for African language depth you should plan for optional adapters or alternative supporting models.

## Verified ecosystem facts

## 1. Gemma 4 E4B-it

Verified from Google's April 2, 2026 launch and the official Hugging Face card:

- Gemma 4 was announced on April 2, 2026.
- `E4B` is the small edge-friendly Gemma 4 variant relevant to this product.
- `Gemma 4 E4B-it` supports text and image input, with audio support on the small `E2B` and `E4B` models.
- The Gemma 4 family is positioned for reasoning, coding, multimodal understanding, and agentic workflows.
- The official Hugging Face card says `E2B` and `E4B` have `128K` context, while larger Gemma 4 models reach `256K`.
- The official Hugging Face card also describes native function calling and structured tool use support.

Product implication:

- `Gemma 4 E4B-it` should be the main conversation, planning, synthesis, and general multimodal model.
- You should not anchor the architecture on Gemma 3-era assumptions anymore.

Implementation nuance:

- Older generic Gemma prompt docs say instruction-tuned Gemma uses only `user` and `model` roles, with no separate `system` turn.
- The Gemma 4 Hugging Face template now shows `system` role usage in practice.

Inference:

- Do not build one universal "Gemma prompt formatter" abstraction.
- Build against the exact tokenizer and chat template for each deployed model/runtime path.

## 2. EmbeddingGemma

Verified from Google AI for Developers:

- `EmbeddingGemma` is a small multilingual embedding model based on Gemma 3.
- The model card describes it as `300M` parameters, while the overview page describes it as `308M`; this looks like documentation rounding rather than a product distinction.
- It was trained on `100+` spoken languages.
- It supports `2K` token input.
- Default embedding dimension is `768`, with smaller `512`, `256`, and `128` options via Matryoshka Representation Learning.
- Google positions it for low-resource and on-device use, including phones, laptops, and tablets.

Product implication:

- `EmbeddingGemma` is still the right default local retrieval backbone.
- It is especially attractive because it is small enough to keep retrieval cheap and always available.

## 3. FunctionGemma

Verified from the official model card and docs:

- `FunctionGemma` is built on `Gemma 3 270M`.
- Google says it is a foundation for developers to fine-tune on their own function-calling task.
- Google explicitly says it is not intended to be used as a direct dialogue model.
- Google provides a special function-calling formatting path and control tokens for it.

Product implication:

- Use it only after you define a narrow tool surface.
- Do not make it the main assistant.
- Do not wire it up before the tool API stabilizes.

## 4. PaliGemma 2

Verified from the official model card:

- `PaliGemma 2` is built for strong fine-tune performance on image captioning, visual question answering, text reading, object detection, segmentation, and short video tasks.
- It is a specialist vision-language family, not your default chat brain.

Product implication:

- Keep it behind explicit tools such as:
  - `extract_form_fields`
  - `read_poster_or_sign`
  - `medical_document_extract`
  - `detect_objects_in_training_image`

## 5. MedGemma 1.5 4B

Verified from Google's January 13, 2026 announcement and official Hugging Face card:

- `MedGemma 1.5` is currently released as a `4B` multimodal instruction-tuned variant.
- The model card says it supports `128K` input context and `8192` output tokens.
- Google positions it for medical text and image comprehension, including CT, MRI, histopathology, longitudinal chest X-ray comparison, and anatomical localization.
- The model is under `Health AI Developer Foundations` terms, not standard Apache 2.0.

Product implication:

- It is the best small medical specialist in the Gemma family for offline use.
- It must remain an explicit medical mode component with stronger audit and legal review.

## 6. MedASR

Verified from the official Hugging Face model card:

- `MedASR` is a `105M` Conformer-based speech-to-text model.
- It is intended as a starting point for medical dictation workflows.
- It is English only.
- The card warns about weaker performance outside its training conditions, including accents, low-quality audio, and non-standard terms.

Product implication:

- Use it only for English medical dictation mode.
- Do not treat it as the universal speech layer for African field use.

## 7. TranslateGemma

Verified from Google's January 15, 2026 launch and the official Hugging Face card:

- `TranslateGemma` is a family of translation models based on Gemma 3.
- Google released `4B`, `12B`, and `27B` sizes.
- The model is designed for translation across `55` languages.
- It supports text translation and text-in-image translation.
- The `4B` model uses a specialized chat template with only `user` and `assistant` roles and explicit `source_lang_code` and `target_lang_code` fields.
- The official card gives it a `2K` total input context.

Product implication:

- Translation should be a first-class module, not just a prompt pattern on the main chat model.
- Because the accessible official sources I reviewed do not clearly enumerate the full supported language list, you should treat target-language coverage as a bench test, not an assumption.

## 8. MLX runtime stack

Verified from the official MLX repositories and MLX-community conversions:

- `mlx-lm` is the primary MLX package for text generation and fine-tuning on Apple Silicon.
- `mlx-vlm` provides vision-language and omni-model support on Apple Silicon.
- `mlx-embeddings` supports embedding inference.
- `mlx-community` already hosts MLX conversions for `EmbeddingGemma`, `FunctionGemma`, `MedGemma 1.5`, and Gemma 4 E4B variants.
- The Gemma 4 MLX conversions visible now are community conversions, not an official Google MLX release.

Product implication:

- The stack is practical today for a Mac-first product.
- You should still treat model conversion and runtime compatibility as part of your release engineering, not as a solved assumption.

## 9. WhisperKit

Verified from the official repository:

- `WhisperKit` is an on-device speech recognition framework for Apple Silicon.
- It supports real-time streaming, word timestamps, and voice activity detection.
- It also ships a local server that mirrors the OpenAI Audio API shape.
- It is MIT licensed.

Product implication:

- This is currently the cleanest fit for the default offline STT layer in a native macOS app.
- The local server is especially useful if you want the speech subsystem to look like a typed service instead of a direct in-process dependency.

## 10. Docling

Verified from the official repository:

- `Docling` is an MIT-licensed document processing library focused on document parsing for gen-AI use cases.
- It is active and broadly used for PDFs and mixed document formats.

Product implication:

- It is a strong default ingestion engine for knowledge packs, reports, manuals, and forms.

## 11. sqlite-vec

Verified from the official repository:

- `sqlite-vec` is a very small vector search extension for SQLite.
- It is portable and dependency-light.
- The project explicitly says it is still `pre-v1` and may introduce breaking changes.

Product implication:

- It remains a strong default for v1 because it keeps the product simple and offline-friendly.
- Pin exact versions and expect migration work later.

## 12. Piper

Verified from the official repositories:

- The older `rhasspy/piper` repository was archived on October 6, 2025 and shows an MIT license.
- Development moved to `OHF-Voice/piper1-gpl`.
- The active `OHF-Voice/piper1-gpl` repository is GPL-3.0 and the July 10, 2025 release explicitly notes the license change to GPLv3.

Product implication:

- Keep TTS behind an abstraction layer.
- Do not commit the commercial product direction to Piper until license review is complete.

## Africa-specific gaps and opportunities

This is where the current workspace needs more realism.

## 1. Translation coverage must be tested per country pack

Officially, TranslateGemma supports 55 languages. That is encouraging, but not enough.

For the field product, you need a language matrix per deployment:

- country
- primary language
- secondary language
- English/French/Portuguese bridge language
- translation direction
- note-writing language
- speech language

Without this, "multilingual" is not a product claim.

## 2. Retrieval may need an Africa-specific fallback embedding model

EmbeddingGemma is a strong default. But if your primary deployments depend on African languages or code-switching, you should be prepared to compare it against an Africa-adapted alternative.

One credible benchmarked option in the open ecosystem is `McGill-NLP/AfriE5-Large-instruct`, which is adapted for African languages and evaluated on `AfriMTEB`.

Recommendation:

- keep `EmbeddingGemma` as the default v1 path
- run a bakeoff against `AfriE5-Large-instruct` on your target language packs before locking retrieval

## 3. General language adaptation may eventually justify a Gemma-family adapter

One credible ecosystem signal is `McGill-NLP/AfriqueGemma-4B`, a Gemma-3-based model adapted across 20 African languages.

This should not replace Gemma 4 for the main product today.

But it is evidence that:

- Gemma-family African language adaptation is active
- a future African-language adapter or continued pre-training path is realistic

## 4. Community-health adaptation on top of MedGemma is already happening

A good signal here is `electricsheepafrica/chewie-1.2`, a MedGemma-based LoRA adapter for African community health workflows.

That does not make it a product dependency.

It does mean your "medical mode for Africa" idea is not speculative. The ecosystem is already testing it.

## Architecture patterns worth borrowing from agent frameworks

## 1. OpenAI Codex

Useful patterns visible in the open repository:

- local execution as the default
- workspace instruction file pattern via `AGENTS.md`
- a reusable skills packaging layer via `.codex/skills`
- practical focus on artifacts and tool-mediated work instead of abstract "AI coworker" claims

What to borrow:

- project-scoped instruction files
- compact capability modules as installable skills
- explicit approvals and constrained execution
- artifact-first workflows

What not to copy literally:

- coding-agent specific assumptions such as shell-heavy tool surfaces

## 2. Claude Code

Useful patterns visible in the open repository and docs:

- terminal-native task execution
- plugins and extensibility
- subagents
- hooks
- experimental agent teams for parallel work

What to borrow:

- plugin/module system
- hooks for policy, logging, or approval interception
- explicit teammate or subagent invocation instead of hidden delegation

What not to copy literally:

- team-first or subagent-heavy execution as your default experience

The docs themselves make the tradeoff clear: agent teams add coordination overhead and higher token cost, and are best when work is truly parallel.

## 3. LangGraph

Useful patterns from the repository:

- durable execution
- human-in-the-loop checkpoints
- short-term and long-term memory
- explicit state transitions

This is highly relevant for:

- knowledge-pack imports
- document ingestion jobs
- report drafting flows
- approvals
- resumable sync/export work

What to borrow:

- graph-style workflow design for long-running flows
- resumable jobs with explicit checkpoints

## 4. DeepAgents

Useful patterns from the repository:

- planning tool
- filesystem backend abstraction
- optional subagents
- interrupt-based approval flow

Most important design lesson:

- the project explicitly says to enforce boundaries at the tool and sandbox layer, not by trusting the model to self-police

That is exactly right for this product.

What to borrow:

- planning before execution
- filesystem backends for local artifacts and memory
- optional subagents only where context isolation matters
- approval interrupts

## 5. Swarms

Useful patterns from the repository:

- orchestration vocabulary
- hierarchical swarm pattern
- parallel pipelines
- graph-based networks
- agent registry concepts

What to borrow:

- only the vocabulary and a small subset of the orchestration concepts

What not to borrow:

- swarm complexity as a default architecture
- overlapping memories
- many always-on specialists

For this product, the offline field setting makes complexity expensive:

- more memory pressure
- harder debugging
- less predictable latency
- weaker audit clarity
- more user trust issues

## Recommended product architecture update

Your current "single orchestrator plus bounded specialists" direction is correct.

I would sharpen it into this:

## Control plane

- deterministic mode gate
- deterministic policy gate
- deterministic tool registry
- deterministic audit writer

These should be normal software, not model behavior.

## Intelligence plane

- `Gemma 4 E4B-it` for conversation, planning, synthesis, and general multimodal reasoning
- retrieval service backed by `EmbeddingGemma`
- translation service backed by `TranslateGemma`
- optional specialist vision service backed by `PaliGemma 2`
- optional medical service backed by `MedGemma 1.5`
- optional medical dictation service backed by `MedASR`

## Orchestration principle

The orchestrator should decide among only four actions:

1. answer directly
2. retrieve then answer
3. propose a tool call
4. route to a specialist and then synthesize

Everything else should be hidden behind normal application services.

## Tool-calling recommendation

For v1:

- use `Gemma 4 E4B-it` plus typed JSON schemas for tool proposals
- validate tool arguments in normal code
- require explicit confirmation for writes and exports

For v2:

- add a tuned `FunctionGemma` planner if the tool surface is stable and you need a smaller or more reliable tool-calling component

## Vision recommendation

For v1:

- let Gemma 4 handle general image Q&A and basic OCR-style reasoning

For v2:

- add `PaliGemma 2` only for specialist extraction flows with measurable gain

## Medical recommendation

For v1 beta:

- explicit medical session
- explicit medical tools
- explicit provenance
- explicit review-oriented language
- separate audit trail

## Retrieval recommendation

For v1:

- SQLite
- FTS5
- `sqlite-vec`
- encrypted file store
- knowledge pack manifests

Add only one extra retrieval experiment:

- compare `EmbeddingGemma` vs `AfriE5-Large-instruct` on your target African language packs

## Product segmentation recommendation

This is the cleanest business and systems framing:

### Product A: Field Assistant Pro

Target:

- Apple Silicon Mac
- mission teams
- researchers
- operations staff
- care supervisors

Capabilities:

- full Gemma 4 local multimodal assistant
- retrieval
- translation
- voice
- knowledge packs
- report generation
- optional medical mode

### Product B: Field Assistant Lite

Target:

- lower-cost deployment environments
- broader field access
- lighter hardware

Capabilities:

- translation
- retrieval
- note capture
- lightweight chat
- maybe hub-and-spoke sync with Product A later

Key point:

- do not force Product B requirements to distort Product A architecture yet
- do not pretend Product A alone solves the broader offline Africa distribution problem

## Immediate engineering moves

These are the highest-leverage next steps.

### 1. Build an evaluation matrix before more architecture writing

Create a benchmark set covering:

- 20 to 30 field-research questions over local knowledge packs
- 20 translation tasks in target deployment languages
- 15 image extraction tasks
- 10 report-generation tasks
- 10 medical beta tasks
- 10 voice tasks under noisy conditions

### 2. Freeze the v1 tool surface early

Decide the exact first-class tools before introducing FunctionGemma fine-tuning.

If you keep changing tool schemas, you cannot evaluate the planner layer honestly.

### 3. Benchmark real device tiers

Test at least:

- MacBook Air or equivalent 16 GB
- MacBook Pro 24 GB
- MacBook Pro 36 GB or higher if available

Measure:

- cold start
- warm start
- tokens per second
- image turn latency
- memory pressure
- battery impact

### 4. Run the first retrieval bakeoff

Compare:

- `EmbeddingGemma`
- `AfriE5-Large-instruct`

Use the same chunking and ranking pipeline on:

- English-only mission docs
- bilingual packs
- target African language packs
- code-switched notes

### 5. Start with one orchestrator, zero swarms

If you need concurrency, use normal software jobs first.

Only add subagents after a workflow proves it needs context isolation or parallel exploration.

### 6. Put speech behind a service boundary

Start with:

- `WhisperKit` for general offline STT
- TTS abstraction with no hard lock-in yet

Add:

- `MedASR` only inside medical dictation mode

### 7. Treat medical mode as a product inside the product

It needs:

- separate copy
- separate onboarding
- separate evals
- separate audit design
- legal and operational review

## Bottom line

The current workspace is directionally strong.

The right build is not a swarm-first "everything Gemma" science project.

It is a routed local operating system for field work:

- `Gemma 4 E4B-it` as the main brain
- `EmbeddingGemma` as retrieval memory
- `TranslateGemma` as a first-class communications module
- `FunctionGemma` only after tool-schema stability
- `PaliGemma 2` only when structured vision is measurably better
- `MedGemma 1.5` and `MedASR` only in explicit medical mode
- `WhisperKit`, `Docling`, and `sqlite-vec` as strong local infrastructure

And if the mission is truly Africa-wide offline usefulness, then the strategic truth is:

`MLX` is the right premium local runtime, but not the whole platform strategy.

## Sources

Gemma and model stack:

- Gemma 4 launch, April 2, 2026: https://blog.google/innovation-and-ai/technology/developers-tools/gemma-4/
- Gemma 4 E4B-it official card: https://huggingface.co/google/gemma-4-E4B-it
- EmbeddingGemma overview: https://ai.google.dev/gemma/docs/embeddinggemma
- EmbeddingGemma model card: https://ai.google.dev/gemma/docs/embeddinggemma/model_card
- FunctionGemma model card: https://ai.google.dev/gemma/docs/functiongemma/model_card
- Function calling with Gemma: https://ai.google.dev/gemma/docs/capabilities/function-calling
- PaliGemma 2 model card: https://ai.google.dev/gemma/docs/paligemma/model-card-2
- MedGemma 1.5 and MedASR launch, January 13, 2026: https://research.google/blog/next-generation-medical-image-interpretation-with-medgemma-15-and-medical-speech-to-text-with-medasr/
- MedGemma 1.5 4B official card: https://huggingface.co/google/medgemma-1.5-4b-it
- MedASR official card: https://huggingface.co/google/medasr
- TranslateGemma launch, January 15, 2026: https://blog.google/innovation-and-ai/technology/developers-tools/translategemma/
- TranslateGemma 4B official card: https://huggingface.co/google/translategemma-4b-it
- Gemma prompt structure doc: https://ai.google.dev/gemma/docs/core/prompt-structure

Local runtime and supporting tools:

- MLX core: https://github.com/ml-explore/mlx
- MLX LM: https://github.com/ml-explore/mlx-lm
- MLX VLM: https://github.com/Blaizzy/mlx-vlm
- sqlite-vec: https://github.com/asg017/sqlite-vec
- Docling: https://github.com/docling-project/docling
- WhisperKit: https://github.com/argmaxinc/WhisperKit
- Piper archived MIT repo: https://github.com/rhasspy/piper
- Piper active GPL repo: https://github.com/OHF-Voice/piper1-gpl

Agent architecture references:

- OpenAI Codex repo: https://github.com/openai/codex
- Claude Code repo: https://github.com/anthropics/claude-code
- Claude Code subagents docs: https://code.claude.com/docs/en/sub-agents
- Claude Code agent teams docs: https://code.claude.com/docs/en/agent-teams
- LangGraph repo: https://github.com/langchain-ai/langgraph
- DeepAgents repo: https://github.com/langchain-ai/deepagents
- Swarms repo: https://github.com/kyegomez/swarms

Africa-specific optional references:

- AfriqueGemma-4B: https://huggingface.co/McGill-NLP/AfriqueGemma-4B
- AfriE5-Large-instruct: https://huggingface.co/McGill-NLP/AfriE5-Large-instruct
- Chewie 1.2: https://huggingface.co/electricsheepafrica/chewie-1.2
