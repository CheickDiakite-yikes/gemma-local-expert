# Live Real Multimodal Eval

Date: 2026-04-20  
Environment: live localhost server at `http://127.0.0.1:8000`  
Raw log: [output/evals/live-real-multimodal-2026-04-20.json](/Users/cheickdiakite/Codex/gemma-local-expert/output/evals/live-real-multimodal-2026-04-20.json)

## Scope

This run exercised a real long-form multimodal conversation against the live low-memory server using two real uploaded videos:

- [Screen Recording 2026-04-11 at 1.42.15 PM.MOV](/Users/cheickdiakite/Downloads/Screen%20Recording%202026-04-11%20at%201.42.15%E2%80%AFPM.MOV)
- [Screen Recording 2026-04-11 at 2.06.18 PM.MOV](/Users/cheickdiakite/Downloads/Screen%20Recording%202026-04-11%20at%202.06.18%E2%80%AFPM.MOV)

The document leg was not executed in this run because the thread did not expose a concrete document filepath. The eval harness supports `--document-path` and should be rerun once the exact local document path is known.

## Capability Snapshot

From `GET /v1/system/capabilities` at run time:

- `assistant_backend=mlx`
- `assistant_model=gemma-4-e2b-it-4bit`
- `specialist_backend=ocr`
- `vision_model=paligemma-2`
- `tracking_backend=auto`
- `tracking_model=sam3.1`
- `tracking_model_available=false`
- `ffmpeg_available=true`
- `low_memory_profile=true`

Interpretation:

- The live server can upload and sample videos locally.
- The live server cannot do real SAM-backed video tracking in this profile.
- Any assistant claim that implies completed SAM tracking is a product-harness failure, not just a model weakness.

## Assets

### Video A

- path: [Screen Recording 2026-04-11 at 1.42.15 PM.MOV](/Users/cheickdiakite/Downloads/Screen%20Recording%202026-04-11%20at%201.42.15%E2%80%AFPM.MOV)
- duration: `81.75s`
- resolution: `3574x2002`
- fps: about `28.9`

### Video B

- path: [Screen Recording 2026-04-11 at 2.06.18 PM.MOV](/Users/cheickdiakite/Downloads/Screen%20Recording%202026-04-11%20at%202.06.18%E2%80%AFPM.MOV)
- duration: `55.16s`
- resolution: `3574x2002`
- fps: about `52.9`

## Scenario

The conversation ran `17` turns and covered:

- conservative review of video A
- tool / weapon / process follow-ups
- isolation request
- SAM tracking request
- fallback-artifact request
- review of video B
- cross-video comparison
- strongest-claim / weakest-claim question
- structured video tagging request
- message-draft generation and revision
- report generation and title revision
- normal conversational follow-up at the end

## What Worked

- The server handled two large real video uploads without crashing.
- The system generated sampled contact-sheet assets for uploaded videos.
- The assistant stayed conservative about naming a weapon and explicitly acknowledged uncertainty.
- Approval-backed durable output still worked during the long conversation.
- The conversation stayed alive through `17` turns without transport failure.

## High-Severity Findings

### 1. The assistant hallucinated SAM execution when SAM was unavailable

Turn 6 said:

- `Executing local SAM tracking/isolation on the video.`
- `Status: Tracking/Isolation process is running.`

But the live capabilities snapshot had `tracking_model_available=false`. No tracked video artifact was produced. This is a hard trust failure. The assistant should have refused or downgraded immediately to the actual ffmpeg/contact-sheet fallback instead of claiming the action was running.

### 2. The assistant hallucinated isolation results with placeholder content

Turn 5 claimed:

- `I have isolated the segments from the video...`

But the content was only placeholder timecodes and bracketed filler:

- `[Describe the action/object observed in this segment.]`

This is worse than a weak answer. It fabricates completion and makes the UI look like a finished analysis when no grounded object isolation actually happened.

### 3. Video comparison report routing was hijacked into the workspace-agent path

Turn 14 asked for a report comparing both videos. Instead of staying asset-grounded, the system switched into workspace synthesis and prepared a report from repo files. The pending report payload included code/repo content such as:

- `tests/test_router.py`
- `engine/api/routes/conversations.py`
- `engine/context/service.py`

This is a serious router failure. A multimodal comparison request over two uploaded videos must not pivot into workspace-file summarization just because the user also said `save it as a report`.

### 4. Draft outputs were built from placeholders, not grounded findings

The supervisor message draft and the report draft both contained generic template filler instead of grounded video facts:

- `[Insert the main process observed here ...]`
- `[List 1-3 main tools/items observed ...]`

This shows the tool/draft layer can fire even when the evidence layer never produced structured facts good enough to support a draft.

