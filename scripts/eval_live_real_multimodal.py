from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import httpx


@dataclass(slots=True)
class TurnLog:
    index: int
    user_text: str
    asset_ids: list[str]
    stream_event_types: list[str]
    assistant_text: str
    approval_id: str | None
    approval_tool_name: str | None
    approval_title: str | None
    approval_status: str | None


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run a long live multimodal eval against the local Field Assistant server."
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument(
        "--video-a",
        default="/Users/cheickdiakite/Downloads/Screen Recording 2026-04-11 at 1.42.15\u202fPM.MOV",
    )
    parser.add_argument(
        "--video-b",
        default="/Users/cheickdiakite/Downloads/Screen Recording 2026-04-11 at 2.06.18\u202fPM.MOV",
    )
    parser.add_argument("--document-path", default=None)
    parser.add_argument(
        "--output",
        default="output/evals/live-real-multimodal-2026-04-20.json",
    )
    args = parser.parse_args()

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with httpx.Client(base_url=args.base_url, timeout=300.0) as client:
        capabilities = client.get("/v1/system/capabilities").json()
        video_a = _upload_asset(client, Path(args.video_a), description="real-video-a")
        video_b = _upload_asset(client, Path(args.video_b), description="real-video-b")
        document = None
        if args.document_path:
            document = _upload_asset(client, Path(args.document_path), description="real-document")

        conversation = client.post(
            "/v1/conversations",
            json={"title": "Live Real Multimodal Eval", "mode": "research"},
        ).json()
        conversation_id = conversation["id"]

        scenario: list[tuple[str, list[str]]] = [
            (
                "Review the first attached video conservatively. Describe only what you can directly support from the clip.",
                [video_a["id"]],
            ),
            (
                "In that same first video, what tools, objects, or weapon-like items do you think might be present? Label your confidence clearly.",
                [],
            ),
            (
                "Do you think you can identify any specific weapon names from the first video, or is that too uncertain? Be explicit about uncertainty.",
                [],
            ),
            (
                "What repeated process, workflow, or behavior do you infer from the first video, if any?",
                [],
            ),
            (
                "Go back to that first video and isolate the segments or sampled frames where the most concerning object appears.",
                [],
            ),
            (
                "Use local SAM tracking or local video isolation on the first video for the suspected object or person holding it.",
                [],
            ),
            (
                "If full tracking is not available, tell me exactly what local fallback you can do right now and what artifacts you can generate.",
                [],
            ),
            (
                "Now review the second attached video conservatively and tell me what looks meaningfully different from the first one.",
                [video_b["id"]],
            ),
            (
                "Compare both videos. Are the same tools, processes, or possible weapon-like items present in both?",
                [],
            ),
            (
                "Go back to the first video. What is the strongest claim you can make, and what is the weakest claim you should avoid over-stating?",
                [],
            ),
            (
                "Tag the first video with structured labels for people, tools, possible weapons, actions, and confidence.",
                [],
            ),
            (
                "Draft a short message to a supervisor summarizing the first video conservatively, especially any potential weapon or process concerns.",
                [],
            ),
            (
                "Keep that same message draft, but make it shorter, more neutral, and clearer about uncertainty before we save it.",
                [],
            ),
            (
                "Prepare a report comparing both videos, call out any possible weapon or process findings conservatively, and save it as a report.",
                [],
            ),
            (
                "What title are you using for that report draft right now?",
                [],
            ),
            (
                "Keep that same report draft, but make the title shorter and clearer before we save it.",
                [],
            ),
            (
                "Talk normally with me for a second: after both videos, what are you still most uncertain about?",
                [],
            ),
        ]

        if document:
            scenario.extend(
                [
                    (
                        "Now switch to the attached document. Summarize it conservatively and tell me what kind of file understanding you can do locally.",
                        [document["id"]],
                    ),
                    (
                        "From that same document, extract the main sections, key named entities, and any clear action items or claims.",
                        [],
                    ),
                ]
            )

        logs: list[TurnLog] = []
        pending_approval_id: str | None = None
        for index, (text, asset_ids) in enumerate(scenario, start=1):
            turn_response = client.post(
                f"/v1/conversations/{conversation_id}/turns",
                json={
                    "conversation_id": conversation_id,
                    "mode": "research",
                    "text": text,
                    "asset_ids": asset_ids,
                    "enabled_knowledge_pack_ids": [],
                    "response_preferences": {
                        "style": "normal",
                        "citations": True,
                        "audio_reply": False,
                    },
                },
            )
            turn_response.raise_for_status()
            stream_events = _parse_stream_events(turn_response.text)
            messages = client.get(f"/v1/conversations/{conversation_id}/messages").json()
            assistant_message = next(
                (message for message in reversed(messages) if message["role"] == "assistant"),
                None,
            )
            approval = assistant_message.get("approval") if assistant_message else None
            if approval and approval.get("status") == "pending":
                pending_approval_id = approval["id"]

            logs.append(
                TurnLog(
                    index=index,
                    user_text=text,
                    asset_ids=asset_ids,
                    stream_event_types=[event.get("type", "") for event in stream_events],
                    assistant_text=(assistant_message.get("content") or "") if assistant_message else "",
                    approval_id=approval.get("id") if approval else None,
                    approval_tool_name=(approval.get("payload") or {}).get("tool_name") if approval else None,
                    approval_title=((approval.get("payload") or {}).get("payload") or {}).get("title")
                    if approval
                    else None,
                    approval_status=approval.get("status") if approval else None,
                )
            )

            if index == 13 and pending_approval_id:
                _approve_pending(client, pending_approval_id)
                pending_approval_id = None

        if pending_approval_id:
            _approve_pending(client, pending_approval_id)

        transcript = client.get(f"/v1/conversations/{conversation_id}/messages").json()
        runs = client.get(f"/v1/conversations/{conversation_id}/runs").json()

    payload = {
        "capabilities": capabilities,
        "conversation_id": conversation_id,
        "assets": {
            "video_a": video_a,
            "video_b": video_b,
            "document": document,
        },
        "turn_logs": [asdict(item) for item in logs],
        "transcript": transcript,
        "runs": runs,
    }
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Wrote eval log to {output_path}")
    print(f"Conversation: {conversation_id}")
    print("Turn overview:")
    for item in logs:
        print(
            f"{item.index:02d}. approval={item.approval_tool_name or '-'} "
            f"status={item.approval_status or '-'} "
            f"text={item.assistant_text[:140].replace(chr(10), ' ')}"
        )


