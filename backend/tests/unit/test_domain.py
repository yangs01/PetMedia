"""Status machine, schemas, prompts and job input planning."""

from types import SimpleNamespace

import pytest
from langgraph.types import Command
from pydantic import ValidationError

from app.ai.prompts import load_prompt
from app.ai.states.content_state import CopyDecision, ImageDecision, TopicDecision
from app.core.config import PROJECT_ROOT, Settings
from app.core.exceptions import (
    ProviderPermanentError,
    ProviderTransientError,
    WorkflowError,
    is_transient_error,
)
from app.core.status import LEGAL_TRANSITIONS, TaskStatus, is_legal_transition
from app.schemas.approval import CopyDecisionRequest, ImageDecisionRequest, TopicDecisionRequest
from app.schemas.content import CarouselPlanOutput, InstagramOutput
from app.schemas.product import ProductCreate
from app.workers.job_runner import SKIP_RUN, plan_graph_input


class TestStatusMachine:
    def test_every_status_has_a_rule(self):
        assert set(LEGAL_TRANSITIONS) == set(TaskStatus)

    @pytest.mark.parametrize(
        ("current", "target"),
        [
            (TaskStatus.AWAITING_COPY_REVIEW, TaskStatus.GENERATING_COPY),
            (TaskStatus.AWAITING_TOPIC_REVIEW, TaskStatus.GENERATING_TOPICS),
            (TaskStatus.AWAITING_IMAGE_REVIEW, TaskStatus.GENERATING_ASSETS),
            (TaskStatus.FINALIZING, TaskStatus.READY),
            (TaskStatus.FAILED, TaskStatus.QUEUED),
        ],
    )
    def test_legal(self, current, target):
        assert is_legal_transition(current, target)

    @pytest.mark.parametrize(
        ("current", "target"),
        [
            (TaskStatus.AWAITING_TOPIC_REVIEW, TaskStatus.READY),
            (TaskStatus.AWAITING_COPY_REVIEW, TaskStatus.READY),
            (TaskStatus.GENERATING_TOPICS, TaskStatus.GENERATING_ASSETS),
            (TaskStatus.QUEUED, TaskStatus.READY),
        ],
    )
    def test_illegal(self, current, target):
        assert not is_legal_transition(current, target)

    @pytest.mark.parametrize("terminal", [TaskStatus.READY, TaskStatus.CANCELLED])
    def test_terminal_statuses_have_no_exit(self, terminal):
        assert not LEGAL_TRANSITIONS[terminal]


class TestSchemas:
    def test_hashtags_are_normalized_and_deduplicated(self):
        output = InstagramOutput(
            caption="A caption long enough.", hashtags=["cat toys", "#CatToys", "#Pets!"], call_to_action="Look"
        )
        assert output.hashtags == ["#cattoys", "#Pets"]

    def test_caption_over_platform_limit_is_rejected(self):
        with pytest.raises(ValidationError):
            InstagramOutput(caption="x" * 2201, hashtags=["a"], call_to_action="Look")

    @staticmethod
    def _slide(number: int) -> dict:
        return {
            "slide_number": number,
            "slide_type": "education",
            "headline": "Headline",
            "visual_description": "Scene",
            "layout_template": "content",
            "image_prompt": "Scene",
            "alt_text": "Alt text",
        }

    def test_carousel_accepts_three_to_five_ordered_slides(self):
        assert len(CarouselPlanOutput(slides=[self._slide(n) for n in (1, 2, 3)]).slides) == 3

    @pytest.mark.parametrize("numbers", [(1, 2), (1, 2, 3, 4, 5, 6), (1, 3, 2), (2, 3, 4)])
    def test_carousel_rejects_bad_slide_lists(self, numbers):
        with pytest.raises(ValidationError):
            CarouselPlanOutput(slides=[self._slide(n) for n in numbers])

    def test_topic_select_needs_a_topic(self):
        with pytest.raises(ValidationError):
            TopicDecisionRequest(action="select")

    def test_revision_needs_feedback(self):
        with pytest.raises(ValidationError):
            CopyDecisionRequest(
                action="revise", current_version_id="5c1f8f5e-3b9a-4a51-8a11-0a6f0b7d1e11", feedback="  "
            )

    def test_edit_needs_content(self):
        with pytest.raises(ValidationError):
            CopyDecisionRequest(action="edit_and_approve", current_version_id="5c1f8f5e-3b9a-4a51-8a11-0a6f0b7d1e11")

    def test_image_regeneration_rejects_duplicates_and_empty(self):
        with pytest.raises(ValidationError):
            ImageDecisionRequest(action="regenerate", slide_numbers=[])
        with pytest.raises(ValidationError):
            ImageDecisionRequest(action="regenerate", slide_numbers=[2, 2])

    def test_graph_decisions_enforce_their_own_rules(self):
        with pytest.raises(ValidationError):
            TopicDecision(action="select")
        with pytest.raises(ValidationError):
            CopyDecision(action="revise", version_id="v", decision_id="d")
        with pytest.raises(ValidationError):
            ImageDecision(action="regenerate", decision_id="d")

    def test_product_rejects_bad_currency_and_negative_price(self):
        with pytest.raises(ValidationError):
            ProductCreate(name="n", category="c", description="d", currency="usd")
        with pytest.raises(ValidationError):
            ProductCreate(name="n", category="c", description="d", price=-1)