## Medium-Severity Findings

### 5. Multi-video referent continuity broke repeatedly

After reviewing both videos, turn 9 still said it needed the user to remind it which first-video focus to compare, even though the conversation was explicitly about both uploaded clips. Turn 17 also collapsed and said only one video was explicit. This means the continuity layer is still not maintaining a stable active multi-asset set through longer multimodal threads.

### 6. Video grounding stayed generic even after contact sheets existed

The system did generate contact sheets, but the assistant mostly responded with generic language like:

- `sequence of actions`
- `interaction/manipulation`
- `different scene or activity`

That suggests the fallback path is producing artifacts, but the assistant is not actually grounding its later answers in a real sampled-frame interpretation loop.

### 7. The system regenerated contact-sheet assets on repeated follow-ups

The transcript shows new contact-sheet assets for the same source video on several follow-up turns. That creates unnecessary asset churn, wastes time, and makes long conversations noisier than they need to be. The assistant should reuse prior sampled artifacts for the same asset unless the user explicitly requests a new sampling pass.

### 8. Approval continuity is still clumsy across revisions

The message-draft revision turn created a fresh approval object rather than behaving like a clean in-place edit on the existing draft. The report title follow-ups also created additional approval objects. This is workable, but it is not yet a smooth “keep editing the same draft” user experience.

## Lower-Severity Findings

### 9. Structured tagging did not execute

Turn 11 asked for structured labels for people, tools, possible weapons, actions, and confidence. The assistant returned a refusal-like stub saying it needed content again, even though the same conversation already had the uploaded video and generated contact sheets. This is a routing/context-access weakness more than a model-limit issue.

### 10. The initial first-video answer was too metadata-first

Turn 1 mostly returned file metadata and asked what to look for next. That is safe, but too weak for the product goal. Once the system samples frames and generates a contact sheet, the first answer should already include a conservative visual summary of the sampled evidence.

## Architecture Weaknesses

### Video pipeline weakness

Current low-memory video fallback is:

- upload video
- probe metadata
- sample frames with ffmpeg
- build contact sheet

What is missing is the crucial next step:

- run frame-level visual interpretation over the sampled frames
- extract structured facts
- bind later claims to those facts

Without that layer, the assistant either stays generic or hallucinates.

### Router weakness

The router and orchestration stack still over-prioritize durable-output intents like `report` without preserving the source domain of the request. That is how `compare both videos and save it as a report` drifted into `search workspace files and synthesize repo docs`.

### Harness weakness

The assistant text layer can claim actions that the runtime never completed. There is not yet a hard contract that says:

- if `tracking_model_available=false`
- then assistant must not say tracking is running or complete

The same issue applies to isolation and segment extraction.

### Context weakness

The system does not yet maintain a durable multi-asset comparison frame. Once two videos are in play, later turns should preserve:

- active asset A
- active asset B
- comparison goal
- last grounded findings for each

Instead, the assistant repeatedly collapsed back to a single-asset or ambiguous state.

### Tool-output weakness

The drafting layer can produce a note, message, or report shell before the evidence layer has emitted structured facts. That creates polished-looking outputs that are not actually grounded.

## Target Backlog

### Highest priority

- Add a frame-grounded video fallback pipeline: sample frames, run vision on each sampled frame, merge into structured findings, then answer from that structure.
- Hard-gate assistant claims on runtime truth. If tracking is unavailable, the assistant must say so immediately and cannot claim SAM execution or isolation progress.
- Preserve a stable active multi-video comparison state in context so `first video`, `second video`, and `both videos` stay anchored across long follow-ups.
- Prevent workspace-agent routing from hijacking asset-grounded report requests.

### Next priority

- Reuse existing contact-sheet artifacts for the same video across follow-up turns.
- Make approval-backed edits mutate the active pending draft instead of spawning awkward new draft identities.
- Add structured video tags as a first-class artifact: people, tools, possible weapons, actions, confidence, timestamps.

### After that

- Bring SAM tracking online in a profile where `tracking_model_available=true`, then rerun this exact script and compare results.
- Add document-path coverage to the same eval so one transcript can exercise video, document, durable outputs, and normal conversation together.

## Bottom Line

The current product can sustain a long real multimodal conversation and generate local artifacts, but it is not yet trustworthy for serious video reasoning.

The biggest problem is not just model quality. It is contract quality:

- the assistant can over-claim work the runtime did not do
- the router can jump from video comparison into workspace synthesis
- the continuity layer can lose multi-video anchors
- the draft/output layer can formalize placeholder content into saveable objects

This is exactly the kind of eval we need. It tells us the next architecture targets clearly.
