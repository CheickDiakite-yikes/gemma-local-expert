# Repo Plan

This scaffold is intentionally thin. The next delivery slices should happen in
this order:

## Slice 1

- stabilize the HTTP contracts
- replace in-memory persistence with SQLite
- write migrations
- add approval persistence and conversation history tables

## Slice 2

- integrate `EmbeddingGemma`
- implement chunking and hybrid retrieval
- add knowledge-pack ingestion jobs
- establish retrieval eval metrics

## Slice 3

- integrate `Gemma 4 E4B-it`
- implement prompt assembly and structured tool intents
- add typed citations and model provenance to assistant events

## Slice 4

- integrate `TranslateGemma`
- add translation-specific evals per target deployment language
- add image-text translation path

## Slice 5

- integrate image understanding path
- start with Gemma 4 multimodal
- add `PaliGemma 2` only if extraction benchmarks justify it

## Slice 6

- add explicit medical sessions
- integrate `MedGemma 1.5`
- add medical audit events
- add policy and UX hard gates

## Slice 7

- add local speech boundary
- integrate `WhisperKit`
- add TTS abstraction
- keep `MedASR` inside medical dictation only
