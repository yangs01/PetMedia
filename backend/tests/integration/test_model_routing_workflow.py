"""The unchanged graph with a different vendor per role, against fake HTTP servers.

This proves routing, request formats and review flow work together. It cannot prove
that a vendor's live API accepts these requests: that needs real keys.
"""

import json
import re
from collections import Counter
from pathlib import Path
from uuid import UUID

import anthropic
import httpx
import httpx2
import pytest
from sqlalchemy import select

from app.ai.providers import create_model_registry
from app.ai.providers.anthropic_provider import AnthropicLLMProvider
from app.ai.providers.image_provider import OpenAICompatibleImageProvider
from app.ai.providers.llm_provider import DeepSeekLLMProvider, OpenAILLMProvider
from app.ai.providers.model_config import ProviderType
from app.ai.providers.model_router import ModelRouter
from app.core.config import Settings
from app.main import create_app
from app.models import CarouselPlan
from tests.integration.test_real_provider_workflow import _fake_api, _reply_for
from tests.integration.test_workflow import detail

pytestmark = pytest.mark.integration

ACCEPTANCE_YAML = """
profiles:
  topics: {provider: deepseek, model: ds-topics, credential_env: DEEPSEEK_KEY}
  copy: {provider: anthropic, model: claude-copy, credential_env: ANTHROPIC_KEY}
  revision: {provider: anthropic, model: claude-revision, credential_env: ANTHROPIC_KEY}
  instagram: {provider: openai, model: gpt-instagram, credential_env: OPENAI_KEY}
  facebook: {provider: deepseek, model: ds-facebook, credential_env: DEEPSEEK_KEY}
  carousel: {provider: openai, model: gpt-carousel, credential_env: OPENAI_KEY}
roles:
  topic_generation: topics
  copy_generation: copy
  copy_revision: revision
  instagram_adaptation: instagram
  facebook_adaptation: facebook
  carousel_planning: carousel
"""
ENVIRON = {"DEEPSEEK_KEY": "ds-key", "ANTHROPIC_KEY": "claude-key", "OPENAI_KEY": "openai-key"}
OPERATIONS = {
    "Suggest content topics": "topics",
    "Revise an existing": "revision",
    "master marketing draft": "copy",
    "Instagram feed caption": "instagram",
    "Facebook Page post": "facebook",
    "visual storytelling plan": "carousel",
}


def operation_of(system_prompt: str) -> str:
    return next(label for marker, label in OPERATIONS.items() if marker in system_prompt)


