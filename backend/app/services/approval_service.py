"""Validates human review decisions and records them atomically.

One database transaction records the decision, applies its business effect
(selected topic, approved version, ...), moves the task status and enqueues the
resume job. So a decision can never be half-accepted. The worker later hands the
decision to the paused graph through ``Command(resume=...)``.
"""

from uuid import UUID, uuid4

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.states.content_state import CopyDecision, ImageDecision, TopicDecision
from app.ai.validators.content_validator import validate_master_copy
from app.core.config import Settings
from app.core.exceptions import (
    DuplicateDecisionError,
    InvalidTaskStateError,
    RequestValidationFailure,
    StaleReviewError,
)
from app.core.status import (
    GenerationSource,
    JobType,
    ReviewType,
    TaskStatus,
    VersionApproval,
)
from app.models import ApprovalRecord, ContentTask, ContentVersion, GenerationJob
from app.repositories.asset_repository import AssetRepository
from app.repositories.content_repository import ContentRepository
from app.repositories.job_repository import JobRepository
from app.repositories.task_repository import TaskRepository
from app.schemas.approval import (
    CopyDecisionRequest,
    DecisionAccepted,
    ImageDecisionRequest,
    TopicDecisionRequest,
)
from app.services.content_service import read_generation_context
from app.services.task_service import get_task_or_404, transition_task