class TestPrompts:
    @pytest.mark.parametrize(
        "name",
        [
            "brand_guidelines",
            "topic_generation",
            "copy_generation",
            "copy_revision",
            "instagram_adapter",
            "facebook_adapter",
            "carousel_planning",
        ],
    )
    def test_prompt_loads_with_a_version(self, name):
        prompt = load_prompt(name)
        assert prompt.version and prompt.text
        assert not prompt.text.startswith("<!--")
        assert prompt.text.isascii(), "Prompts must stay in plain English."

    def test_guidelines_mark_data_as_untrusted(self):
        assert "untrusted_data" in load_prompt("brand_guidelines").text


class TestSettings:
    def test_empty_environment_values_mean_not_set(self, monkeypatch):
        monkeypatch.setenv("FONT_PATH", "")
        monkeypatch.setenv("API_KEY", "")
        monkeypatch.setenv("LLM_API_KEY", "")
        settings = Settings(_env_file=None)
        assert settings.font_path is None
        assert settings.api_key is None
        assert settings.llm_api_key is None

    def test_example_env_file_is_valid_and_needs_no_keys(self):
        example = PROJECT_ROOT / ".env.example"
        settings = Settings(_env_file=example)
        assert (settings.llm_provider, settings.image_provider) == ("mock", "mock")
        assert settings.font_path is None
        assert settings.api_host == "127.0.0.1"

    def test_secrets_do_not_appear_in_repr(self):
        assert "sk-secret" not in repr(Settings(_env_file=None, llm_api_key="sk-secret"))


class TestErrorClassification:
    def test_transient_and_permanent(self):
        assert is_transient_error(ProviderTransientError("x"))
        assert not is_transient_error(ProviderPermanentError("x"))
        assert not is_transient_error(ValueError("x"))


def _snapshot(*, interrupts=(), next_nodes=(), created_at="2026-01-01"):
    return SimpleNamespace(
        interrupts=tuple(SimpleNamespace(value={"review_key": key}) for key in interrupts),
        next=next_nodes,
        created_at=created_at,
    )


class TestPlanGraphInput:
    """Each case is a point a crashed job can be retried from."""

    def test_fresh_thread_starts_the_graph(self):
        assert plan_graph_input({}, "t1", _snapshot(created_at=None)) == {"task_id": "t1"}

    def test_decision_without_checkpoint_is_an_error(self):
        with pytest.raises(WorkflowError):
            plan_graph_input({"review_key": "k"}, "t1", _snapshot(created_at=None))

    def test_matching_review_key_resumes(self):
        decision = {"action": "select"}
        result = plan_graph_input({"review_key": "k", "decision": decision}, "t", _snapshot(interrupts=["k"]))
        assert isinstance(result, Command) and result.resume == decision

    def test_decision_already_consumed_is_not_applied_again(self):
        result = plan_graph_input({"review_key": "old", "decision": {}}, "t", _snapshot(interrupts=["new"]))
        assert result is SKIP_RUN

    def test_start_job_retried_after_graph_paused_runs_nothing(self):
        assert plan_graph_input({}, "t", _snapshot(interrupts=["k"])) is SKIP_RUN

    def test_mid_graph_checkpoint_continues(self):
        assert plan_graph_input({}, "t", _snapshot(next_nodes=("generate_copy",))) is None

    def test_finished_graph_runs_nothing(self):
        assert plan_graph_input({}, "t", _snapshot()) is SKIP_RUN
