# Evals

The goal of the eval harness is to validate routing and retrieval behavior before
integrating live models.

Current eval groups:

- `routing`: expected route decisions for representative field requests
- `retrieval`: expected top results from seeded knowledge packs
- `conversation`: multi-turn conversational continuity, multimodal follow-ups, and mixed local-agent behavior

Run:

```bash
uv run python scripts/run_local_eval.py routing
uv run python scripts/run_local_eval.py retrieval
uv run python scripts/run_local_eval.py conversation
```
