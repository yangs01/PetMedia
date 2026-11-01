"""The whole workflow through the real provider classes, against a fake HTTP server.

This proves the HTTP, JSON parsing and validation paths are wired into the graph.
It cannot prove a particular vendor's API accepts our requests: that needs a real key.
"""

import base64
import json
import re

import httpx
import pytest

from app.ai.providers.image_provider import OpenAICompatibleImageProvider
from app.ai.providers.llm_provider import OpenAICompatibleLLMProvider
from app.core.config import Settings
from tests.conftest import png_bytes
from tests.integration.test_workflow import detail

pytestmark = pytest.mark.integration


def _reply_for(system_prompt: str, data: dict) -> dict:
    product_id = data["products"][0]["id"]
    if "Suggest content topics" in system_prompt:
        return {
            "topics": [
                {
                    "title": f"Real topic {n}",
                    "angle": "An angle",
                    "target_audience": "Cat owners",
                    "hook": "A hook",
                    "product_relevance": "It fits",
                    "content_type": "educational_tips",
                    "rationale": "A reason",
                }
                for n in range(data["topic_count"])
            ]
        }
    if "Revise an existing" in system_prompt or "master marketing draft" in system_prompt:
        return {
            "title": "A real draft",
            "opening_hook": "A hook",
            "body": "Useful advice for cat owners. " * 100,
            "key_takeaways": ["Keep sessions short"],
            "featured_product_ids": [product_id],
            "call_to_action": "Take a look",
            "source_review_ids": [],
        }
    if "Instagram feed caption" in system_prompt:
        return {"caption": "A short caption for Instagram.", "hashtags": ["CatToys", "#PetCare"], "call_to_action": "Take a look"}
    if "Facebook Page post" in system_prompt:
        return {"opening_hook": "A hook", "post_text": "A longer post for Facebook readers.", "call_to_action": "Take a look"}
    if "visual storytelling plan" in system_prompt:
        count = data["image_count"]
        return {
            "slides": [
                {
                    "slide_number": n,
                    "slide_type": "cover" if n == 1 else "education",
                    "headline": f"Headline {n}",
                    "supporting_text": "Short text",
                    "visual_description": "A cozy room",
                    "product_ids": [product_id] if n == count else [],
                    "layout_template": "cover" if n == 1 else "content",
                    "image_prompt": "A cozy room in soft light",
                    "alt_text": f"Slide {n}",
                }
                for n in range(1, count + 1)
            ]
        }
    raise AssertionError("Unexpected prompt.")


def _fake_api(request: httpx.Request) -> httpx.Response:
    if request.url.path.endswith("/chat/completions"):
        body = json.loads(request.content)
        system, user = body["messages"][0]["content"], body["messages"][1]["content"]
        data = json.loads(re.search(r"<untrusted_data>\n(.*)\n</untrusted_data>", user, re.DOTALL).group(1))
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(_reply_for(system, data))}}]})
    if request.url.path.endswith("/images/generations"):
        encoded = base64.b64encode(png_bytes((256, 384))).decode()
        return httpx.Response(200, json={"data": [{"b64_json": encoded}]})
    raise AssertionError(f"Unexpected request: {request.url}")


async def test_full_workflow_with_real_provider_classes(client, task_inputs, make_runner, drain):
    transport = httpx.MockTransport(_fake_api)
    settings = Settings(
        _env_file=None,
        llm_provider="openai_compatible",
        llm_api_key="test-key",
        llm_model="test-model",
        image_provider="openai_compatible",
        image_api_key="test-key",
        image_model="test-image",
    )
    runner = make_runner(
        llm=OpenAICompatibleLLMProvider(settings, transport=transport),
        image=OpenAICompatibleImageProvider(settings, transport=transport),
    )
    task_id = (await client.post("/tasks", json=task_inputs)).json()["task_id"]
    await drain(runner)

    topics = (await client.get(f"/tasks/{task_id}/topics")).json()
    assert [t["provider"] for t in topics] == ["openai_compatible"] * 5
    await client.post(f"/tasks/{task_id}/topic-decision", json={"action": "select", "selected_topic_id": topics[0]["id"]})
    await drain(runner)

    version = (await detail(client, task_id))["current_version"]
    assert version["provider"] == "openai_compatible"
    await client.post(f"/tasks/{task_id}/copy-decision", json={"action": "approve", "current_version_id": version["id"]})
    await drain(runner)

    task = await detail(client, task_id)
    assert task["status"] == "AWAITING_IMAGE_REVIEW"
    assert len(task["assets"]) == 4
    assert all(a["provider"] == "openai_compatible:test-image" and not a["is_mock"] for a in task["assets"])

    await client.post(f"/tasks/{task_id}/image-decision", json={"action": "approve"})
    await drain(runner)
    assert (await detail(client, task_id))["status"] == "READY"

    response = await client.get(f"/tasks/{task_id}/exports/all")
    assert response.status_code == 200
    import io
    import zipfile

    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert json.loads(archive.read("metadata.json"))["contains_mock_content"] is False
        assert "must not be published" not in archive.read("README.md").decode()
