from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.core.status import GenerationSource, ReviewType, TaskStatus, VersionApproval
from app.schemas.asset import AssetRead


class TaskCreate(BaseModel):
    brand_id: UUID
    product_ids: list[UUID] = Field(min_length=1, max_length=10)
    target_market: str | None = Field(default=None, max_length=50)
    target_audience: str | None = Field(default=None, max_length=2000)
    marketing_goal: str | None = Field(default=None, max_length=2000)
    operator_instructions: str | None = Field(default=None, max_length=5000)
    channels: list[str] = Field(default=["instagram", "facebook"], min_length=1)
    image_count: int | None = Field(default=None, ge=3, le=5)
    target_word_count: int | None = Field(default=None, ge=100, le=2000)


class TaskCreated(BaseModel):
    task_id: UUID
    thread_id: str
    status: TaskStatus


class TaskSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    status: TaskStatus
    target_market: str
    channels: list[str]
    image_count: int
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None


class TopicRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    batch_id: UUID
    batch_number: int
    position: int
    title: str
    angle: str
    target_audience: str
    hook: str
    product_relevance: str
    content_type: str
    rationale: str
    operator_feedback: str | None
    is_selected: bool
    provider: str
    created_at: datetime


class ContentVersionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    version_number: int
    content: dict[str, Any]
    generation_source: GenerationSource
    parent_version_id: UUID | None
    revision_feedback: str | None
    approval_status: VersionApproval
    validation: dict[str, Any] | None
    provider: str
    prompt_version: str | None
    created_at: datetime


class ChannelContentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    platform: str
    content_version_id: UUID
    payload: dict[str, Any]
    validation: dict[str, Any] | None
    provider: str
    created_at: datetime


class TaskEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    event_type: str
    from_status: str | None
    to_status: str | None
    node_name: str | None
    message: str | None
    data: dict[str, Any] | None
    created_at: datetime


class TaskDetail(BaseModel):
    """Everything a frontend needs to render a task. Holds no LangGraph internals."""

    id: UUID
    thread_id: str
    brand_id: UUID
    product_ids: list[UUID]
    status: TaskStatus
    version: int
    review_stage: ReviewType | None
    review_key: str | None
    available_actions: list[str]
    decision_in_progress: bool
    target_market: str
    target_audience: str | None
    marketing_goal: str | None
    channels: list[str]
    image_count: int
    selected_topic: TopicRead | None
    current_version: ContentVersionRead | None
    approved_version_id: UUID | None
    carousel_plan: list[dict[str, Any]] | None
    assets: list[AssetRead]
    channel_contents: list[ChannelContentRead]
    error: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None