class FakeVendors:
    """Answers each vendor in its own format and records who was asked for what."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str, str]] = []

    def _reply(self, system: str, user: str) -> str:
        data = json.loads(re.search(r"<untrusted_data>\n(.*)\n</untrusted_data>", user, re.DOTALL).group(1))
        return json.dumps(_reply_for(system, data))

    def chat(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        system, user = body["messages"][0]["content"], body["messages"][1]["content"]
        token = request.headers["authorization"].removeprefix("Bearer ")
        self.calls.append((operation_of(system), request.url.host, body["model"], token))
        message = {"content": self._reply(system, user)}
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": message}]})

    def claude(self, request: httpx2.Request) -> httpx2.Response:
        body = json.loads(request.content)
        token = request.headers["authorization"].removeprefix("Bearer ")
        self.calls.append((operation_of(body["system"]), request.url.host, body["model"], token))
        return httpx2.Response(
            200,
            json={
                "id": "msg_test",
                "type": "message",
                "role": "assistant",
                "model": body["model"],
                "content": [{"type": "text", "text": self._reply(body["system"], body["messages"][0]["content"])}],
                "stop_reason": "end_turn",
                "stop_sequence": None,
                "usage": {"input_tokens": 1, "output_tokens": 1},
            },
        )


def build_router(tmp_path: Path, vendors: FakeVendors, profiles_yaml: str = ACCEPTANCE_YAML) -> ModelRouter:
    path = tmp_path / "models.yaml"
    path.write_text(profiles_yaml, encoding="utf-8")
    registry = create_model_registry(Settings(_env_file=None, llm_profiles_path=path), ENVIRON)
    transport = httpx.MockTransport(vendors.chat)
    registry.register_provider(
        ProviderType.DEEPSEEK, lambda profile, key: DeepSeekLLMProvider(profile, key, transport=transport)
    )
    registry.register_provider(
        ProviderType.OPENAI, lambda profile, key: OpenAILLMProvider(profile, key, transport=transport)
    )
    registry.register_provider(
        ProviderType.ANTHROPIC,
        lambda profile, key: AnthropicLLMProvider(
            profile,
            key,
            http_client=anthropic.DefaultAsyncHttpxClient(transport=httpx2.MockTransport(vendors.claude)),
        ),
    )
    return ModelRouter.from_registry(registry)


def image_provider(seen: list[str]) -> OpenAICompatibleImageProvider:
    settings = Settings(
        _env_file=None,
        image_provider="openai_compatible",
        image_api_key="image-key",
        image_model="image-model",
        image_base_url="https://images.example.com/v1",
    )

    def handler(request):
        seen.append(request.headers["authorization"])
        return _fake_api(request)

    return OpenAICompatibleImageProvider(settings, transport=httpx.MockTransport(handler))


async def test_acceptance_configuration_runs_the_whole_workflow(
    client, task_inputs, make_runner, drain, tmp_path, session_factory
):
    vendors = FakeVendors()
    image_auth: list[str] = []
    router = build_router(tmp_path, vendors)
    runner = make_runner(models=router, image=image_provider(image_auth))

    task_id = (await client.post("/tasks", json=task_inputs)).json()["task_id"]
    await drain(runner)

    # The review interrupt still pauses the graph, with nothing else requested.
    assert (await detail(client, task_id))["status"] == "AWAITING_TOPIC_REVIEW"
    assert [call[0] for call in vendors.calls] == ["topics"]
    topics = (await client.get(f"/tasks/{task_id}/topics")).json()
    assert {topic["provider"] for topic in topics} == {"deepseek"}

    await client.post(
        f"/tasks/{task_id}/topic-decision", json={"action": "select", "selected_topic_id": topics[0]["id"]}
    )
    await drain(runner)
    first = (await detail(client, task_id))["current_version"]
    assert first["provider"] == "anthropic"
    assert first["generation_source"] == "AI_INITIAL"

    response = await client.post(
        f"/tasks/{task_id}/copy-decision",
        json={"action": "revise", "current_version_id": first["id"], "feedback": "Make it warmer."},
    )
    assert response.status_code == 202
    await drain(runner)
    revised = (await detail(client, task_id))["current_version"]
    assert revised["provider"] == "anthropic"
    assert revised["generation_source"] == "AI_REVISION"
    assert revised["version_number"] == first["version_number"] + 1

    await client.post(
        f"/tasks/{task_id}/copy-decision", json={"action": "approve", "current_version_id": revised["id"]}
    )
    await drain(runner)
    task = await detail(client, task_id)
    assert task["status"] == "AWAITING_IMAGE_REVIEW"
    assert {c["platform"]: c["provider"] for c in task["channel_contents"]} == {
        "instagram": "openai",
        "facebook": "deepseek",
    }
    async with session_factory() as session:
        plan_provider = await session.scalar(
            select(CarouselPlan.provider).where(CarouselPlan.task_id == UUID(task_id))
        )
    assert plan_provider == "openai"
    assert {asset["provider"] for asset in task["assets"]} == {"openai_compatible:image-model"}

    await client.post(f"/tasks/{task_id}/image-decision", json={"action": "approve"})
    await drain(runner)
    assert (await detail(client, task_id))["status"] == "READY"

    expected = {
        "topics": ("api.deepseek.com", "ds-topics", "ds-key"),
        "copy": ("api.anthropic.com", "claude-copy", "claude-key"),
        "revision": ("api.anthropic.com", "claude-revision", "claude-key"),
        "instagram": ("api.openai.com", "gpt-instagram", "openai-key"),
        "facebook": ("api.deepseek.com", "ds-facebook", "ds-key"),
        "carousel": ("api.openai.com", "gpt-carousel", "openai-key"),
    }
    assert {call[0]: call[1:] for call in vendors.calls} == expected
    assert Counter(call[0] for call in vendors.calls) == Counter(expected.keys())
    # Images were configured separately and used their own credential.
    assert image_auth and set(image_auth) == {"Bearer image-key"}

    await router.aclose()


async def test_paused_task_resumes_on_a_restarted_worker_with_a_new_router(
    client, task_inputs, make_runner, drain, tmp_path
):
    vendors = FakeVendors()
    first_worker = build_router(tmp_path, vendors)
    task_id = (await client.post("/tasks", json=task_inputs)).json()["task_id"]
    await drain(make_runner(models=first_worker))
    await first_worker.aclose()

    # Routing is not in the checkpoint, so a new worker's configuration applies on resume.
    changed = ACCEPTANCE_YAML.replace(
        "copy: {provider: anthropic, model: claude-copy, credential_env: ANTHROPIC_KEY}",
        "copy: {provider: openai, model: gpt-copy, credential_env: OPENAI_KEY}",
    )
    second_worker = build_router(tmp_path, vendors, changed)
    topics = (await client.get(f"/tasks/{task_id}/topics")).json()
    await client.post(
        f"/tasks/{task_id}/topic-decision", json={"action": "select", "selected_topic_id": topics[0]["id"]}
    )
    await drain(make_runner(models=second_worker))

    task = await detail(client, task_id)
    assert task["status"] == "AWAITING_COPY_REVIEW"
    assert task["current_version"]["provider"] == "openai"
    topics_after = (await client.get(f"/tasks/{task_id}/topics")).json()
    assert [topic["id"] for topic in topics_after] == [topic["id"] for topic in topics]
    assert [call[0] for call in vendors.calls].count("topics") == 1
    await second_worker.aclose()


async def test_fallback_records_the_provider_that_answered(client, task_inputs, make_runner, drain, tmp_path):
    vendors = FakeVendors()
    profiles = ACCEPTANCE_YAML.replace(
        "topics: {provider: deepseek, model: ds-topics, credential_env: DEEPSEEK_KEY}",
        "topics: {provider: deepseek, model: ds-topics, credential_env: DEEPSEEK_KEY, fallback_profile: carousel}",
    )
    original_chat = vendors.chat

    def deepseek_is_down(request):
        if request.url.host == "api.deepseek.com":
            return httpx.Response(503)
        return original_chat(request)

    vendors.chat = deepseek_is_down
    router = build_router(tmp_path, vendors, profiles)

    task_id = (await client.post("/tasks", json=task_inputs)).json()["task_id"]
    await drain(make_runner(models=router))

    assert (await detail(client, task_id))["status"] == "AWAITING_TOPIC_REVIEW"
    topics = (await client.get(f"/tasks/{task_id}/topics")).json()
    assert {topic["provider"] for topic in topics} == {"openai"}
    await router.aclose()


async def test_ready_endpoint_reports_profiles(client, settings, session_factory, storage, tmp_path):
    assert (await client.get("/health/ready")).json()["providers"]["llm"] == "mock"

    configured = settings.model_copy(update={"llm_profiles_path": tmp_path / "models.yaml"})
    app = create_app(configured)
    app.state.settings = configured
    app.state.session_factory = session_factory
    app.state.storage = storage
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test/api/v1") as profiled:
        assert (await profiled.get("/health/ready")).json()["providers"]["llm"] == "profiles"
