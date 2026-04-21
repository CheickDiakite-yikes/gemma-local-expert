from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
import re

from engine.agent.service import WorkspaceAgentError, WorkspaceAgentService
from engine.audit.service import AuditService
from engine.config.settings import Settings
from engine.context.memory import ConversationMemoryService
from engine.context.service import ConversationContextService
from engine.contracts.api import (
    AgentRun,
    AgentRunStatus,
    AgentRunStep,
    AgentStepStatus,
    AssetAnalysisStatus,
    AssetKind,
    AssetSummary,
    EvidencePacket,
    EvidenceFact,
    EvidenceRef,
    ExecutionMode,
    GroundingStatus,
    RuntimeProfile,
    SourceDomain,
    TranscriptMessage,
)
from engine.contracts.api import ConversationStreamEvent, ConversationTurnRequest, StreamEventType, new_id
from engine.models.document import DocumentAnalysisRequest, DocumentAsset, DocumentRuntime
from engine.models.gateway import ModelGateway
from engine.models.runtime import (
    AssistantGenerationRequest,
    AssistantGenerationResult,
    AssistantRuntime,
)
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
        document_runtime: DocumentRuntime,
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
        self.document_runtime = document_runtime
        self.prompt_builder = prompt_builder
        self.tool_runtime = tool_runtime
        self.workspace_agent = workspace_agent
        self.audit = audit
        self.context_service = ConversationContextService()
        self.memory_service = ConversationMemoryService(runtime)

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
            limit=max(
                self.settings.continuity_history_limit,
                self.settings.conversation_history_limit,
            ),
        )
        recent_memories = self.store.list_conversation_memories(
            turn.conversation_id,
            limit=self.settings.conversation_memory_limit,
        )
        attached_assets = self.store.list_assets(turn.asset_ids)
        conversation_context = self.context_service.build(
            turn_text=turn.text,
            transcript=prior_transcript,
            attached_assets=attached_assets,
            recent_memories=recent_memories,
        )
        contextual_assets = conversation_context.selected_context_assets
        routed_assets = self._merge_assets(attached_assets, contextual_assets)
        attached_asset_ids = [asset.id for asset in attached_assets]
        self.store.append_transcript(
            turn.conversation_id,
            "user",
            turn.text,
            asset_ids=attached_asset_ids,
            turn_id=turn_id,
        )
        route = self.router.decide(
            turn,
            assets=attached_assets,
            contextual_assets=contextual_assets,
            history=history,
            conversation_context=conversation_context,
        )
        if contextual_assets and conversation_context.selected_context_reason:
            route.reasons.append(conversation_context.selected_context_reason)
        policy = self.policy.evaluate(turn, route)
        model_selection = self.models.select(route)
        assistant_asset_ids: list[str] = []
        tool_result: dict[str, object] | None = None
        agent_run: AgentRun | None = None
        workspace_summary: str | None = None
        prepared_tool_name: str | None = None
        prepared_tool_plan = None
        active_pending_approval = self._pending_approval_for_context(conversation_context)
        approval_required = policy.approval_required or bool(
            active_pending_approval and active_pending_approval.status == "pending"
        )

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

        if (
            route.interaction_kind == "draft_follow_up"
            and active_pending_approval
            and getattr(conversation_context, "selected_referent_kind", None) == "pending_output"
        ):
            revised_approval = self._apply_pending_draft_revision(
                approval=active_pending_approval,
                instruction=turn.text,
                conversation_context=conversation_context,
            )
            if revised_approval:
                active_pending_approval = revised_approval
                approval_required = True
                agent_run = (
                    self.store.get_agent_run(revised_approval.run_id)
                    if revised_approval.run_id
                    else None
                )
                self.audit.record(
                    "approval.updated",
                    approval_id=revised_approval.id,
                    tool_name=revised_approval.tool_name,
                    conversation_id=turn.conversation_id,
                    turn_id=turn_id,
                )
                yield self._status_event(
                    conversation_id=turn.conversation_id,
                    turn_id=turn_id,
                    kind="tool",
                    label="Updated local draft",
                    detail="Revised the pending draft while keeping the local save gated.",
                )
                yield ConversationStreamEvent(
                    type=StreamEventType.APPROVAL_REQUIRED,
                    conversation_id=turn.conversation_id,
                    turn_id=turn_id,
                    payload={
                        **revised_approval.model_dump(mode="json"),
                        "run": agent_run.model_dump(mode="json") if agent_run else None,
                    },
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
            self._persist_conversation_memory(
                conversation_id=turn.conversation_id,
                turn_id=turn_id,
                turn_text=turn.text,
                assistant_text=blocked_message,
                interaction_kind=route.interaction_kind,
                conversation_context=conversation_context,
                evidence_packet=None,
                workspace_summary=None,
                tool_name=None,
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
        evidence_packet: EvidencePacket | None = None
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
                evidence_packet = specialist_analysis.evidence_packet
                if not specialist_analysis.available and specialist_analysis.unavailable_reason:
                    yield ConversationStreamEvent(
                        type=StreamEventType.WARNING,
                        conversation_id=turn.conversation_id,
                        turn_id=turn_id,
                        payload={
                            "message": specialist_analysis.unavailable_reason,
                            "source_domain": SourceDomain.IMAGE.value,
                            "execution_mode": evidence_packet.execution_mode.value if evidence_packet else None,
                            "grounding_status": evidence_packet.grounding_status.value if evidence_packet else None,
                            "evidence_packet_id": evidence_packet.id if evidence_packet else None,
                        },
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
                evidence_packet = specialist_analysis.evidence_packet
                if evidence_packet is not None:
                    evidence_packet.artifact_ids = list(specialist_asset_ids)
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
                        payload={
                            "message": specialist_analysis.unavailable_reason,
                            "source_domain": SourceDomain.VIDEO.value,
                            "execution_mode": evidence_packet.execution_mode.value if evidence_packet else None,
                            "grounding_status": evidence_packet.grounding_status.value if evidence_packet else None,
                            "evidence_packet_id": evidence_packet.id if evidence_packet else None,
                        },
                    )
        elif route.specialist_model == "document":
            document_assets = self._collect_document_assets(routed_assets)
            if document_assets:
                yield self._status_event(
                    conversation_id=turn.conversation_id,
                    turn_id=turn_id,
                    kind="document",
                    label="Reviewing the document locally",
                    detail="Running local document extraction before the final answer.",
                )
                specialist_analysis = self.document_runtime.analyze(
                    DocumentAnalysisRequest(
                        conversation_id=turn.conversation_id,
                        turn_id=turn_id,
                        user_text=turn.text,
                        assets=document_assets,
                    )
                )
                evidence_packet = specialist_analysis.evidence_packet
                self.audit.record(
                    "document.analyzed",
                    conversation_id=turn.conversation_id,
                    turn_id=turn_id,
                    backend=specialist_analysis.backend,
                    model_name=specialist_analysis.model_name,
                    available=specialist_analysis.available,
                )
                if specialist_analysis.unavailable_reason:
                    yield ConversationStreamEvent(
                        type=StreamEventType.WARNING,
                        conversation_id=turn.conversation_id,
                        turn_id=turn_id,
                        payload={
                            "message": specialist_analysis.unavailable_reason,
                            "source_domain": SourceDomain.DOCUMENT.value,
                            "execution_mode": evidence_packet.execution_mode.value if evidence_packet else None,
                            "grounding_status": evidence_packet.grounding_status.value if evidence_packet else None,
                            "evidence_packet_id": evidence_packet.id if evidence_packet else None,
                        },
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
                    evidence_packet = self._workspace_evidence_packet(
                        summary_text=workspace_summary,
                        run=agent_run,
                    )
                    if agent_plan.output_tool_name:
                        prepared_tool_name = agent_plan.output_tool_name
                        prepared_tool_plan = self.tool_runtime.plan(
                            turn,
                            prepared_tool_name,
                            results,
                            evidence_packet=evidence_packet,
                            specialist_analysis_text=workspace_summary,
                            context_assets=routed_assets,
                            context_summary=conversation_context.selected_context_summary,
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
                    evidence_packet = self._workspace_evidence_packet(
                        summary_text=workspace_summary,
                        run=agent_run,
                    )
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
                evidence_packet = self._workspace_evidence_packet(
                    summary_text=workspace_summary,
                    run=agent_run,
                    grounded=GroundingStatus.UNAVAILABLE,
                    execution_mode=ExecutionMode.UNAVAILABLE,
                )
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
        tool_feedback: str | None = None
        if planned_tool_name:
            allowed, tool_feedback = self._grounding_allows_tool(
                tool_name=planned_tool_name,
                evidence_packet=evidence_packet,
                user_text=turn.text,
                source_domain=route.source_domain,
            )
            if not allowed:
                yield ConversationStreamEvent(
                    type=StreamEventType.WARNING,
                    conversation_id=turn.conversation_id,
                    turn_id=turn_id,
                    payload={
                        "message": tool_feedback,
                        "source_domain": route.source_domain.value if route.source_domain else None,
                        "execution_mode": evidence_packet.execution_mode.value if evidence_packet else None,
                        "grounding_status": evidence_packet.grounding_status.value if evidence_packet else None,
                        "evidence_packet_id": evidence_packet.id if evidence_packet else None,
                    },
                )
                planned_tool_name = None
        if planned_tool_name:
            tool_plan = prepared_tool_plan or self.tool_runtime.plan(
                turn,
                planned_tool_name,
                results,
                evidence_packet=evidence_packet,
                specialist_analysis_text=(
                    workspace_summary
                    or (specialist_analysis.text if specialist_analysis else None)
                ),
                context_assets=routed_assets,
                context_summary=conversation_context.selected_context_summary,
            )
            yield ConversationStreamEvent(
                type=StreamEventType.TOOL_PROPOSED,
                conversation_id=turn.conversation_id,
                turn_id=turn_id,
                payload={
                    "tool_name": planned_tool_name,
                    "payload": tool_plan.payload,
                    "source_domain": route.source_domain.value if route.source_domain else None,
                    "execution_mode": evidence_packet.execution_mode.value if evidence_packet else None,
                    "grounding_status": evidence_packet.grounding_status.value if evidence_packet else None,
                    "evidence_packet_id": evidence_packet.id if evidence_packet else None,
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
                        "source_domain": route.source_domain.value if route.source_domain else None,
                        "execution_mode": evidence_packet.execution_mode.value if evidence_packet else None,
                        "grounding_status": evidence_packet.grounding_status.value if evidence_packet else None,
                        "evidence_packet_id": evidence_packet.id if evidence_packet else None,
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
                        "source_domain": route.source_domain.value if route.source_domain else None,
                        "execution_mode": evidence_packet.execution_mode.value if evidence_packet else None,
                        "grounding_status": evidence_packet.grounding_status.value if evidence_packet else None,
                        "evidence_packet_id": evidence_packet.id if evidence_packet else None,
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
                        "source_domain": route.source_domain.value if route.source_domain else None,
                        "execution_mode": evidence_packet.execution_mode.value if evidence_packet else None,
                        "grounding_status": evidence_packet.grounding_status.value if evidence_packet else None,
                        "evidence_packet_id": evidence_packet.id if evidence_packet else None,
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
        deterministic_reply = self._multi_output_recall_reply(
            turn.text, conversation_context
        ) or self._missing_output_reply(
            turn_text=turn.text,
            conversation_context=conversation_context,
        ) or self._evidence_guardrail_reply(
            turn_text=turn.text,
            evidence_packet=evidence_packet,
            route=route,
        )
        if not deterministic_reply and tool_feedback and not planned_tool_name:
            deterministic_reply = self._grounding_feedback_reply(
                tool_feedback=tool_feedback,
                evidence_packet=evidence_packet,
            )
        prompt_context = None
        if deterministic_reply and not planned_tool_name:
            generation = AssistantGenerationResult(
                text=deterministic_reply,
                backend="deterministic",
                model_name="continuity-shortcut",
                model_source=None,
            )
        else:
            prompt_context = self.prompt_builder.build(
                turn=turn,
                history=history,
                assets=attached_assets,
                context_assets=contextual_assets,
                conversation_context=conversation_context,
                evidence_packet=evidence_packet,
                specialist_analysis=specialist_analysis.text if specialist_analysis else None,
                workspace_summary=workspace_summary,
                route=route,
                policy=policy,
                model_selection=model_selection,
                results=results,
                tool_result=tool_result
                or (
                    {"message": tool_feedback, "status": "grounding_blocked"}
                    if tool_feedback and not planned_tool_name
                    else None
                ),
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
                    active_topic=conversation_context.active_topic,
                    conversation_context_summary="\n".join(conversation_context.prompt_lines()) or None,
                    selected_memory_topic=conversation_context.selected_memory_topic,
                    selected_memory_summary=conversation_context.selected_memory_summary,
                    referent_kind=conversation_context.selected_referent_kind,
                    referent_tool=conversation_context.selected_referent_tool,
                    referent_title=conversation_context.selected_referent_title,
                    referent_summary=conversation_context.selected_referent_summary,
                    referent_excerpt=conversation_context.selected_referent_excerpt,
                    proposed_tool=planned_tool_name,
                    approval_required=approval_required,
                    tool_result=tool_result
                    or (
                        {"message": tool_feedback, "status": "grounding_blocked"}
                        if tool_feedback and not planned_tool_name
                        else None
                    ),
                    assistant_model_name=model_selection.assistant_model,
                    assistant_model_source=model_selection.assistant_model_source,
                    specialist_model_name=model_selection.specialist_model,
                    evidence_packet=evidence_packet,
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
            source_count=prompt_context.source_count if prompt_context else 0,
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
            evidence_packet=evidence_packet,
        )
        self._persist_conversation_memory(
            conversation_id=turn.conversation_id,
            turn_id=turn_id,
            turn_text=turn.text,
            assistant_text=assistant_message,
            interaction_kind=route.interaction_kind,
            conversation_context=conversation_context,
            evidence_packet=evidence_packet,
            workspace_summary=workspace_summary,
            tool_name=planned_tool_name or conversation_context.selected_referent_tool,
        )

    def _multi_output_recall_reply(
        self,
        turn_text: str,
        conversation_context,
    ) -> str | None:
        if not conversation_context or len(conversation_context.recent_outputs) < 2:
            return None

        lowered = turn_text.lower().strip()
        requested_labels: list[str] = []
        if "report" in lowered:
            requested_labels.append("report")
        if "checklist" in lowered:
            requested_labels.append("checklist")
        if any(token in lowered for token in {"export", "markdown", "document"}):
            requested_labels.append("markdown export")
        if len(set(requested_labels)) < 2:
            return None
        if not any(
            token in lowered
            for token in {"title", "titles", "called", "name", "named", "what was", "what's", "what is"}
        ):
            return None

        typed_outputs: dict[str, str] = {}
        for output in conversation_context.recent_outputs:
            label = self._tool_label(output.tool_name)
            if output.title and label not in typed_outputs:
                typed_outputs[label] = output.title

        parts: list[str] = []
        if "report" in requested_labels and typed_outputs.get("report"):
            parts.append(f'The earlier report is titled "{typed_outputs["report"]}".')
        if "checklist" in requested_labels and typed_outputs.get("checklist"):
            parts.append(f'The checklist is titled "{typed_outputs["checklist"]}".')
        if "markdown export" in requested_labels and typed_outputs.get("markdown export"):
            parts.append(f'The newer export is titled "{typed_outputs["markdown export"]}".')

        if len(parts) < 2:
            return None
        return "\n".join(parts)

    def _missing_output_reply(
        self,
        *,
        turn_text: str,
        conversation_context,
    ) -> str | None:
        if not conversation_context or conversation_context.selected_referent_kind != "missing_output":
            return None
        label = self._tool_label(conversation_context.selected_referent_tool)
        lowered = turn_text.lower().strip()
        if any(
            token in lowered
            for token in {
                "title",
                "called",
                "name",
                "named",
                "shorter",
                "tighten",
                "rename",
                "retitle",
                "edit",
                "revise",
                "rewrite",
                "what is in",
                "what's in",
                "what was in",
            }
        ):
            return (
                f"There is no current {label} yet. "
                "I held off on creating it because the local evidence is not grounded enough for a durable draft. "
                "If you want, tell me to proceed anyway with a partial draft."
            )
        return None

    def _evidence_guardrail_reply(
        self,
        *,
        turn_text: str,
        evidence_packet: EvidencePacket | None,
        route,
    ) -> str | None:
        if evidence_packet is None:
            return None

        lowered = turn_text.lower().strip()

        if (
            evidence_packet.source_domain == SourceDomain.VIDEO
            and any(
                self._contains_grounding_term(lowered, token)
                for token in {"sam", "track", "tracking", "isolation", "isolate", "segment"}
            )
            and evidence_packet.execution_mode != ExecutionMode.FULL
        ):
            return self._tracking_unavailable_reply(evidence_packet)

        if (
            evidence_packet.source_domain == SourceDomain.VIDEO
            and len(evidence_packet.asset_ids) > 1
            and any(
                token in lowered
                for token in {
                    "both videos",
                    "compare both",
                    "compare the videos",
                    "different from the first",
                    "same tools",
                    "same process",
                    "same processes",
                    "same weapon",
                    "weapon-like",
                    "in both",
                }
            )
        ):
            return self._video_comparison_reply(turn_text, evidence_packet)

        if evidence_packet.source_domain == SourceDomain.DOCUMENT and any(
            token in lowered
            for token in {
                "summarize",
                "summarise",
                "extract",
                "section",
                "sections",
                "entity",
                "entities",
                "action item",
                "action items",
                "claims",
                "file understanding",
                "understanding",
            }
        ):
            return self._document_grounded_reply(turn_text, evidence_packet)

        if (
            evidence_packet.source_domain == SourceDomain.DOCUMENT
            and route.interaction_kind == "document"
            and evidence_packet.grounding_status != GroundingStatus.GROUNDED
        ):
            return self._document_grounded_reply(turn_text, evidence_packet)

        return None

    def _tracking_unavailable_reply(self, evidence_packet: EvidencePacket) -> str:
        refs = [ref.ref for ref in evidence_packet.refs[:4] if ref.ref]
        ref_text = ", ".join(refs)
        lines = [
            "I could not run local SAM tracking or video isolation in this profile.",
            "Right now I only have sampled-frame review from the video fallback path.",
        ]
        if ref_text:
            lines.append(f"Sampled timestamps: {ref_text}.")
        if evidence_packet.uncertainties:
            lines.append(evidence_packet.uncertainties[0])
        lines.append(
            "If you want, I can inspect one sampled timestamp more closely or keep comparing the videos conservatively from the fallback evidence."
        )
        return "\n".join(lines)

    def _video_comparison_reply(
        self,
        turn_text: str,
        evidence_packet: EvidencePacket,
    ) -> str:
        lowered = turn_text.lower()
        fact_lines: list[str] = []
        for fact in evidence_packet.facts:
            summary = fact.summary.strip()
            if not summary:
                continue
            refs = ", ".join(ref.ref for ref in fact.refs[:2] if ref.ref)
            if refs:
                summary = f"{summary} ({refs})"
            fact_lines.append(summary)

        lines = ["I compared both videos conservatively from separate local evidence packets."]
        if any(
            token in lowered
            for token in {"weapon", "weapon-like", "tools", "tool", "process", "processes"}
        ):
            lines.append(
                "I cannot confirm the same specific tools, weapon-like items, or repeated processes in both videos from this fallback evidence alone."
            )
        if "different" in lowered or "difference" in lowered:
            lines.append(
                "The strongest grounded difference right now is in the sampled visual/text evidence from each clip, not in any confirmed shared object label."
            )
        if fact_lines:
            lines.append("Grounded comparison points:")
            lines.extend(f"- {line}" for line in fact_lines[:4])
        if evidence_packet.uncertainties:
            lines.append("Limits:")
            lines.extend(f"- {item}" for item in evidence_packet.uncertainties[:2])
        return "\n".join(lines)

    def _contains_grounding_term(self, lowered: str, term: str) -> bool:
        if " " in term:
            return term in lowered
        return re.search(rf"\b{re.escape(term)}\b", lowered) is not None

    def _document_grounded_reply(
        self,
        turn_text: str,
        evidence_packet: EvidencePacket,
    ) -> str:
        lowered = turn_text.lower()
        fact_lines = self._document_fact_lines(evidence_packet)
        capability_lines = [
            "Locally I can read embedded PDF text, render pages and OCR them when embedded text is missing, cite page refs, and draft only from extracted evidence.",
            "I should not claim clean sections, named entities, or action items when the extraction is incomplete or OCR-noisy.",
        ]

        if any(token in lowered for token in {"file understanding", "what kind of file understanding", "do locally"}):
            lines = []
            if evidence_packet.grounding_status == GroundingStatus.UNAVAILABLE:
                lines.append(evidence_packet.summary)
            else:
                lines.append("I reviewed the attached document conservatively.")
                if fact_lines:
                    lines.append("Grounded lines so far:")
                    lines.extend(f"- {line}" for line in fact_lines[:4])
            if evidence_packet.uncertainties:
                lines.append("Limits:")
                lines.extend(f"- {item}" for item in evidence_packet.uncertainties[:2])
            lines.append("Local file understanding:")
            lines.extend(f"- {item}" for item in capability_lines)
            return "\n".join(lines)

        if any(token in lowered for token in {"extract", "section", "sections", "entity", "entities", "action item", "action items", "claims"}):
            lines = [
                "I do not have a clean enough document extraction to list main sections, named entities, or action items with high confidence yet."
            ]
            if fact_lines:
                lines.append("What I can ground so far:")
                lines.extend(f"- {line}" for line in fact_lines[:5])
            if evidence_packet.uncertainties:
                lines.append("Limits:")
                lines.extend(f"- {item}" for item in evidence_packet.uncertainties[:2])
            return "\n".join(lines)

        lines = ["I reviewed the attached document conservatively."]
        if fact_lines:
            lines.append("Grounded points:")
            lines.extend(f"- {line}" for line in fact_lines[:4])
        if evidence_packet.uncertainties:
            lines.append("Limits:")
            lines.extend(f"- {item}" for item in evidence_packet.uncertainties[:2])
        return "\n".join(lines)

    def _document_fact_lines(self, evidence_packet: EvidencePacket) -> list[str]:
        fact_lines: list[str] = []
        for fact in evidence_packet.facts:
            summary = fact.summary.strip()
            if not summary:
                continue
            refs = ", ".join(ref.ref for ref in fact.refs[:2] if ref.ref)
            if refs:
                summary = f"{summary} ({refs})"
            fact_lines.append(summary)
        return fact_lines

    def _grounding_feedback_reply(
        self,
        *,
        tool_feedback: str,
        evidence_packet: EvidencePacket | None,
    ) -> str:
        lines = [tool_feedback]
        if evidence_packet and evidence_packet.facts:
            lines.append("Current grounded evidence:")
            lines.extend(
                f"- {line}" for line in self._document_fact_lines(evidence_packet)[:3]
            )
        return "\n".join(lines)

    def _tool_label(self, tool_name: str | None) -> str:
        mapping = {
            "create_note": "note",
            "create_report": "report",
            "create_message_draft": "message draft",
            "create_checklist": "checklist",
            "create_task": "task",
            "export_brief": "markdown export",
            "log_observation": "observation",
        }
        if tool_name in mapping:
            return mapping[tool_name]
        if not tool_name:
            return "output"
        return tool_name.replace("_", " ")

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

    def _collect_document_assets(self, attached_assets: list) -> list[DocumentAsset]:
        document_assets: list[DocumentAsset] = []
        for asset in attached_assets:
            if asset.kind != AssetKind.DOCUMENT:
                continue
            local_path = self.store.get_asset_local_path(asset.id)
            if not local_path or not Path(local_path).exists():
                continue
            document_assets.append(
                DocumentAsset(
                    asset_id=asset.id,
                    display_name=asset.display_name,
                    local_path=local_path,
                    media_type=asset.media_type,
                    analysis_summary=asset.analysis_summary,
                )
            )
        return document_assets

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

    def _pending_approval_for_context(
        self, conversation_context: object
    ):
        approval_id = getattr(conversation_context, "pending_approval_id", None)
        if not approval_id:
            return None
        approval = self.store.get_approval(approval_id)
        if approval is None or approval.status != "pending":
            return None
        return approval

    def _apply_pending_draft_revision(
        self,
        *,
        approval,
        instruction: str,
        conversation_context,
    ):
        revised_payload = self.tool_runtime.revise_pending_payload(
            approval.tool_name,
            approval.payload,
            instruction,
        )
        if not revised_payload or revised_payload == approval.payload:
            return None
        revised_approval = self.store.update_approval_payload(approval.id, revised_payload)
        summary, excerpt = self.context_service.describe_payload(revised_payload)
        conversation_context.pending_approval_id = revised_approval.id
        conversation_context.pending_approval_tool = revised_approval.tool_name
        conversation_context.pending_approval_summary = summary
        conversation_context.pending_approval_excerpt = excerpt
        if conversation_context.selected_referent_kind == "pending_output":
            conversation_context.selected_referent_tool = revised_approval.tool_name
            conversation_context.selected_referent_title = summary
            conversation_context.selected_referent_summary = summary
            conversation_context.selected_referent_excerpt = excerpt
        return revised_approval

    def _tool_result_summary(self, result: dict[str, object]) -> str:
        if result.get("title") and result.get("entity_type"):
            return f"Created {result['entity_type']}: {result['title']}"
        if result.get("message"):
            return str(result["message"])
        if result.get("status"):
            return f"Tool finished with status {result['status']}."
        return "The local tool completed successfully."

    def _persist_conversation_memory(
        self,
        *,
        conversation_id: str,
        turn_id: str,
        turn_text: str,
        assistant_text: str,
        interaction_kind: str,
        conversation_context,
        evidence_packet: EvidencePacket | None,
        workspace_summary: str | None,
        tool_name: str | None,
    ) -> None:
        source_domain = self._memory_source_domain(
            evidence_packet=evidence_packet,
            workspace_summary=workspace_summary,
            conversation_context=conversation_context,
        )
        asset_ids = (
            list(evidence_packet.asset_ids)
            if evidence_packet is not None
            else list(getattr(conversation_context, "active_asset_ids", []) or [])
        )
        try:
            entry = self.memory_service.build_entry(
                conversation_id=conversation_id,
                turn_id=turn_id,
                user_text=turn_text,
                assistant_text=assistant_text,
                interaction_kind=interaction_kind,
                active_topic=getattr(conversation_context, "active_topic", None),
                source_domain=source_domain,
                asset_ids=asset_ids,
                referent_kind=getattr(conversation_context, "selected_referent_kind", None),
                referent_title=(
                    getattr(conversation_context, "selected_referent_title", None)
                    or getattr(conversation_context, "selected_memory_topic", None)
                ),
                evidence_packet=evidence_packet,
                workspace_summary_text=workspace_summary,
                tool_name=tool_name,
            )
            if entry is None:
                return
            self.store.create_conversation_memory(entry)
        except Exception:
            return

    def _memory_source_domain(
        self,
        *,
        evidence_packet: EvidencePacket | None,
        workspace_summary: str | None,
        conversation_context,
    ) -> SourceDomain | None:
        if evidence_packet is not None:
            return evidence_packet.source_domain
        if workspace_summary:
            return SourceDomain.WORKSPACE
        for candidate in (
            getattr(conversation_context, "selected_referent_kind", None),
            getattr(conversation_context, "selected_context_kind", None),
            getattr(conversation_context, "active_domain", None),
        ):
            mapped = self._source_domain_from_label(candidate)
            if mapped is not None:
                return mapped
        return None

    def _source_domain_from_label(self, label: str | None) -> SourceDomain | None:
        mapping = {
            "image": SourceDomain.IMAGE,
            "video": SourceDomain.VIDEO,
            "document": SourceDomain.DOCUMENT,
            "workspace": SourceDomain.WORKSPACE,
            "conversation": SourceDomain.CONVERSATION,
            "topic": SourceDomain.CONVERSATION,
            "pending_output": SourceDomain.CONVERSATION,
            "saved_output": SourceDomain.CONVERSATION,
        }
        if not label:
            return None
        return mapping.get(label)

    def _workspace_evidence_packet(
        self,
        *,
        summary_text: str | None,
        run: AgentRun,
        grounded: GroundingStatus = GroundingStatus.GROUNDED,
        execution_mode: ExecutionMode = ExecutionMode.FULL,
    ) -> EvidencePacket:
        lines = [
            line.strip()
            for line in (summary_text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
            if line.strip()
        ]
        facts: list[EvidenceFact] = []
        refs: list[str] = []
        section: str | None = None
        overview: str | None = None
        for line in lines:
            lowered = line.lower().strip()
            if lowered.startswith("key points:"):
                section = "facts"
                continue
            if lowered.startswith("files reviewed:"):
                section = "refs"
                continue
            cleaned = line.strip(" -*")
            if not cleaned:
                continue
            if section == "refs":
                refs.append(cleaned)
                continue
            if section == "facts":
                facts.append(EvidenceFact(summary=cleaned))
                continue
            if not lowered.startswith(("overview:", "working title:", "related docs:", "related local docs:")):
                overview = cleaned

        if not facts and overview:
            facts.append(EvidenceFact(summary=overview))

        return EvidencePacket(
            source_domain=SourceDomain.WORKSPACE,
            asset_ids=list(run.artifact_ids),
            profile=(
                RuntimeProfile.LOW_MEMORY
                if self.settings.default_assistant_model == "gemma-4-e2b-it-4bit"
                else RuntimeProfile.FULL_LOCAL
            ),
            execution_mode=execution_mode,
            grounding_status=grounded,
            summary=overview or (facts[0].summary if facts else (summary_text or "Workspace run completed.")),
            facts=facts[:6],
            uncertainties=(
                ["The workspace run did not produce strong local matches."]
                if grounded == GroundingStatus.UNAVAILABLE
                else []
            ),
            refs=[EvidenceRef(label=ref, ref=ref) for ref in refs[:6]],
        )

    def _grounding_allows_tool(
        self,
        *,
        tool_name: str,
        evidence_packet: EvidencePacket | None,
        user_text: str,
        source_domain: SourceDomain | None,
    ) -> tuple[bool, str | None]:
        gated_tools = {"create_note", "create_report", "create_message_draft", "export_brief"}
        if tool_name not in gated_tools:
            return True, None
        if evidence_packet is None:
            if source_domain in {
                SourceDomain.IMAGE,
                SourceDomain.VIDEO,
                SourceDomain.DOCUMENT,
                SourceDomain.WORKSPACE,
            }:
                return (
                    False,
                    "I need current grounded local evidence before I prepare that durable draft. Please keep the asset in scope for this turn or ask me to review it again first.",
                )
            return True, None
        if evidence_packet.grounding_status == GroundingStatus.GROUNDED:
            return True, None
        if evidence_packet.grounding_status == GroundingStatus.PARTIAL:
            lowered = user_text.lower()
            if any(
                phrase in lowered
                for phrase in {"proceed anyway", "draft it anyway", "save it anyway", "use partial evidence"}
            ):
                return True, None
            return (
                False,
                "I need stronger grounded evidence before I prepare that durable draft. I can keep extracting locally or you can explicitly tell me to proceed anyway with a partial draft.",
            )
        return (
            False,
            "I cannot prepare a durable draft from this turn yet because the local evidence path did not produce grounded extraction.",
        )
