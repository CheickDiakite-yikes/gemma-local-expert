# Live Real Multimodal Eval With Document

Date: 2026-04-20  
Raw log: [output/evals/live-real-multimodal-with-doc-2026-04-20.json](/Users/cheickdiakite/Codex/gemma-local-expert/output/evals/live-real-multimodal-with-doc-2026-04-20.json)  
Related earlier video-only report: [docs/live-real-multimodal-eval-2026-04-20.md](/Users/cheickdiakite/Codex/gemma-local-expert/docs/live-real-multimodal-eval-2026-04-20.md)

## Scope

This run extended the earlier live multimodal eval by adding a real PDF:

- [Screen Recording 2026-04-11 at 1.42.15 PM.MOV](/Users/cheickdiakite/Downloads/Screen%20Recording%202026-04-11%20at%201.42.15%E2%80%AFPM.MOV)
- [Screen Recording 2026-04-11 at 2.06.18 PM.MOV](/Users/cheickdiakite/Downloads/Screen%20Recording%202026-04-11%20at%202.06.18%E2%80%AFPM.MOV)
- [Mali_Intelligence_Strategy.pdf](/Users/cheickdiakite/Downloads/Mali_Intelligence_Strategy.pdf)

The conversation ran `19` turns.

## Capability Snapshot

At run time:

- `assistant_backend=mlx`
- `specialist_backend=ocr`
- `vision_model=paligemma-2`
- `tracking_model=sam3.1`
- `tracking_model_available=false`
- `ffmpeg_available=true`
- `low_memory_profile=true`

That means:

- video sampling is available
- true SAM-backed video tracking is not available
- document extraction is effectively OCR/path-dependent in this server profile

## Document Reality Check

The assistant's document answers were checked against the actual PDF.

### What the PDF actually looks like

`pdftotext` returned only form-feed characters, which means the document is not behaving like an ordinary embedded-text PDF in the current extraction path.

OCR on rendered pages showed the real document begins like this:

Page 1:

- `Mali at a Turning Point: Organizing Knowledge to Capture National Value`

Page 2:

- `The world is entering a new age of intelligence.`
- `The question is not whether change is coming. The question is whether Mali will react to it, or use it to its advantage.`

Page 3:

- timeline / evolution framing about AI and government workflows

Page 4:

- `AI has moved from theory to everyday national advantage.`

This is enough to conclude the assistant's extraction was not grounded.

## Document Findings

### 1. The assistant hallucinated a document structure that is not in the PDF

The assistant claimed sections like:

- `Phase I: Reconnaissance & Information Gathering`
- `Phase II: Analysis & Synthesis`
- `Phase III: Operational Deployment`
- `Phase IV: Post-Operation Reporting`

Those do not match the real first-page and early-page content. This is a hard document-grounding failure.

### 2. The assistant mixed file-understanding claims with repo/code examples instead of the PDF

In the first document summary turn, it described local file understanding using examples like:

- `knowledge_packs.py`
- `service.py`
- SQL migration files

That is generic repo talk, not analysis of the attached PDF. This shows the assistant is still too willing to answer from internal/product priors when the file extraction layer is weak.

### 3. The document turn appears to have triggered workspace-agent behavior behind the scenes

The raw log shows workspace-run activity for the document request. That is a routing smell. A request about an attached document should stay document-grounded first, not implicitly drift into workspace-document search.

## Video Findings From This Run

The video issues from the earlier run reproduced again:

- SAM tracking was claimed even though `tracking_model_available=false`
- isolation outputs were described as complete while still containing placeholders
- multi-video comparison continuity stayed weak
- report generation still drifted into a durable-output path before grounded comparison facts were established

This run also had a slightly different but still problematic first-turn behavior:

- the first answer talked about `router guidance` instead of just describing the sampled evidence

That is another form of exposed internal machinery on the user surface.

## Combined Product Weaknesses

### Runtime truthfulness

The assistant still over-claims what the runtime has done:

- `Executing local SAM tracking`
- `Processing complete`

when the runtime cannot actually do that in the current profile.

### Asset-grounded routing

Once a request includes:

- attached video
- attached document
- durable output request

the router still struggles to preserve the source domain cleanly. It can drift into workspace synthesis or generic repo reasoning too early.

### Evidence-to-draft contract

The system still allows drafts and reports to be generated from:

- placeholders
- generic template language
- repo-file summaries

before the evidence layer is strong enough.

### Document extraction robustness

The current harness does not have a strong fallback chain for PDFs like this:

- embedded text extraction failed
- OCR would have been needed
- the assistant still answered as if structured extraction had succeeded

That is exactly the wrong failure mode.

## Strongest Backlog Targets After This Run

### 1. Add hard truth gates between runtime and assistant phrasing

If:

- `tracking_model_available=false`
- text extraction failed
- OCR did not run

then the assistant must not speak as if those analyses completed.

### 2. Build a real PDF extraction fallback stack

For document turns:

- try embedded text extraction
- if empty, render pages
- OCR selected pages or all pages
- expose extracted evidence to the assistant
- only then allow section/entity/action extraction

### 3. Separate attached-asset routing from workspace routing more aggressively

A request about:

- attached videos
- attached PDFs

should remain asset-grounded unless the user explicitly asks to search the workspace too.

### 4. Require grounded structured facts before durable output generation

Before a report or message draft is proposed, the system should have a structured fact packet such as:

- sampled evidence
- extracted entities
- comparison facts
- uncertainty notes

If that packet does not exist, the assistant should ask one clarifying question or say it needs to run the extraction first.

## Bottom Line

The document leg made the evaluation sharper.

The current system can sustain a long mixed multimodal conversation and ingest real local files, but it is still too willing to answer confidently when the extraction layer failed. For both video and PDF, the core issue is the same:

- weak or unavailable evidence pipeline
- assistant still speaks as if evidence exists

That is the main reliability gap to fix next.
