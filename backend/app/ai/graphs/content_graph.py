"""ContentProductionGraph: the LangGraph definition of the content workflow.

The graph owns the sequence and routing. Nodes do the work; everything they
persist is idempotent, so LangGraph may safely re-execute any of them.
"""

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import RetryPolicy

from app.ai.nodes.adapt_channels import adapt_channels
from app.ai.nodes.finalize_content import finalize_content
from app.ai.nodes.generate_copy import generate_copy
from app.ai.nodes.generate_images import generate_images
from app.ai.nodes.generate_topics import generate_topics
from app.ai.nodes.load_context import load_context
from app.ai.nodes.plan_carousel import plan_carousel
from app.ai.nodes.review_copy import review_copy, route_after_copy_review
from app.ai.nodes.review_images import review_images, route_after_image_review
from app.ai.nodes.review_topic import review_topic, route_after_topic_review
from app.ai.nodes.validate_copy import route_after_validation, validate_copy
from app.ai.runtime import WorkflowDeps
from app.ai.states.content_state import ContentState
from app.core.exceptions import is_transient_error

GRAPH_NAME = "ContentProductionGraph"


def build_content_graph(
    checkpointer: BaseCheckpointSaver,
    *,
    max_node_attempts: int = 3,
    retry_initial_interval: float = 1.0,
) -> CompiledStateGraph:
    # Transient failures retry with backoff inside the node's step; anything else
    # surfaces immediately to the job runner.
    retry = RetryPolicy(
        max_attempts=max_node_attempts,
        initial_interval=retry_initial_interval,
        backoff_factor=2.0,
        max_interval=30.0,
        retry_on=is_transient_error,
    )
    graph = StateGraph(ContentState, context_schema=WorkflowDeps)

    graph.add_node("load_context", load_context, retry_policy=retry)
    graph.add_node("generate_topics", generate_topics, retry_policy=retry)
    graph.add_node("review_topic", review_topic)
    graph.add_node("generate_copy", generate_copy, retry_policy=retry)
    graph.add_node("validate_copy", validate_copy, retry_policy=retry)
    graph.add_node("review_copy", review_copy)
    graph.add_node("adapt_channels", adapt_channels, retry_policy=retry)
    graph.add_node("plan_carousel", plan_carousel, retry_policy=retry)
    graph.add_node("generate_images", generate_images, retry_policy=retry)
    graph.add_node("review_images", review_images)
    graph.add_node("finalize_content", finalize_content, retry_policy=retry)

    graph.add_edge(START, "load_context")
    graph.add_edge("load_context", "generate_topics")
    graph.add_edge("generate_topics", "review_topic")
    graph.add_conditional_edges(
        "review_topic",
        route_after_topic_review,
        {"generate_topics": "generate_topics", "generate_copy": "generate_copy", "__end__": END},
    )
    graph.add_edge("generate_copy", "validate_copy")
    graph.add_conditional_edges(
        "validate_copy",
        route_after_validation,
        {"generate_copy": "generate_copy", "review_copy": "review_copy"},
    )
    graph.add_conditional_edges(
        "review_copy",
        route_after_copy_review,
        {"adapt_channels": "adapt_channels", "generate_copy": "generate_copy", "__end__": END},
    )
    graph.add_edge("adapt_channels", "plan_carousel")
    graph.add_edge("plan_carousel", "generate_images")
    graph.add_edge("generate_images", "review_images")
    graph.add_conditional_edges(
        "review_images",
        route_after_image_review,
        {"generate_images": "generate_images", "finalize_content": "finalize_content", "__end__": END},
    )
    graph.add_edge("finalize_content", END)

    return graph.compile(checkpointer=checkpointer, name=GRAPH_NAME)
