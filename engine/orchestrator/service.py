from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

from engine.agent.service import WorkspaceAgentError, WorkspaceAgentService
from engine.audit.service import AuditService
from engine.config.settings import Settings
from engine.contracts.api import (
    AgentRun,
    AgentRunStatus,
    AgentRunStep,
    AgentStepStatus,
    AssetAnalysisStatus,
    AssetKind,
    AssetSummary,
    TranscriptMessage,
)
from engine.contracts.api import ConversationStreamEvent, ConversationTurnRequest, StreamEventType, new_id
from engine.models.gateway import ModelGateway
from engine.models.runtime import AssistantGenerationRequest, AssistantRuntime
from engine.models.video import VideoAnalysisRequest, VideoAsset, VideoRuntime
from engine.models.vision import VisionAnalysisRequest, VisionAsset, VisionRuntime
from engine.orchestrator.prompting import PromptBuilder
from engine.persistence.repositories import PersistenceStore
from engine.policy.service import PolicyService
from engine.retrieval.service import RetrievalService
from engine.routing.service import RouterService
from engine.tools.runtime import ToolRuntime


class OrchestratorService:
    def __init__(
        self,
        *,
        settings: Settings,
        store: PersistenceStore,
        router: RouterService,
        policy: PolicyService,
        retrieval: RetrievalService,
        models: ModelGateway,
        runtime: AssistantRuntime,
        vision_runtime: VisionRuntime,
        video_runtime: VideoRuntime,
        prompt_builder: PromptBuilder,
        tool_runtime: ToolRuntime,
        workspace_agent: WorkspaceAgentService,
        audit: AuditService,
    ) -> None:
        self.settings = settings
        self.store = store
        self.router = router
        self.policy = policy
        self.retrieval = retrieval
        self.models = models
        self.runtime = runtime
        self.vision_runtime = vision_runtime
        self.video_runtime = video_runtime
        self.prompt_builder = prompt_builder
        self.tool_runtime = tool_runtime
        self.workspace_agent = workspace_agent
        self.audit = audit

    async def stream_turn(
        self, turn: ConversationTurnRequest
    ) -> AsyncIterator[ConversationStreamEvent]:
        self.store.ensure_conversation(turn.conversation_id, turn.mode)
        turn_id = new_id("turn")
        history = self.store.list_recent_messages(
            turn.conversation_id,
            limit=self.settings.conversation_history_limit,
        )
        prior_transcript = self.store.list_transcript(
            turn.conversation_id,
            limit=self.settings.conversation_history_limit,
        )
        attached_assets = self.store.list_assets(turn.asset_ids)
        contextual_assets = self._recent_media_context_assets(prior_transcript)
        if attached_assets:
            contextual_assets = []
        routed_assets = self._merge_assets(attached_assets, contextual_assets)
        attached_asset_ids = [asset.id for asset in attached_assets]
        self.store.append_transcript(
            turn.conversation_id,
            "user",
            turn.text,
            asset_ids=attached_asset_ids,
            turn_id=turn_id,
        )
        route = self.router.decide(turn, assets=routed_assets, history=history)
        if contextual_assets:
            route.reasons.append("Using recent image attachment from conversation context.")
        policy = self.policy.evaluate(turn, route)
        model_selection = self.models.select(route)
        assistant_asset_ids: list[str] = []
        tool_result: dict[str, object] | None = None
        agent_run: AgentRun | None = None
        workspace_summary: str | None = None
        prepared_tool_name: str | None = None
        prepared_tool_plan = None
        approval_required = policy.approval_required

        self.audit.record(
            "turn.received",
            conversation_id=turn.conversation_id,
            turn_id=turn_id,
            mode=turn.mode.value,
            route_reasons=route.reasons,
        )

        yield self._status_event(
            conversation_id=turn.conversation_id,
            turn_id=turn_id,
            kind="route",
            label="Routing locally",
            detail="Selecting retrieval, image, and tool paths for this turn.",
        )

        for warning in policy.warnings:
            yield ConversationStreamEvent(
                type=StreamEventType.WARNING,
                conversation_id=turn.conversation_id,
                turn_id=turn_id,
                payload={"message": warning},
            )

        if policy.blocked:
            blocked_message = (
                "Request blocked by policy. Open an explicit medical session before using "
                "medical specialist workflows."
            )
            for event in self._message_events(
                conversation_id=turn.conversation_id,
                turn_id=turn_id,
                text=blocked_message,
                assets=[],
                models=model_selection.model_dump(),
            ):
                yield event
            self.store.append_transcript(
                turn.conversation_id,
                "assistant",
                blocked_message,
                turn_id=turn_id,
            )
            return

        results = []
        if route.needs_retrieval:
            yield self._status_event(
                conversation_id=turn.conversation_id,
                turn_id=turn_id,
                kind="retrieval",
                label="Reviewing local material",
                detail="Checking local material that may help with this reply.",
            )
            results = self.retrieval.retrieve_for_turn(turn)
            for result in results:
                yield ConversationStreamEvent(
                    type=StreamEventType.CITATION_ADDED,
                    conversation_id=turn.conversation_id,
                    turn_id=turn_id,
                    payload=result.model_dump(),
                )

        specialist_analysis = None
        specialist_asset_ids: list[str] = []
        if route.specialist_model in {"paligemma", "medgemma"} and model_selection.specialist_model:
            visual_assets = self._collect_visual_assets(routed_assets)
            if visual_assets:
                yield self._status_event(
                    conversation_id=turn.conversation_id,
                    turn_id=turn_id,
                    kind="vision",
                    label="Inspecting the image locally",
                    detail=f"Using {route.specialist_model} routing for visual context.",
                )
                specialist_analysis = self.vision_runtime.analyze(
                    VisionAnalysisRequest(
                        conversation_id=turn.conversation_id,
                        turn_id=turn_id,
                        mode=turn.mode,
                        user_text=turn.text,
                        specialist_model_name=model_selection.specialist_model,
                        specialist_model_source=model_selection.specialist_model_source,
                        assets=visual_assets,
                        max_tokens=self.settings.specialist_max_tokens,
                        temperature=0.0,
                    )
                )
                self.audit.record(
                    "specialist.analyzed",
                    conversation_id=turn.conversation_id,
                    turn_id=turn_id,
                    backend=specialist_analysis.backend,
                    model_name=specialist_analysis.model_name,
                    available=specialist_analysis.available,
                )
                if not specialist_analysis.available and specialist_analysis.unavailable_reason:
                    yield ConversationStreamEvent(
                        type=StreamEventType.WARNING,
                        conversation_id=turn.conversation_id,
                        turn_id=turn_id,
                        payload={"message": specialist_analysis.unavailable_reason},
                    )
        elif route.specialist_model == "sam3" and model_selection.tracking_model:
            video_assets = self._collect_video_assets(routed_assets)
            if video_assets:
                yield self._status_event(
                    conversation_id=turn.conversation_id,
                    turn_id=turn_id,
                    kind="video",
                    label="Reviewing the video locally",
                    detail="Running local video analysis and preparing review artifacts.",
                )
                specialist_analysis = self.video_runtime.analyze(
                    VideoAnalysisRequest(
                        conversation_id=turn.conversation_id,
                        turn_id=turn_id,
                        mode=turn.mode,
                        user_text=turn.text,
                        tracking_model_name=model_selection.tracking_model,
                        tracking_model_source=model_selection.tracking_model_source,
                        assets=video_assets,
                        sample_frames=self.settings.video_sample_frames,
                        resolution=self.settings.tracking_resolution,
                        detect_every=self.settings.tracking_detect_every,
                    )
                )
                specialist_asset_ids = self._persist_specialist_artifacts(
                    specialist_analysis.artifacts
                )
                self.audit.record(
                    "video.analyzed",
                    conversation_id=turn.conversation_id,
                    turn_id=turn_id,
                    backend=specialist_analysis.backend,
                    model_name=specialist_analysis.model_name,
                    available=specialist_analysis.available,
                )
                if not specialist_analysis.available and specialist_analysis.unavailable_reason:
                    yield ConversationStreamEvent(
                        type=StreamEventType.WARNING,
                        conversation_id=turn.conversation_id,
                        turn_id=turn_id,
                        payload={"message": specialist_analysis.unavailable_reason},
                    )

        if route.agent_run:
            yield self._status_event(
                conversation_id=turn.conversation_id,
                turn_id=turn_id,
                kind="agent",
                label="Planning workspace run",
                detail="Preparing a bounded local workspace run before the final answer.",
            )
            try:
                agent_plan = self.workspace_agent.plan(turn.text)
                agent_run = self.store.create_agent_run(
                    turn.conversation_id,
                    turn_id,
                    turn.text,
                    agent_plan.scope_root,
                    status=AgentRunStatus.RUNNING,
                    plan_steps=agent_plan.steps,
                )
                agent_state = self.workspace_agent.create_state(agent_plan)
                self.audit.record(
                    "agent.run.created",
                    conversation_id=turn.conversation_id,
                    turn_id=turn_id,
                    run_id=agent_run.id,
                    scope_root=agent_plan.scope_root,
                )

                for step in agent_plan.steps:
                    step_result = self.workspace_agent.execute_step(agent_plan, agent_state, step)
                    next_status = AgentRunStatus.RUNNING
                    if step_result.status == AgentStepStatus.BLOCKED:
                        next_status = AgentRunStatus.BLOCKED
                    elif step_result.status == AgentStepStatus.FAILED:
                        next_status = AgentRunStatus.FAILED

                    agent_run = self.store.update_agent_run(
                        agent_run.id,
                        status=next_status,
                        executed_steps=agent_run.executed_steps + [step_result],
                    )
                    self.audit.record(
                        "agent.step.completed",
                        conversation_id=turn.conversation_id,
                        turn_id=turn_id,
                        run_id=agent_run.id,
                        step_kind=step_result.kind,
                        step_status=step_result.status.value,
                    )
                    yield self._status_event(
                        conversation_id=turn.conversation_id,
                        turn_id=turn_id,
                        kind="agent",
                        label=step_result.title,
                        detail=step_result.detail or "Workspace step complete.",
                        extra={
                            "run_id": agent_run.id,
                            "run_status": agent_run.status.value,
                            "run": agent_run.model_dump(mode="json"),
                            "step": step_result.model_dump(mode="json"),
                        },
                    )
                    if agent_run.status in {AgentRunStatus.BLOCKED, AgentRunStatus.FAILED}:
                        break

                workspace_summary = agent_state.summary_text or agent_run.result_summary
                if agent_run.status == AgentRunStatus.RUNNING and workspace_summary:
                    if agent_plan.output_tool_name:
                        prepared_tool_name = agent_plan.output_tool_name
                        prepared_tool_plan = self.tool_runtime.plan(
                            turn,
                            prepared_tool_name,
                            results,
                            specialist_analysis_text=workspace_summary,
                            context_assets=routed_assets,
                        )
                        approval_required = (
                            self.policy.tools.requires_confirmation(prepared_tool_name)
                            or approval_required
                        )
                        agent_run = self.store.update_agent_run(
                            agent_run.id,
                            result_summary=self._compact_agent_summary(workspace_summary),
                        )
                    else:
                        agent_run = self.store.update_agent_run(
                            agent_run.id,
                            status=AgentRunStatus.COMPLETED,
                            result_summary=self._compact_agent_summary(workspace_summary),
                        )
                elif agent_run.status == AgentRunStatus.RUNNING:
                    agent_run = self.store.update_agent_run(
                        agent_run.id,
                        status=AgentRunStatus.COMPLETED,
                        result_summary="The workspace run completed without strong matching files.",
                    )
                    workspace_summary = agent_run.result_summary
                    yield self._status_event(
                        conversation_id=turn.conversation_id,
                        turn_id=turn_id,
                        kind="agent",
                        label="Workspace run complete",
                        detail=agent_run.result_summary,
                        extra={
                            "run_id": agent_run.id,
                            "run_status": agent_run.status.value,
                            "run": agent_run.model_dump(mode="json"),
                        },
                    )
            except WorkspaceAgentError as exc:
                agent_run = self.store.create_agent_run(
                    turn.conversation_id,
                    turn_id,
                    turn.text,
                    self.settings.workspace_root,
                    status=AgentRunStatus.BLOCKED,
                    result_summary=str(exc),
                )
                workspace_summary = str(exc)
                yield self._status_event(
                    conversation_id=turn.conversation_id,
                    turn_id=turn_id,
                    kind="agent",
                    label="Workspace run blocked",
                    detail=str(exc),
                    extra={
                        "run_id": agent_run.id,
                        "run_status": agent_run.status.value,
                        "run": agent_run.model_dump(mode="json"),
                    },
                )
                self.audit.record(
                    "agent.run.blocked",
                    conversation_id=turn.conversation_id,
                    turn_id=turn_id,
                    run_id=agent_run.id,
                    reason=str(exc),
                )

        planned_tool_name = prepared_tool_name or route.proposed_tool
        if planned_tool_name:
            tool_plan = prepared_tool_plan or self.tool_runtime.plan(
                turn,
                planned_tool_name,
                results,
                specialist_analysis_text=(
                    workspace_summary
                    or (specialist_analysis.text if specialist_analysis else None)
                ),
                context_assets=routed_assets,
            )
            yield ConversationStreamEvent(
                type=StreamEventType.TOOL_PROPOSED,
                conversation_id=turn.conversation_id,
                turn_id=turn_id,
                payload={
                    "tool_name": planned_tool_name,
                    "payload": tool_plan.payload,
                    "run_id": agent_run.id if agent_run else None,
                    "run": agent_run.model_dump(mode="json") if agent_run else None,
                },
            )
            if approval_required:
                yield self._status_event(
                    conversation_id=turn.conversation_id,
                    turn_id=turn_id,
                    kind="tool",
                    label="Preparing a draft for approval",
                    detail="A local write is ready for review before it runs.",
                    extra={"run_id": agent_run.id if agent_run else None},
                )
                approval = self.store.create_approval(
                    turn.conversation_id,
                    turn_id,
                    planned_tool_name,
                    reason="Tool writes durable state or enters a gated workflow.",
                    payload=tool_plan.payload,
                    run_id=agent_run.id if agent_run else None,
                )
                if agent_run:
                    agent_run = self.store.update_agent_run(
                        agent_run.id,
                        status=AgentRunStatus.AWAITING_APPROVAL,
                        approval_id=approval.id,
                        result_summary=f"Awaiting approval to run `{planned_tool_name}` from workspace findings.",
                    )
                self.audit.record(
                    "approval.created",
                    approval_id=approval.id,
                    tool_name=approval.tool_name,
                    conversation_id=turn.conversation_id,
                )
                yield ConversationStreamEvent(
                    type=StreamEventType.APPROVAL_REQUIRED,
                    conversation_id=turn.conversation_id,
                    turn_id=turn_id,
                    payload={
                        **approval.model_dump(mode="json"),
                        "run": agent_run.model_dump(mode="json") if agent_run else None,
                    },
                )
            else:
                yield self._status_event(
                    conversation_id=turn.conversation_id,
                    turn_id=turn_id,
                    kind="tool",
                    label="Running a local helper",
                    detail=f"Executing {planned_tool_name} inside the local engine.",
                    extra={"run_id": agent_run.id if agent_run else None},
                )
                yield ConversationStreamEvent(
                    type=StreamEventType.TOOL_STARTED,
                    conversation_id=turn.conversation_id,
                    turn_id=turn_id,
                    payload={
                        "tool_name": planned_tool_name,
                        "payload": tool_plan.payload,
                        "run_id": agent_run.id if agent_run else None,
                        "run": agent_run.model_dump(mode="json") if agent_run else None,
                    },
                )
                tool_result = self.tool_runtime.execute(planned_tool_name, tool_plan.payload)
                assistant_asset_ids = [
                    asset_id
                    for asset_id in tool_result.get("asset_ids", [])
                    if isinstance(asset_id, str)
                ]
                completed_assets = self.store.list_assets(assistant_asset_ids)
                if agent_run:
                    agent_run = self.store.update_agent_run(
                        agent_run.id,
                        status=AgentRunStatus.COMPLETED,
                        artifact_ids=assistant_asset_ids,
                        result_summary=self._tool_result_summary(tool_result),
                    )
                yield ConversationStreamEvent(
                    type=StreamEventType.TOOL_COMPLETED,
                    conversation_id=turn.conversation_id,
                    turn_id=turn_id,
                    payload={
                        "tool_name": planned_tool_name,
                        "result": tool_result,
                        "assets": [asset.model_dump(mode="json") for asset in completed_assets],
                        "run_id": agent_run.id if agent_run else None,
                        "run": agent_run.model_dump(mode="json") if agent_run else None,
                    },
                )
                self.audit.record(
                    "tool.executed",
                    conversation_id=turn.conversation_id,
                    turn_id=turn_id,
                    tool_name=planned_tool_name,
                    result=tool_result,
                )

        yield self._status_event(
            conversation_id=turn.conversation_id,
            turn_id=turn_id,
            kind="compose",
            label="Drafting the answer",
            detail="Turning grounded context into the final response.",
        )
        prompt_context = self.prompt_builder.build(
            turn=turn,
            history=history,
            assets=attached_assets,
            context_assets=contextual_assets,
            specialist_analysis=specialist_analysis.text if specialist_analysis else None,
            workspace_summary=workspace_summary,
            route=route,
            policy=policy,
            model_selection=model_selection,
            results=results,
            tool_result=tool_result,
        )

        generation = self.runtime.generate(
            AssistantGenerationRequest(
                conversation_id=turn.conversation_id,
                turn_id=turn_id,
                mode=turn.mode,
                user_text=turn.text,
                messages=prompt_context.messages,
                citations=results,
                interaction_kind=route.interaction_kind,
                is_follow_up=route.is_follow_up,
                proposed_tool=planned_tool_name,
                approval_required=approval_required,
                tool_result=tool_result,
                assistant_model_name=model_selection.assistant_model,
                assistant_model_source=model_selection.assistant_model_source,
                specialist_model_name=model_selection.specialist_model,
                specialist_analysis_text=specialist_analysis.text if specialist_analysis else None,
                workspace_summary_text=workspace_summary,
                max_tokens=self.settings.assistant_max_tokens,
                temperature=self.settings.assistant_temperature,
                top_p=self.settings.assistant_top_p,
            )
        )
        self.audit.record(
            "assistant.generated",
            conversation_id=turn.conversation_id,
            turn_id=turn_id,
            backend=generation.backend,
            assistant_model=generation.model_name,
            source_count=prompt_context.source_count,
        )
        assistant_message = generation.text
        completed_asset_ids = assistant_asset_ids + specialist_asset_ids
        completed_assets = self.store.list_assets(completed_asset_ids)
        for event in self._message_events(
            conversation_id=turn.conversation_id,
            turn_id=turn_id,
            text=assistant_message,
            assets=completed_assets,
            models={
                **model_selection.model_dump(),
                "assistant_backend": generation.backend,
                "assistant_model_source": generation.model_source,
                "specialist_backend": specialist_analysis.backend if specialist_analysis else None,
                "specialist_model_source": (
                    specialist_analysis.model_source if specialist_analysis else None
                ),
            },
        ):
            yield event
        self.store.append_transcript(
            turn.conversation_id,
            "assistant",
            assistant_message,
            turn_id=turn_id,
            asset_ids=completed_asset_ids,
        )

    def _merge_assets(
        self,
        attached_assets: list[AssetSummary],
        contextual_assets: list[AssetSummary],
    ) -> list[AssetSummary]:
        combined = attached_assets + contextual_assets
        seen_ids: set[str] = set()
        merged: list[AssetSummary] = []
        for asset in combined:
            if asset.id in seen_ids:
                continue
            seen_ids.add(asset.id)
            merged.append(asset)
        return merged

    def _recent_media_context_assets(
        self, transcript: list[TranscriptMessage]
    ) -> list[AssetSummary]:
        for message in reversed(transcript):
            media_assets = [
                asset for asset in message.assets if asset.kind in {AssetKind.IMAGE, AssetKind.VIDEO}
            ]
            if media_assets:
                return media_assets
        return []

    def _collect_visual_assets(self, attached_assets: list) -> list[VisionAsset]:
        visual_assets: list[VisionAsset] = []
        for asset in attached_assets:
            if asset.kind != AssetKind.IMAGE:
                continue
            local_path = self.store.get_asset_local_path(asset.id)
            if not local_path or not Path(local_path).exists():
                continue
            visual_assets.append(
                VisionAsset(
                    asset_id=asset.id,
                    display_name=asset.display_name,
                    local_path=local_path,
                    kind=asset.kind,
                    media_type=asset.media_type,
                    care_context=asset.care_context.value,
                    analysis_summary=asset.analysis_summary,
                )
            )
        return visual_assets

    def _collect_video_assets(self, attached_assets: list) -> list[VideoAsset]:
        video_assets: list[VideoAsset] = []
        for asset in attached_assets:
            if asset.kind != AssetKind.VIDEO:
                continue
            local_path = self.store.get_asset_local_path(asset.id)
            if not local_path or not Path(local_path).exists():
                continue
            video_assets.append(
                VideoAsset(
                    asset_id=asset.id,
                    display_name=asset.display_name,
                    local_path=local_path,
                    kind=asset.kind,
                    media_type=asset.media_type,
                    care_context=asset.care_context.value,
                    analysis_summary=asset.analysis_summary,
                )
            )
        return video_assets

    def _persist_specialist_artifacts(self, artifacts: list) -> list[str]:
        asset_ids: list[str] = []
        for artifact in artifacts:
            path = Path(artifact.local_path)
            if not path.exists():
                continue
            asset = self.store.create_asset_record(
                asset_id=new_id("asset"),
                source_path=path.name,
                display_name=artifact.display_name,
                description="Derived local artifact from specialist media analysis.",
                media_type=artifact.media_type,
                kind=artifact.kind,
                byte_size=path.stat().st_size,
                local_path=str(path),
                care_context=artifact.care_context,
                analysis_status=AssetAnalysisStatus.READY,
                analysis_summary=artifact.analysis_summary,
            )
            asset_ids.append(asset.id)
        return asset_ids

    def _status_event(
        self,
        *,
        conversation_id: str,
        turn_id: str,
        kind: str,
        label: str,
        detail: str,
        extra: dict[str, object] | None = None,
    ) -> ConversationStreamEvent:
        payload = {"kind": kind, "label": label, "detail": detail}
        if extra:
            payload.update(extra)
        return ConversationStreamEvent(
            type=StreamEventType.TURN_STATUS,
            conversation_id=conversation_id,
            turn_id=turn_id,
            payload=payload,
        )

    def _message_events(
        self,
        *,
        conversation_id: str,
        turn_id: str,
        text: str,
        assets: list[AssetSummary],
        models: dict[str, str | None],
    ) -> list[ConversationStreamEvent]:
        events: list[ConversationStreamEvent] = []
        for chunk in self._chunk_text(text):
            events.append(
                ConversationStreamEvent(
                    type=StreamEventType.ASSISTANT_DELTA,
                    conversation_id=conversation_id,
                    turn_id=turn_id,
                    payload={"text": chunk},
                )
            )

        events.append(
            ConversationStreamEvent(
                type=StreamEventType.ASSISTANT_MESSAGE_COMPLETED,
                conversation_id=conversation_id,
                turn_id=turn_id,
                payload={
                    "text": text,
                    "models": models,
                    "assets": [asset.model_dump(mode="json") for asset in assets],
                },
            )
        )
        return events

    def _chunk_text(self, text: str) -> list[str]:
        size = self.settings.max_stream_chunk_chars
        return [text[index : index + size] for index in range(0, len(text), size)] or [""]

    def _compact_agent_summary(self, summary: str) -> str:
        cleaned = " ".join(summary.split())
        if len(cleaned) <= 220:
            return cleaned
        return cleaned[:219].rstrip() + "…"

    def _tool_result_summary(self, result: dict[str, object]) -> str:
        if result.get("title") and result.get("entity_type"):
            return f"Created {result['entity_type']}: {result['title']}"
        if result.get("message"):
            return str(result["message"])
        if result.get("status"):
            return f"Tool finished with status {result['status']}."
        return "The local tool completed successfully."
