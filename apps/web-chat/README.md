# web-chat

Minimal local web chat shell for the Field Assistant engine.

Run the engine:

```bash
uv run uvicorn engine.api.app:create_app --factory --reload
```

Then open:

```text
http://127.0.0.1:8000/chat/
```

Current shell features:

- conversation/session switching
- transcript loading
- streaming assistant deltas
- citation chips
- approval cards with approve/reject actions
- mode switcher
- mobile-friendly composer with a voice placeholder button
