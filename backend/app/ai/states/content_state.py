"""Graph state and the human decision schemas.

State holds only ids and small workflow values, all JSON-friendly. Content and
images live in the business database and storage.
"""

from typing import Any, Literal, TypedDict

from pydantic import BaseModel, Field, model_validator


class ContentState(TypedDict, total=False):
    task_id: str
    brand_id: str
    product_ids: list[str]
    channels: list[str]
    image_count: int

    topic_batch_number: int
    topic_candidate_ids: list[str]
    topic_feedback: str | None
    selected_topic_id: str | None

    current_content_version_id: str | None
    approved_content_version_id: str | None
    # Set when a new draft must be produced from the current one. None means first draft.
    pending_revision: dict[str, Any] | None
    revision_count: int
    copy_auto_fix_count: int

    carousel_plan_id: str | None
    generated_asset_ids: list[str]
    # Slides the next generate_images run should produce. Empty means all of them.
    pending_slide_numbers: list[int]
    image_request_key: str | None
    image_feedback: str | None

    channel_content_ids: list[str]

    # The most recent decision's action; conditional edges route on it.
    last_decision: str | None
    workflow_status: str


class ReviewPayload(BaseModel):
    """What the graph tells the outside world when it pauses."""

    review_type: Literal["TOPIC", "COPY", "IMAGE"]
    review_key: str
    task_id: str
    candidate_ids: list[str] = Field(default_factory=list)


class TopicDecision(BaseModel):
    action: Literal["select", "regenerate", "cancel"]
    selected_topic_id: str | None = None
    feedback: str | None = None

    @model_validator(mode="after")
    def _select_needs_topic(self) -> "TopicDecision":
        if self.action == "select" and not self.selected_topic_id:
            raise ValueError("selected_topic_id is required to select a topic.")
        return self


class CopyDecision(BaseModel):
    action: Literal["approve", "revise", "cancel"]
    version_id: str
    feedback: str | None = None
    decision_id: str

    @model_validator(mode="after")
    def _revise_needs_feedback(self) -> "CopyDecision":
        if self.action == "revise" and not (self.feedback and self.feedback.strip()):
            raise ValueError("feedback is required to request a revision.")
        return self


class ImageDecision(BaseModel):
    action: Literal["approve", "regenerate", "cancel"]
    slide_numbers: list[int] = Field(default_factory=list)
    feedback: str | None = None
    decision_id: str

    @model_validator(mode="after")
    def _regenerate_needs_slides(self) -> "ImageDecision":
        if self.action == "regenerate" and not self.slide_numbers:
            raise ValueError("slide_numbers is required to regenerate images.")
        return self
