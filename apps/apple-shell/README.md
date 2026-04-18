# apple-shell

Native SwiftUI shells for validating the Field Assistant experience on macOS and
iPhone/iPad.

Targets:

- `FieldAssistantIOS`
- `FieldAssistantMac`

Shared responsibilities:

- session list and switching
- transcript loading
- NDJSON streaming from `/v1/conversations/{id}/turns`
- approval cards and approve/reject flow
- a unified assistant surface
- voice placeholder affordance
- native Apple UX experimentation

Default engine URL:

```text
http://127.0.0.1:8000
```

The local engine must be running before launching either app target.

Current status:

- useful as a native interaction prototype
- not yet the most complete shell in the repo
- intended to inform the longer-term native product direction
