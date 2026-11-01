from uuid import UUID

from fastapi import APIRouter, status

from app.api.dependencies import SessionDep, SettingsDep
from app.schemas.approval import (
    CopyDecisionRequest,
    DecisionAccepted,
    ImageDecisionRequest,
    TopicDecisionRequest,
)
from app.services.approval_service import ApprovalService

router = APIRouter(prefix="/tasks/{task_id}", tags=["approvals"])


@router.post("/topic-decision", response_model=DecisionAccepted, status_code=status.HTTP_202_ACCEPTED)
async def submit_topic_decision(
    task_id: UUID, request: TopicDecisionRequest, session: SessionDep, settings: SettingsDep
):
    return await ApprovalService(session, settings).decide_topic(task_id, request)


@router.post("/copy-decision", response_model=DecisionAccepted, status_code=status.HTTP_202_ACCEPTED)
async def submit_copy_decision(
    task_id: UUID, request: CopyDecisionRequest, session: SessionDep, settings: SettingsDep
):
    return await ApprovalService(session, settings).decide_copy(task_id, request)


@router.post("/image-decision", response_model=DecisionAccepted, status_code=status.HTTP_202_ACCEPTED)
async def submit_image_decision(
    task_id: UUID, request: ImageDecisionRequest, session: SessionDep, settings: SettingsDep
):
    return await ApprovalService(session, settings).decide_images(task_id, request)
