"""Dependencies injected into graph nodes through LangGraph's runtime context.

These objects are not serializable, so they must never enter graph state. The
context is passed on every invocation and is not stored in checkpoints, which is
why a restarted worker can supply fresh ones.
"""

from dataclasses import dataclass

from app.ai.providers.image_provider import ImageProvider
from app.ai.providers.model_router import ModelRouter
from app.core.config import Settings
from app.db.session import SessionFactory
from app.media.storage import Storage


@dataclass(frozen=True)
class WorkflowDeps:
    session_factory: SessionFactory
    models: ModelRouter
    image: ImageProvider
    storage: Storage
    settings: Settings