class ApprovalService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.tasks = TaskRepository(session)
        self.content = ContentRepository(session)
        self.assets = AssetRepository(session)
        self.jobs = JobRepository(session)

    async def decide_topic(self, task_id: UUID, request: TopicDecisionRequest) -> DecisionAccepted:
        try:
            return await self._decide_topic(task_id, request)
        except IntegrityError as error:
            raise await self._duplicate(error) from error

    async def decide_copy(self, task_id: UUID, request: CopyDecisionRequest) -> DecisionAccepted:
        try:
            return await self._decide_copy(task_id, request)
        except IntegrityError as error:
            raise await self._duplicate(error) from error

    async def decide_images(self, task_id: UUID, request: ImageDecisionRequest) -> DecisionAccepted:
        try:
            return await self._decide_images(task_id, request)
        except IntegrityError as error:
            raise await self._duplicate(error) from error

    async def _duplicate(self, error: IntegrityError) -> DuplicateDecisionError:
        await self.session.rollback()
        return DuplicateDecisionError("A decision for this review has already been submitted.")

    async def _load_at_review(self, task_id: UUID, expected: TaskStatus) -> ContentTask:
        task = await get_task_or_404(self.session, task_id)
        if task.status != expected or not task.current_review_key:
            labels = {
                TaskStatus.AWAITING_TOPIC_REVIEW: "topic review",
                TaskStatus.AWAITING_COPY_REVIEW: "copy approval",
                TaskStatus.AWAITING_IMAGE_REVIEW: "image review",
            }
            raise InvalidTaskStateError(
                f"The task is not awaiting {labels[expected]}.",
                details={"current_status": task.status.value},
            )
        return task

    async def _decide_topic(self, task_id: UUID, request: TopicDecisionRequest) -> DecisionAccepted:
        task = await self._load_at_review(task_id, TaskStatus.AWAITING_TOPIC_REVIEW)
        review_key = task.current_review_key
        target_id: UUID | None = None

        if request.action == "select":
            topic = await self.tasks.get_topic(request.selected_topic_id)
            if topic is None or topic.task_id != task.id:
                raise RequestValidationFailure(
                    "The selected topic does not belong to this task.",
                    details={"selected_topic_id": str(request.selected_topic_id)},
                )
            if topic.batch_number != await self.tasks.latest_topic_batch_number(task.id):
                raise StaleReviewError("That topic is from an earlier suggestion batch.")
            topic.is_selected = True
            target_id = topic.id
            await transition_task(
                self.session, task, TaskStatus.GENERATING_COPY, selected_topic_id=topic.id, current_review_key=None
            )
        elif request.action == "regenerate":
            await transition_task(self.session, task, TaskStatus.GENERATING_TOPICS, current_review_key=None)
        else:
            await transition_task(self.session, task, TaskStatus.CANCELLED, current_review_key=None)

        record = await self._record(task, ReviewType.TOPIC, request.action, review_key, target_id, request.feedback)
        decision = TopicDecision(
            action=request.action,
            selected_topic_id=str(target_id) if target_id else None,
            feedback=request.feedback,
        )
        job = await self._enqueue_resume(task, JobType.RESUME_TOPIC_REVIEW, review_key, decision.model_dump())
        return await self._accepted(task, record, job)

    async def _decide_copy(self, task_id: UUID, request: CopyDecisionRequest) -> DecisionAccepted:
        task = await self._load_at_review(task_id, TaskStatus.AWAITING_COPY_REVIEW)
        review_key = task.current_review_key
        if request.current_version_id != task.current_content_version_id:
            raise StaleReviewError(
                "That draft is no longer the current version.",
                details={"current_version_id": str(task.current_content_version_id)},
            )
        version = await self.content.get_version(request.current_version_id)
        target_id = version.id
        decided_version_id = str(version.id)

        if request.action == "approve":
            version.approval_status = VersionApproval.APPROVED
            await transition_task(
                self.session, task, TaskStatus.GENERATING_ASSETS,
                approved_content_version_id=version.id, current_review_key=None,
            )
        elif request.action == "revise":
            version.approval_status = VersionApproval.REVISION_REQUESTED
            await transition_task(self.session, task, TaskStatus.GENERATING_COPY, current_review_key=None)
        elif request.action == "edit_and_approve":
            edited = await self._create_human_edit(task, version, request, review_key)
            target_id = edited.id
            decided_version_id = str(edited.id)
            await transition_task(
                self.session, task, TaskStatus.GENERATING_ASSETS,
                current_content_version_id=edited.id,
                approved_content_version_id=edited.id,
                current_review_key=None,
            )
        else:
            await transition_task(self.session, task, TaskStatus.CANCELLED, current_review_key=None)

        record = await self._record(
            task, ReviewType.COPY, request.action, review_key, target_id, request.feedback,
            details=_override_details(version) if request.action == "approve" else None,
        )
        decision = CopyDecision(
            # A direct edit reaches the graph as an approval of the new version.
            action="approve" if request.action == "edit_and_approve" else request.action,
            version_id=decided_version_id,
            feedback=request.feedback,
            decision_id=str(record.id),
        )
        job = await self._enqueue_resume(task, JobType.RESUME_COPY_REVIEW, review_key, decision.model_dump())
        return await self._accepted(task, record, job)

    async def _create_human_edit(
        self, task: ContentTask, parent: ContentVersion, request: CopyDecisionRequest, review_key: str
    ) -> ContentVersion:
        context = read_generation_context(task)
        report = validate_master_copy(request.edited_content, context)
        invalid_refs = [f for f in report.findings if f.code in {"UNKNOWN_PRODUCT", "UNKNOWN_REVIEW"}]
        if invalid_refs:
            # A human may overrule a claim warning, but ids must point at real records.
            raise RequestValidationFailure(
                "The edited draft references unknown records.",
                details={"findings": [f.model_dump() for f in invalid_refs]},
            )
        parent.approval_status = VersionApproval.SUPERSEDED
        return await self.content.add_version(
            ContentVersion(
                task_id=task.id,
                content=request.edited_content.model_dump(mode="json"),
                generation_source=GenerationSource.HUMAN_EDIT,
                parent_version_id=parent.id,
                revision_feedback=request.feedback,
                approval_status=VersionApproval.APPROVED,
                idempotency_key=f"human:{review_key}",
                validation=report.to_record(),
                provider="human",
            )
        )

    async def _decide_images(self, task_id: UUID, request: ImageDecisionRequest) -> DecisionAccepted:
        task = await self._load_at_review(task_id, TaskStatus.AWAITING_IMAGE_REVIEW)
        review_key = task.current_review_key
        if request.review_key and request.review_key != review_key:
            raise StaleReviewError(
                "The images changed since this review was loaded.", details={"review_key": review_key}
            )
        if request.action == "regenerate":
            invalid = [n for n in request.slide_numbers if not 1 <= n <= task.image_count]
            if invalid:
                raise RequestValidationFailure(
                    f"Slide numbers must be between 1 and {task.image_count}.", details={"invalid": invalid}
                )
            await transition_task(self.session, task, TaskStatus.GENERATING_ASSETS, current_review_key=None)
        elif request.action == "approve":
            await self.assets.approve_current(task.id)
            await transition_task(self.session, task, TaskStatus.FINALIZING, current_review_key=None)
        else:
            await transition_task(self.session, task, TaskStatus.CANCELLED, current_review_key=None)

        record = await self._record(
            task, ReviewType.IMAGE, request.action, review_key, None, request.feedback,
            details={"slide_numbers": request.slide_numbers} if request.slide_numbers else None,
        )
        decision = ImageDecision(
            action=request.action,
            slide_numbers=sorted(request.slide_numbers),
            feedback=request.feedback,
            decision_id=str(record.id),
        )
        job = await self._enqueue_resume(task, JobType.RESUME_IMAGE_REVIEW, review_key, decision.model_dump())
        return await self._accepted(task, record, job)

    async def _record(
        self, task, review_type, decision, review_key, target_id, feedback, details=None
    ) -> ApprovalRecord:
        return await self.tasks.add_approval(
            ApprovalRecord(
                id=uuid4(),
                task_id=task.id,
                review_type=review_type,
                decision=decision,
                target_reference_id=target_id,
                feedback=feedback,
                review_key=review_key,
                details=details,
            )
        )

    async def _enqueue_resume(self, task, job_type, review_key, decision: dict) -> GenerationJob:
        return await self.jobs.enqueue(
            task_id=task.id,
            job_type=job_type,
            idempotency_key=f"decision:{task.id}:{review_key}",
            max_attempts=self.settings.job_max_attempts,
            payload={"review_key": review_key, "decision": decision},
        )

    async def _accepted(self, task, record, job) -> DecisionAccepted:
        await self.session.commit()
        return DecisionAccepted(task_id=task.id, status=task.status.value, decision_id=record.id, job_id=job.id)


def _override_details(version: ContentVersion) -> dict | None:
    """Record when an operator approved a draft despite validation errors."""
    if version.validation and not version.validation.get("passed", True):
        return {"approved_despite_validation_errors": True, "findings": version.validation.get("findings")}
    return None