def _upload_asset(client: httpx.Client, file_path: Path, *, description: str) -> dict[str, Any]:
    file_path = file_path.expanduser()
    if not file_path.exists():
        raise FileNotFoundError(f"Missing asset: {file_path}")

    with file_path.open("rb") as handle:
        response = client.post(
            "/v1/assets/upload",
            data={"care_context": "general", "description": description},
            files={"file": (file_path.name, handle, _media_type(file_path))},
        )
    response.raise_for_status()
    return response.json()["asset"]


def _approve_pending(client: httpx.Client, approval_id: str) -> None:
    response = client.post(
        f"/v1/approvals/{approval_id}/decisions",
        json={"action": "approve", "edited_payload": {}},
    )
    response.raise_for_status()


def _media_type(path: Path) -> str:
    lowered = path.suffix.lower()
    if lowered == ".mov":
        return "video/quicktime"
    if lowered == ".mp4":
        return "video/mp4"
    if lowered == ".webm":
        return "video/webm"
    if lowered == ".pdf":
        return "application/pdf"
    if lowered == ".txt":
        return "text/plain"
    if lowered in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if lowered == ".png":
        return "image/png"
    return "application/octet-stream"


def _parse_stream_events(raw_text: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for line in raw_text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            events.append({"type": "unparsed", "raw": line})
    return events


if __name__ == "__main__":
    main()
