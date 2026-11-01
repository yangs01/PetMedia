"""HTTP request bodies for the three human review stages."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from app.schemas.content import MasterCopy


class TopicDecisionRequest(BaseModel):
    action: Literal["select", "regenerate", "cancel"]
    selected_topic_id: UUID | None = None
    feedback: str | None = Field(default=None, max_length=5000)

    @model_validator(mode="after")
    def _select_needs_topic(self) -> "TopicDecisionRequest":
        if self.action == "select" and self.selected_topic_id is None:
            raise ValueError("selected_topic_id is required when action is 'select'.")
        return self


class CopyDecisionRequest(BaseModel):
    action: Literal["approve", "revise", "edit_and_approve", "cancel"]
    current_version_id: UUID = Field(
        description="The draft the operator reviewed. Rejected as stale if it is no longer current."
    )
    feedback: str | None = Field(default=None, max_length=5000)
    edited_content: MasterCopy | None = None

    @model_validator(mode="after")
    def _check_action_fields(self) -> "CopyDecisionRequest":
        if self.action == "revise" and not (self.feedback and self.feedback.strip()):
            raise ValueError("feedback is required when action is 'revise'.")
        if self.action == "edit_and_approve" and self.edited_content is None:
            raise ValueError("edited_content is required when action is 'edit_and_approve'.")
        return self


class ImageDecisionRequest(BaseModel):
    action: Literal["approve", "regenerate", "cancel"]
    slide_numbers: list[int] = Field(default_factory=list, max_length=5)
    feedback: str | None = Field(default=None, max_length=5000)
    review_key: str | None = Field(
        default=None,
        description="Optional review_key from the task details; rejected as stale if outdated.",
    )

    @model_validator(mode="after")
    def _regenerate_needs_slides(self) -> "ImageDecisionRequest":
        if self.action == "regenerate" and not self.slide_numbers:
            raise ValueError("slide_numbers is required when action is 'regenerate'.")
        if len(set(self.slide_numbers)) != len(self.slide_numbers):
            raise ValueError("slide_numbers must not contain duplicates.")
        return self


class DecisionAccepted(BaseModel):
    task_id: UUID
    status: str
    decision_id: UUID
    job_id: UUID | None
