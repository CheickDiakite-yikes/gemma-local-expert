from __future__ import annotations

from dataclasses import dataclass

from fastapi import Request

from engine.audit.service import AuditService
from engine.agent.service import WorkspaceAgentService
from engine.config.settings import Settings
from engine.models.document import DocumentRuntime
from engine.models.gateway import ModelGateway
from engine.models.runtime import AssistantRuntime
from engine.models.video import VideoRuntime
from engine.models.vision import VisionRuntime
from engine.orchestrator.prompting import PromptBuilder
from engine.orchestrator.service import OrchestratorService
from engine.persistence.repositories import PersistenceStore
from engine.policy.service import PolicyService
from engine.retrieval.service import RetrievalService
from engine.routing.service import RouterService
from engine.tools.registry import ToolRegistry
from engine.tools.runtime import ToolRuntime


@dataclass(slots=True)
class ServiceContainer:
    settings: Settings
    store: PersistenceStore
    tools: ToolRegistry
    router: RouterService
    policy: PolicyService
    retrieval: RetrievalService
    models: ModelGateway
    runtime: AssistantRuntime
    vision_runtime: VisionRuntime
    video_runtime: VideoRuntime
    document_runtime: DocumentRuntime
    prompt_builder: PromptBuilder
    tool_runtime: ToolRuntime
    workspace_agent: WorkspaceAgentService
    audit: AuditService
    orchestrator: OrchestratorService


def get_container(request: Request) -> ServiceContainer:
    return request.app.state.container
