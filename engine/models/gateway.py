from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from engine.config.settings import Settings
from engine.routing.service import RouteDecision


class ModelRouteSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assistant_model: str
    assistant_model_source: str | None = None
    embedding_model: str
    specialist_model: str | None = None
    specialist_model_source: str | None = None
    tracking_model: str | None = None
    tracking_model_source: str | None = None
    tool_planner_model: str | None = None


class ModelGateway:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def select(self, route: RouteDecision) -> ModelRouteSelection:
        specialist = None
        specialist_source = None
        if route.specialist_model == "translategemma":
            specialist = self.settings.default_translation_model
        elif route.specialist_model == "paligemma":
            specialist = self.settings.default_vision_model
            specialist_source = self.settings.vision_model_source
        elif route.specialist_model == "medgemma":
            specialist = self.settings.default_medical_model
            specialist_source = self.settings.medical_model_source

        tracking_model = None
        tracking_model_source = None
        if route.specialist_model == "sam3":
            tracking_model = self.settings.default_tracking_model
            tracking_model_source = self.settings.tracking_model_source

        tool_planner = None
        if route.proposed_tool and self.settings.enable_function_gemma:
            tool_planner = self.settings.default_function_model

        return ModelRouteSelection(
            assistant_model=self.settings.default_assistant_model,
            assistant_model_source=self.settings.assistant_model_source,
            embedding_model=self.settings.default_embedding_model,
            specialist_model=specialist,
            specialist_model_source=specialist_source,
            tracking_model=tracking_model,
            tracking_model_source=tracking_model_source,
            tool_planner_model=tool_planner,
        )
