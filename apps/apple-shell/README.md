# apple-shell

Native SwiftUI shells for validating the Field Assistant chat UX on macOS and iPhone/iPad.

Targets:

- `FieldAssistantIOS`
- `FieldAssistantMac`

Shared responsibilities:

- session list and switching
- transcript loading
- NDJSON streaming from `/v1/conversations/{id}/turns`
- approval cards and approve/reject flow
- mode switching
- voice placeholder affordance

Default engine URL:

```text
http://127.0.0.1:8000
```

The local engine must be running before launching either app target.
