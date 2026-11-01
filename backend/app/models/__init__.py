"""Importing this package registers every table on ``Base.metadata`` (Alembic relies on it)."""

from app.models.approval import ApprovalRecord
from app.models.asset import CarouselPlan, GeneratedAsset
from app.models.brand import BrandProfile
from app.models.channel_content import ChannelContent
from app.models.content_task import ContentTask, ContentTaskProduct
from app.models.content_version import ContentVersion
from app.models.customer_review import CustomerReview
from app.models.generation_job import GenerationJob
from app.models.product import Product, ProductAsset
from app.models.task_event import TaskEvent
from app.models.topic import TopicSuggestion

__all__ = [
    "ApprovalRecord",
    "BrandProfile",
    "CarouselPlan",
    "ChannelContent",
    "ContentTask",
    "ContentTaskProduct",
    "ContentVersion",
    "CustomerReview",
    "GeneratedAsset",
    "GenerationJob",
    "Product",
    "ProductAsset",
    "TaskEvent",
    "TopicSuggestion",
]
