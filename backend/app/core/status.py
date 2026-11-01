"""Domain enums and the task status state machine."""

from enum import StrEnum


class TaskStatus(StrEnum):
    CREATED = "CREATED"
    QUEUED = "QUEUED"
    GENERATING_TOPICS = "GENERATING_TOPICS"
    AWAITING_TOPIC_REVIEW = "AWAITING_TOPIC_REVIEW"
    GENERATING_COPY = "GENERATING_COPY"
    AWAITING_COPY_REVIEW = "AWAITING_COPY_REVIEW"
    GENERATING_ASSETS = "GENERATING_ASSETS"
    AWAITING_IMAGE_REVIEW = "AWAITING_IMAGE_REVIEW"
    FINALIZING = "FINALIZING"
    READY = "READY"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class ReviewType(StrEnum):
    TOPIC = "TOPIC"
    COPY = "COPY"
    IMAGE = "IMAGE"


class GenerationSource(StrEnum):
    AI_INITIAL = "AI_INITIAL"
    AI_REVISION = "AI_REVISION"
    HUMAN_EDIT = "HUMAN_EDIT"


class VersionApproval(StrEnum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    SUPERSEDED = "SUPERSEDED"


class AssetStatus(StrEnum):
    ACTIVE = "ACTIVE"  # Current slide image, awaiting review.
    APPROVED = "APPROVED"  # Current slide image, approved for publishing.
    SUPERSEDED = "SUPERSEDED"  # Replaced by a newer version; kept as history.


class ProductStatus(StrEnum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class ReviewVerification(StrEnum):
    UNVERIFIED = "UNVERIFIED"
    VERIFIED = "VERIFIED"


class JobType(StrEnum):
    START_CONTENT_WORKFLOW = "START_CONTENT_WORKFLOW"
    RESUME_TOPIC_REVIEW = "RESUME_TOPIC_REVIEW"
    RESUME_COPY_REVIEW = "RESUME_COPY_REVIEW"
    RESUME_IMAGE_REVIEW = "RESUME_IMAGE_REVIEW"
    RETRY_WORKFLOW = "RETRY_WORKFLOW"


class JobStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


LEGAL_TRANSITIONS: dict[TaskStatus, frozenset[TaskStatus]] = {
    TaskStatus.CREATED: frozenset({TaskStatus.QUEUED, TaskStatus.CANCELLED}),
    # A retried job can resume any phase, or find its review checkpoint already reached.
    TaskStatus.QUEUED: frozenset(
        {
            TaskStatus.GENERATING_TOPICS,
            TaskStatus.AWAITING_TOPIC_REVIEW,
            TaskStatus.GENERATING_COPY,
            TaskStatus.AWAITING_COPY_REVIEW,
            TaskStatus.GENERATING_ASSETS,
            TaskStatus.AWAITING_IMAGE_REVIEW,
            TaskStatus.FINALIZING,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
        }
    ),
    TaskStatus.GENERATING_TOPICS: frozenset({TaskStatus.AWAITING_TOPIC_REVIEW, TaskStatus.FAILED}),
    TaskStatus.AWAITING_TOPIC_REVIEW: frozenset(
        {TaskStatus.GENERATING_TOPICS, TaskStatus.GENERATING_COPY, TaskStatus.CANCELLED}
    ),
    TaskStatus.GENERATING_COPY: frozenset({TaskStatus.AWAITING_COPY_REVIEW, TaskStatus.FAILED}),
    TaskStatus.AWAITING_COPY_REVIEW: frozenset(
        {TaskStatus.GENERATING_COPY, TaskStatus.GENERATING_ASSETS, TaskStatus.CANCELLED}
    ),
    TaskStatus.GENERATING_ASSETS: frozenset({TaskStatus.AWAITING_IMAGE_REVIEW, TaskStatus.FAILED}),
    TaskStatus.AWAITING_IMAGE_REVIEW: frozenset(
        {TaskStatus.GENERATING_ASSETS, TaskStatus.FINALIZING, TaskStatus.CANCELLED}
    ),
    TaskStatus.FINALIZING: frozenset({TaskStatus.READY, TaskStatus.FAILED}),
    TaskStatus.FAILED: frozenset({TaskStatus.QUEUED, TaskStatus.CANCELLED}),
    TaskStatus.READY: frozenset(),
    TaskStatus.CANCELLED: frozenset(),
}

REVIEW_STATUS_BY_TYPE: dict[ReviewType, TaskStatus] = {
    ReviewType.TOPIC: TaskStatus.AWAITING_TOPIC_REVIEW,
    ReviewType.COPY: TaskStatus.AWAITING_COPY_REVIEW,
    ReviewType.IMAGE: TaskStatus.AWAITING_IMAGE_REVIEW,
}
REVIEW_TYPE_BY_STATUS = {status: review for review, status in REVIEW_STATUS_BY_TYPE.items()}

# Reported to clients so a frontend can render controls without duplicating these rules.
AVAILABLE_ACTIONS: dict[TaskStatus, tuple[str, ...]] = {
    TaskStatus.QUEUED: ("cancel",),
    TaskStatus.AWAITING_TOPIC_REVIEW: ("select", "regenerate", "cancel"),
    TaskStatus.AWAITING_COPY_REVIEW: ("approve", "revise", "edit_and_approve", "cancel"),
    TaskStatus.AWAITING_IMAGE_REVIEW: ("approve", "regenerate", "cancel"),
    TaskStatus.FAILED: ("retry", "cancel"),
    TaskStatus.READY: ("export",),
}


def is_legal_transition(current: TaskStatus, target: TaskStatus) -> bool:
    return target in LEGAL_TRANSITIONS[current]
