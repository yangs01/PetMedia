"""The LangGraph workflow, driven through the API and the real job queue and checkpointer."""

import hashlib
import io
import zipfile
from uuid import UUID

import pytest
from langgraph.types import Command
from pydantic import ValidationError
from sqlalchemy import func, select

from app.ai.providers.image_provider import ImageProvider
from app.ai.providers.mock_provider import MockImageProvider, MockLLMProvider
from app.core.exceptions import ProviderPermanentError, ProviderTransientError
from app.models import ContentVersion, GeneratedAsset, TopicSuggestion

pytestmark = pytest.mark.integration


async def create_task(client, inputs) -> str:
    response = await client.post("/tasks", json=inputs)
    assert response.status_code == 202
    return response.json()["task_id"]


async def detail(client, task_id) -> dict:
    response = await client.get(f"/tasks/{task_id}")
    assert response.status_code == 200
    return response.json()


async def to_topic_review(client, inputs, runner, drain) -> str:
    task_id = await create_task(client, inputs)
    await drain(runner)
    assert (await detail(client, task_id))["status"] == "AWAITING_TOPIC_REVIEW"
    return task_id


async def select_first_topic(client, task_id) -> None:
    topics = (await client.get(f"/tasks/{task_id}/topics")).json()
    response = await client.post(
        f"/tasks/{task_id}/topic-decision", json={"action": "select", "selected_topic_id": topics[-1]["id"]}
    )
    assert response.status_code == 202


async def to_copy_review(client, inputs, runner, drain) -> str:
    task_id = await to_topic_review(client, inputs, runner, drain)
    await select_first_topic(client, task_id)
    await drain(runner)
    assert (await detail(client, task_id))["status"] == "AWAITING_COPY_REVIEW"
    return task_id


async def approve_current_copy(client, task_id) -> None:
    version_id = (await detail(client, task_id))["current_version"]["id"]
    response = await client.post(
        f"/tasks/{task_id}/copy-decision", json={"action": "approve", "current_version_id": version_id}
    )
    assert response.status_code == 202


async def to_image_review(client, inputs, runner, drain) -> str:
    task_id = await to_copy_review(client, inputs, runner, drain)
    await approve_current_copy(client, task_id)
    await drain(runner)
    assert (await detail(client, task_id))["status"] == "AWAITING_IMAGE_REVIEW"
    return task_id


async def graph_state(runner, task_id, client):
    thread_id = (await detail(client, task_id))["thread_id"]
    return await runner.graph.aget_state({"configurable": {"thread_id": thread_id}})


class TestTopicStage:
    async def test_generates_five_topics_and_really_interrupts(self, client, task_inputs, make_runner, drain):
        runner = make_runner()
        task_id = await to_topic_review(client, task_inputs, runner, drain)

        topics = (await client.get(f"/tasks/{task_id}/topics")).json()
        assert len(topics) == 5
        assert {topic["batch_number"] for topic in topics} == {1}

        # The pause is LangGraph's: a pending interrupt on review_topic, not a status column alone.
        state = await graph_state(runner, task_id, client)
        assert state.next == ("review_topic",)
        assert state.interrupts[0].value["review_type"] == "TOPIC"
        assert (await detail(client, task_id))["available_actions"] == ["select", "regenerate", "cancel"]
        # With no decision, a worker finds nothing to do and the task stays paused.
        assert await drain(runner) == 0
        assert (await detail(client, task_id))["status"] == "AWAITING_TOPIC_REVIEW"

    async def test_selection_is_persisted_and_resumes(self, client, task_inputs, make_runner, drain):
        runner = make_runner()
        task_id = await to_topic_review(client, task_inputs, runner, drain)
        topic = (await client.get(f"/tasks/{task_id}/topics")).json()[2]
        await client.post(f"/tasks/{task_id}/topic-decision", json={"action": "select", "selected_topic_id": topic["id"]})
        # Persisted the moment the API accepts it, before any worker runs.
        assert (await detail(client, task_id))["selected_topic"]["id"] == topic["id"]
        await drain(runner)
        task = await detail(client, task_id)
        assert task["status"] == "AWAITING_COPY_REVIEW"
        assert task["current_version"]["generation_source"] == "AI_INITIAL"

    async def test_regeneration_creates_a_new_batch_and_keeps_history(self, client, task_inputs, make_runner, drain):
        runner = make_runner()
        task_id = await to_topic_review(client, task_inputs, runner, drain)
        response = await client.post(
            f"/tasks/{task_id}/topic-decision", json={"action": "regenerate", "feedback": "More seasonal ideas"}
        )
        assert response.status_code == 202
        await drain(runner)

        topics = (await client.get(f"/tasks/{task_id}/topics")).json()
        first = [t for t in topics if t["batch_number"] == 1]
        second = [t for t in topics if t["batch_number"] == 2]
        assert len(first) == len(second) == 5
        assert {t["batch_id"] for t in first}.isdisjoint({t["batch_id"] for t in second})
        assert second[0]["operator_feedback"] == "More seasonal ideas"
        assert "More seasonal ideas" in second[0]["rationale"]
        assert (await detail(client, task_id))["status"] == "AWAITING_TOPIC_REVIEW"

    async def test_topic_from_an_old_batch_is_stale(self, client, task_inputs, make_runner, drain):
        runner = make_runner()
        task_id = await to_topic_review(client, task_inputs, runner, drain)
        old_topic = (await client.get(f"/tasks/{task_id}/topics")).json()[0]
        await client.post(f"/tasks/{task_id}/topic-decision", json={"action": "regenerate"})
        await drain(runner)
        response = await client.post(
            f"/tasks/{task_id}/topic-decision", json={"action": "select", "selected_topic_id": old_topic["id"]}
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "STALE_REVIEW"

    async def test_recent_topics_reach_the_next_task_of_the_brand(self, client, task_inputs, make_runner, drain, session_factory):
        runner = make_runner()
        first = await to_topic_review(client, task_inputs, runner, drain)
        await select_first_topic(client, first)
        await drain(runner)
        chosen = (await detail(client, first))["selected_topic"]["title"]
        second = await to_topic_review(client, task_inputs, runner, drain)
        async with session_factory() as session:
            from app.models import ContentTask

            task = await session.get(ContentTask, UUID(second))
            assert chosen in task.context_snapshot["recent_topics"]


class TestCopyStage:
    async def test_revision_creates_a_new_version_and_preserves_the_old(self, client, task_inputs, make_runner, drain):
        runner = make_runner()
        task_id = await to_copy_review(client, task_inputs, runner, drain)
        first = (await detail(client, task_id))["current_version"]
        feedback = "Make this more informative and less sales-oriented."
        response = await client.post(
            f"/tasks/{task_id}/copy-decision",
            json={"action": "revise", "current_version_id": first["id"], "feedback": feedback},
        )
        assert response.status_code == 202
        await drain(runner)

        task = await detail(client, task_id)
        assert task["status"] == "AWAITING_COPY_REVIEW"
        versions = (await client.get(f"/tasks/{task_id}/versions")).json()
        assert [v["version_number"] for v in versions] == [1, 2]
        assert versions[0]["content"] == first["content"], "The old draft must be unchanged."
        assert versions[0]["approval_status"] == "REVISION_REQUESTED"
        assert versions[1]["generation_source"] == "AI_REVISION"
        assert versions[1]["parent_version_id"] == first["id"]
        assert versions[1]["revision_feedback"] == feedback
        assert feedback in versions[1]["content"]["body"]
        assert task["current_version"]["id"] == versions[1]["id"]

    async def test_revision_loop_can_repeat(self, client, task_inputs, make_runner, drain):
        runner = make_runner()
        task_id = await to_copy_review(client, task_inputs, runner, drain)
        for round_number in (1, 2, 3):
            current = (await detail(client, task_id))["current_version"]["id"]
            await client.post(
                f"/tasks/{task_id}/copy-decision",
                json={"action": "revise", "current_version_id": current, "feedback": f"Change {round_number}"},
            )
            await drain(runner)
        versions = (await client.get(f"/tasks/{task_id}/versions")).json()
        assert [v["version_number"] for v in versions] == [1, 2, 3, 4]
        state = await graph_state(runner, task_id, client)
        assert state.values["revision_count"] == 3

    async def test_human_edit_becomes_an_approved_version(self, client, task_inputs, make_runner, drain):
        runner = make_runner()
        task_id = await to_copy_review(client, task_inputs, runner, drain)
        current = (await detail(client, task_id))["current_version"]
        edited = {**current["content"], "title": "An operator's title", "body": "Edited by hand. " * 30}
        response = await client.post(
            f"/tasks/{task_id}/copy-decision",
            json={"action": "edit_and_approve", "current_version_id": current["id"], "edited_content": edited},
        )
        assert response.status_code == 202
        await drain(runner)

        task = await detail(client, task_id)
        versions = (await client.get(f"/tasks/{task_id}/versions")).json()
        assert versions[-1]["generation_source"] == "HUMAN_EDIT"
        assert versions[-1]["parent_version_id"] == current["id"]
        assert versions[0]["content"]["title"] != "An operator's title"
        assert task["approved_version_id"] == versions[-1]["id"]
        assert task["status"] == "AWAITING_IMAGE_REVIEW"
        # Downstream work uses the edited version, not the earlier draft.
        channels = (await client.get(f"/tasks/{task_id}/channels")).json()
        assert {channel["content_version_id"] for channel in channels} == {versions[-1]["id"]}

    async def test_human_edit_cannot_reference_unknown_products(self, client, task_inputs, make_runner, drain):
        runner = make_runner()
        task_id = await to_copy_review(client, task_inputs, runner, drain)
        current = (await detail(client, task_id))["current_version"]
        edited = {**current["content"], "featured_product_ids": ["made-up"]}
        response = await client.post(
            f"/tasks/{task_id}/copy-decision",
            json={"action": "edit_and_approve", "current_version_id": current["id"], "edited_content": edited},
        )
        assert response.status_code == 422
        assert (await detail(client, task_id))["status"] == "AWAITING_COPY_REVIEW"

    async def test_stale_version_is_rejected(self, client, task_inputs, make_runner, drain):
        runner = make_runner()
        task_id = await to_copy_review(client, task_inputs, runner, drain)
        first = (await detail(client, task_id))["current_version"]["id"]
        await client.post(
            f"/tasks/{task_id}/copy-decision",
            json={"action": "revise", "current_version_id": first, "feedback": "Change it"},
        )
        await drain(runner)
        response = await client.post(
            f"/tasks/{task_id}/copy-decision", json={"action": "approve", "current_version_id": first}
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "STALE_REVIEW"

    async def test_validation_errors_trigger_a_bounded_automatic_fix(self, client, task_inputs, make_runner, drain):
        class ClaimsThenFixes(MockLLMProvider):
            calls = 0

            async def generate_master_copy(self, context, *, topic):
                draft = await super().generate_master_copy(context, topic=topic)
                return draft.model_copy(update={"body": draft.body + "\n\nThousands of customers love this toy."})

            async def revise_master_copy(self, context, *, topic, current, feedback):
                type(self).calls += 1
                assert "Thousands of customers" in feedback
                return current.model_copy(update={"body": current.body.replace("Thousands of customers love this toy.", "")})

        runner = make_runner(llm=ClaimsThenFixes())
        task_id = await to_copy_review(client, task_inputs, runner, drain)
        versions = (await client.get(f"/tasks/{task_id}/versions")).json()
        assert ClaimsThenFixes.calls == 1
        assert [v["generation_source"] for v in versions] == ["AI_INITIAL", "AI_REVISION"]
        assert versions[0]["validation"]["passed"] is False
        assert versions[1]["validation"]["passed"] is True

    async def test_unfixable_draft_reaches_the_human_with_its_report(self, client, task_inputs, make_runner, drain):
        class AlwaysClaims(MockLLMProvider):
            async def generate_master_copy(self, context, *, topic):
                draft = await super().generate_master_copy(context, topic=topic)
                return draft.model_copy(update={"body": draft.body + " Clinically proven."})

            async def revise_master_copy(self, context, *, topic, current, feedback):
                return current

        runner = make_runner(llm=AlwaysClaims())
        task_id = await to_copy_review(client, task_inputs, runner, drain)
        task = await detail(client, task_id)
        assert len((await client.get(f"/tasks/{task_id}/versions")).json()) == 3  # Initial plus two bounded fixes.
        assert task["current_version"]["validation"]["passed"] is False


class TestImageStage:
    async def test_platform_content_and_images_are_produced(self, client, task_inputs, make_runner, drain, storage):
        runner = make_runner()
        task_id = await to_image_review(client, task_inputs, runner, drain)
        task = await detail(client, task_id)

        assert [asset["slide_number"] for asset in task["assets"]] == [1, 2, 3, 4]
        assert all(asset["is_mock"] and asset["provider"] == "mock" for asset in task["assets"])
        assert len(task["carousel_plan"]) == 4
        channels = {channel["platform"]: channel["payload"] for channel in task["channel_contents"]}
        assert channels["instagram"]["hashtags"] and channels["instagram"]["caption"]
        assert channels["facebook"]["post_text"]
        assert channels["instagram"]["caption"] != channels["facebook"]["post_text"]

        response = await client.get(task["assets"][0]["url"].removeprefix("/api/v1"))
        assert response.status_code == 200
        assert response.headers["content-type"] == "image/jpeg"
        from PIL import Image

        image = Image.open(io.BytesIO(response.content))
        assert image.format == "JPEG" and image.size == (1080, 1350)

    async def test_selective_regeneration_touches_only_chosen_slides(self, client, task_inputs, make_runner, drain):
        runner = make_runner()
        task_id = await to_image_review(client, task_inputs, runner, drain)
        before = {a["slide_number"]: a for a in (await detail(client, task_id))["assets"]}
        versions_before = (await client.get(f"/tasks/{task_id}/versions")).json()
        topics_before = (await client.get(f"/tasks/{task_id}/topics")).json()

        response = await client.post(
            f"/tasks/{task_id}/image-decision",
            json={"action": "regenerate", "slide_numbers": [2], "feedback": "Make it more minimalistic."},
        )
        assert response.status_code == 202
        await drain(runner)

        task = await detail(client, task_id)
        assert task["status"] == "AWAITING_IMAGE_REVIEW"
        after = {a["slide_number"]: a for a in task["assets"]}
        for number in (1, 3, 4):
            assert after[number]["id"] == before[number]["id"]
            assert after[number]["sha256"] == before[number]["sha256"]
        assert after[2]["id"] != before[2]["id"]
        assert after[2]["sha256"] != before[2]["sha256"]
        assert after[2]["asset_version"] == 2
        assert after[2]["visual_feedback"] == "Make it more minimalistic."

        history = (await client.get(f"/tasks/{task_id}/assets", params={"include_history": True})).json()
        old = next(a for a in history if a["id"] == before[2]["id"])
        assert old["status"] == "SUPERSEDED"
        # The old file stays downloadable as history.
        assert (await client.get(old["url"].removeprefix("/api/v1"))).status_code == 200

        # Topics and drafts are untouched: nothing upstream ran again.
        assert (await client.get(f"/tasks/{task_id}/versions")).json() == versions_before
        assert (await client.get(f"/tasks/{task_id}/topics")).json() == topics_before

    async def test_multiple_slides_and_repeated_regeneration(self, client, task_inputs, make_runner, drain):
        runner = make_runner()
        task_id = await to_image_review(client, task_inputs, runner, drain)
        for feedback in ("Round one", "Round two"):
            await client.post(
                f"/tasks/{task_id}/image-decision",
                json={"action": "regenerate", "slide_numbers": [2, 4], "feedback": feedback},
            )
            await drain(runner)
        assets = {a["slide_number"]: a for a in (await detail(client, task_id))["assets"]}
        assert {n: a["asset_version"] for n, a in assets.items()} == {1: 1, 2: 3, 3: 1, 4: 3}

    async def test_out_of_range_slide_is_rejected(self, client, task_inputs, make_runner, drain):
        runner = make_runner()
        task_id = await to_image_review(client, task_inputs, runner, drain)
        response = await client.post(
            f"/tasks/{task_id}/image-decision", json={"action": "regenerate", "slide_numbers": [9]}
        )
        assert response.status_code == 422

    async def test_stale_review_key_is_rejected(self, client, task_inputs, make_runner, drain):
        runner = make_runner()
        task_id = await to_image_review(client, task_inputs, runner, drain)
        key = (await detail(client, task_id))["review_key"]
        await client.post(f"/tasks/{task_id}/image-decision", json={"action": "regenerate", "slide_numbers": [1]})
        await drain(runner)
        response = await client.post(f"/tasks/{task_id}/image-decision", json={"action": "approve", "review_key": key})
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "STALE_REVIEW"

    @pytest.mark.parametrize("image_count", [3, 5])
    async def test_other_slide_counts(self, client, task_inputs, make_runner, drain, image_count):
        runner = make_runner()
        task_id = await to_image_review(client, {**task_inputs, "image_count": image_count}, runner, drain)
        assert len((await detail(client, task_id))["assets"]) == image_count

    async def test_product_without_a_photo_still_produces_slides(self, client, task_inputs, make_runner, drain):
        product = (
            await client.post(
                "/products", json={"name": "No Photo Toy", "category": "Dog Toys", "description": "A durable chew toy."}
            )
        ).json()
        runner = make_runner()
        task_id = await to_image_review(client, {**task_inputs, "product_ids": [product["id"]]}, runner, drain)
        assert len((await detail(client, task_id))["assets"]) == 4


class TestCompletion:
    async def test_approval_finishes_the_workflow_and_exports(self, client, task_inputs, make_runner, drain):
        runner = make_runner()
        task_id = await to_image_review(client, task_inputs, runner, drain)
        await client.post(f"/tasks/{task_id}/image-decision", json={"action": "regenerate", "slide_numbers": [2], "feedback": "Other"})
        await drain(runner)
        task = await detail(client, task_id)
        replaced_ids = {a["id"] for a in (await client.get(f"/tasks/{task_id}/assets", params={"include_history": True})).json()} - {a["id"] for a in task["assets"]}

        assert (await client.post(f"/tasks/{task_id}/image-decision", json={"action": "approve"})).status_code == 202
        await drain(runner)

        task = await detail(client, task_id)
        assert task["status"] == "READY"
        assert task["completed_at"] is not None
        assert task["available_actions"] == ["export"]
        assert all(a["status"] == "APPROVED" for a in task["assets"])
        state = await graph_state(runner, task_id, client)
        assert state.next == ()

        payloads = {c["platform"]: c["payload"] for c in task["channel_contents"]}
        current_ids = [a["id"] for a in task["assets"]]
        assert payloads["instagram"]["carousel_slide_ids"] == current_ids
        assert payloads["facebook"]["image_asset_ids"] == current_ids
        assert set(payloads["instagram"]["alt_text"]) == {"1", "2", "3", "4"}

        response = await client.get(f"/tasks/{task_id}/exports/all")
        assert response.status_code == 200
        assert response.headers["content-type"] == "application/zip"
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            names = set(archive.namelist())
            assert {"instagram/caption.txt", "instagram/hashtags.txt", "instagram/alt_text.json", "facebook/post.txt", "metadata.json", "README.md"} <= names
            for n in (1, 2, 3, 4):
                assert f"instagram/slide_0{n}.jpg" in names
                assert f"facebook/images/image_0{n}.jpg" in names
            metadata = __import__("json").loads(archive.read("metadata.json"))
            exported = {image["sha256"] for image in metadata["images"]}
            assert exported == {a["sha256"] for a in task["assets"]}
            assert hashlib.sha256(archive.read("instagram/slide_02.jpg")).hexdigest() in exported
            assert metadata["approved_content_version"]["id"] == task["approved_version_id"]
            assert metadata["contains_mock_content"] is True
            assert not replaced_ids & {image["asset_id"] for image in metadata["images"]}
            assert "must not be published" in archive.read("README.md").decode()

        for name, expected in (("instagram", "instagram/caption.txt"), ("facebook", "facebook/post.txt")):
            single = await client.get(f"/tasks/{task_id}/exports/{name}")
            assert single.status_code == 200
            with zipfile.ZipFile(io.BytesIO(single.content)) as archive:
                assert expected in archive.namelist()
                assert f"{name}/metadata.json" in archive.namelist()

    async def test_exports_are_blocked_until_ready(self, client, task_inputs, make_runner, drain):
        runner = make_runner()
        task_id = await to_image_review(client, task_inputs, runner, drain)
        response = await client.get(f"/tasks/{task_id}/exports/all")
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "EXPORT_NOT_READY"
        listing = (await client.get(f"/tasks/{task_id}/exports")).json()
        assert listing["ready"] is False and all(not e["available"] for e in listing["exports"])

    async def test_single_channel_task_only_produces_that_channel(self, client, task_inputs, make_runner, drain):
        runner = make_runner()
        task_id = await to_image_review(client, {**task_inputs, "channels": ["instagram"]}, runner, drain)
        await client.post(f"/tasks/{task_id}/image-decision", json={"action": "approve"})
        await drain(runner)
        assert [c["platform"] for c in (await client.get(f"/tasks/{task_id}/channels")).json()] == ["instagram"]
        assert (await client.get(f"/tasks/{task_id}/exports/facebook")).status_code == 404
        with zipfile.ZipFile(io.BytesIO((await client.get(f"/tasks/{task_id}/exports/all")).content)) as archive:
            assert not any(name.startswith("facebook/") for name in archive.namelist())


class TestCancellation:
    async def _assert_cancelled(self, client, runner, drain, task_id):
        await drain(runner)
        task = await detail(client, task_id)
        assert task["status"] == "CANCELLED"
        assert task["available_actions"] == []
        state = await graph_state(runner, task_id, client)
        assert state.next == () and state.values["workflow_status"] == "CANCELLED"

    async def test_cancel_at_topic_review(self, client, task_inputs, make_runner, drain):
        runner = make_runner()
        task_id = await to_topic_review(client, task_inputs, runner, drain)
        await client.post(f"/tasks/{task_id}/topic-decision", json={"action": "cancel"})
        await self._assert_cancelled(client, runner, drain, task_id)

    async def test_cancel_at_copy_review(self, client, task_inputs, make_runner, drain):
        runner = make_runner()
        task_id = await to_copy_review(client, task_inputs, runner, drain)
        current = (await detail(client, task_id))["current_version"]["id"]
        await client.post(f"/tasks/{task_id}/copy-decision", json={"action": "cancel", "current_version_id": current})
        await self._assert_cancelled(client, runner, drain, task_id)

    async def test_cancel_at_image_review(self, client, task_inputs, make_runner, drain):
        runner = make_runner()
        task_id = await to_image_review(client, task_inputs, runner, drain)
        await client.post(f"/tasks/{task_id}/image-decision", json={"action": "cancel"})
        await self._assert_cancelled(client, runner, drain, task_id)

    async def test_cancelled_task_accepts_no_more_decisions(self, client, task_inputs, make_runner, drain):
        runner = make_runner()
        task_id = await to_topic_review(client, task_inputs, runner, drain)
        await client.post(f"/tasks/{task_id}/topic-decision", json={"action": "cancel"})
        await drain(runner)
        response = await client.post(f"/tasks/{task_id}/topic-decision", json={"action": "regenerate"})
        assert response.status_code == 409

    async def test_queued_task_can_be_cancelled_before_a_worker_starts(self, client, task_inputs, make_runner, drain):
        task_id = await create_task(client, task_inputs)
        assert (await client.post(f"/tasks/{task_id}/cancel")).status_code == 200
        assert (await detail(client, task_id))["status"] == "CANCELLED"
        assert await drain(make_runner()) == 0


class TestInvalidDecisions:
    """The graph refuses bad input itself and stays interrupted, whatever a caller sends."""

    @pytest.mark.parametrize(
        "resume",
        [
            {"action": "approve"},
            {"action": "select"},
            {"action": "nonsense", "selected_topic_id": "x"},
        ],
    )
    async def test_graph_stays_interrupted_on_invalid_resume(self, client, task_inputs, make_runner, drain, resume):
        runner = make_runner()
        task_id = await to_topic_review(client, task_inputs, runner, drain)
        config = {"configurable": {"thread_id": (await detail(client, task_id))["thread_id"]}}

        with pytest.raises(ValidationError):
            await runner.graph.ainvoke(Command(resume=resume), config, context=runner.deps, durability="sync")

        state = await runner.graph.aget_state(config)
        assert state.next == ("review_topic",)
        assert state.interrupts

        # A valid decision still works afterwards.
        await select_first_topic(client, task_id)
        await drain(runner)
        assert (await detail(client, task_id))["status"] == "AWAITING_COPY_REVIEW"

    async def test_empty_resume_does_not_advance_the_graph(self, client, task_inputs, make_runner, drain):
        runner = make_runner()
        task_id = await to_topic_review(client, task_inputs, runner, drain)
        config = {"configurable": {"thread_id": (await detail(client, task_id))["thread_id"]}}
        await runner.graph.ainvoke(Command(resume={}), config, context=runner.deps, durability="sync")
        state = await runner.graph.aget_state(config)
        assert state.next == ("review_topic",) and state.interrupts


class CountingLLM(MockLLMProvider):
    """Fails a chosen call a chosen number of times, and counts every call."""

    def __init__(self, *, fail_method: str | None = None, failures: int = 0, error: Exception | None = None):
        super().__init__()
        self.fail_method, self.failures, self.error = fail_method, failures, error
        self.calls: dict[str, int] = {}

    def _note(self, method: str) -> None:
        self.calls[method] = self.calls.get(method, 0) + 1
        if method == self.fail_method and self.failures > 0:
            self.failures -= 1
            raise self.error

    async def generate_topics(self, context, **kwargs):
        self._note("generate_topics")
        return await super().generate_topics(context, **kwargs)

    async def generate_master_copy(self, context, **kwargs):
        self._note("generate_master_copy")
        return await super().generate_master_copy(context, **kwargs)

    async def revise_master_copy(self, context, **kwargs):
        self._note("revise_master_copy")
        return await super().revise_master_copy(context, **kwargs)

    async def plan_carousel(self, context, **kwargs):
        self._note("plan_carousel")
        return await super().plan_carousel(context, **kwargs)


class FlakyImages(ImageProvider):
    """Succeeds for the first calls, then fails a set number of times."""

    name = "mock"

    def __init__(self, *, succeed_first: int, failures: int, error: Exception) -> None:
        self.inner = MockImageProvider()
        self.succeed_first, self.failures, self.error = succeed_first, failures, error
        self.calls = 0

    async def generate_background(self, prompt, *, width, height):
        self.calls += 1
        if self.calls > self.succeed_first and self.failures > 0:
            self.failures -= 1
            raise self.error
        return await self.inner.generate_background(prompt, width=width, height=height)


class TestFailureAndRetry:
    async def test_transient_error_is_retried_within_the_node(self, client, task_inputs, make_runner, drain):
        llm = CountingLLM(fail_method="generate_topics", failures=2, error=ProviderTransientError("rate limited"))
        runner = make_runner(llm=llm, max_node_attempts=3)
        task_id = await to_topic_review(client, task_inputs, runner, drain)
        assert llm.calls["generate_topics"] == 3
        assert len((await client.get(f"/tasks/{task_id}/topics")).json()) == 5

    async def test_retries_are_bounded_and_end_in_a_recoverable_failure(self, client, task_inputs, make_runner, drain):
        llm = CountingLLM(fail_method="generate_topics", failures=99, error=ProviderTransientError("down"))
        runner = make_runner(llm=llm, max_node_attempts=3)
        task_id = await create_task(client, task_inputs)
        await drain(runner)
        task = await detail(client, task_id)
        assert task["status"] == "FAILED"
        assert task["error"]["code"] == "PROVIDER_TRANSIENT_ERROR"
        assert task["available_actions"] == ["retry", "cancel"]
        assert llm.calls["generate_topics"] == 3

    async def test_permanent_error_is_not_retried(self, client, task_inputs, make_runner, drain):
        llm = CountingLLM(fail_method="generate_topics", failures=99, error=ProviderPermanentError("bad key"))
        runner = make_runner(llm=llm)
        task_id = await create_task(client, task_inputs)
        await drain(runner)
        assert llm.calls["generate_topics"] == 1
        assert (await detail(client, task_id))["status"] == "FAILED"

    async def test_retry_endpoint_continues_without_repeating_finished_work(self, client, task_inputs, make_runner, drain):
        llm = CountingLLM(fail_method="generate_master_copy", failures=1, error=ProviderPermanentError("refused"))
        runner = make_runner(llm=llm)
        task_id = await to_topic_review(client, task_inputs, runner, drain)
        await select_first_topic(client, task_id)
        await drain(runner)
        assert (await detail(client, task_id))["status"] == "FAILED"

        response = await client.post(f"/tasks/{task_id}/retry")
        assert response.status_code == 202
        assert (await detail(client, task_id))["error"] is None
        await drain(runner)

        task = await detail(client, task_id)
        assert task["status"] == "AWAITING_COPY_REVIEW"
        assert llm.calls["generate_topics"] == 1, "Topics must not be generated again."
        assert llm.calls["generate_master_copy"] == 2
        assert len((await client.get(f"/tasks/{task_id}/versions")).json()) == 1

    async def test_only_failed_tasks_can_be_retried(self, client, task_inputs, make_runner, drain):
        runner = make_runner()
        task_id = await to_topic_review(client, task_inputs, runner, drain)
        response = await client.post(f"/tasks/{task_id}/retry")
        assert response.status_code == 409

    async def test_partial_image_failure_keeps_finished_slides(self, client, task_inputs, make_runner, drain, session_factory):
        images = FlakyImages(succeed_first=2, failures=1, error=ProviderPermanentError("refused"))
        runner = make_runner(image=images)
        task_id = await to_copy_review(client, task_inputs, runner, drain)
        await approve_current_copy(client, task_id)
        await drain(runner)
        assert (await detail(client, task_id))["status"] == "FAILED"
        saved = (await client.get(f"/tasks/{task_id}/assets")).json()
        assert [a["slide_number"] for a in saved] == [1, 2]

        await client.post(f"/tasks/{task_id}/retry")
        await drain(runner)
        task = await detail(client, task_id)
        assert task["status"] == "AWAITING_IMAGE_REVIEW"
        assert [a["slide_number"] for a in task["assets"]] == [1, 2, 3, 4]
        assert {a["id"] for a in saved} <= {a["id"] for a in task["assets"]}
        assert images.calls == 5  # Two kept, one failed, two more: no slide was paid for twice.
        async with session_factory() as session:
            count = await session.scalar(select(func.count()).select_from(GeneratedAsset).where(GeneratedAsset.task_id == UUID(task_id)))
        assert count == 4

    async def test_failed_regeneration_keeps_the_old_image_current(self, client, task_inputs, make_runner, drain):
        images = FlakyImages(succeed_first=4, failures=1, error=ProviderPermanentError("refused"))
        runner = make_runner(image=images)
        task_id = await to_image_review(client, task_inputs, runner, drain)
        before = {a["slide_number"]: a["id"] for a in (await detail(client, task_id))["assets"]}
        await client.post(f"/tasks/{task_id}/image-decision", json={"action": "regenerate", "slide_numbers": [2], "feedback": "New"})
        await drain(runner)
        task = await detail(client, task_id)
        assert task["status"] == "FAILED"
        assert {a["slide_number"]: a["id"] for a in task["assets"]} == before

        await client.post(f"/tasks/{task_id}/retry")
        await drain(runner)
        after = {a["slide_number"]: a for a in (await detail(client, task_id))["assets"]}
        assert after[2]["id"] != before[2] and after[2]["visual_feedback"] == "New"
        assert after[1]["id"] == before[1]

    async def test_decision_is_not_lost_when_failing_before_it_reaches_the_graph(
        self, client, task_inputs, make_runner, drain, monkeypatch
    ):
        runner = make_runner()
        task_id = await to_topic_review(client, task_inputs, runner, drain)
        topic = (await client.get(f"/tasks/{task_id}/topics")).json()[0]
        await client.post(f"/tasks/{task_id}/topic-decision", json={"action": "select", "selected_topic_id": topic["id"]})

        # The job dies before resuming: the graph is still paused on the same review.
        with monkeypatch.context() as patch:
            async def boom(*args, **kwargs):
                raise ProviderPermanentError("checkpoint unavailable")

            patch.setattr(runner.graph, "aget_state", boom)
            await drain(runner)
        assert (await detail(client, task_id))["status"] == "FAILED"

        await client.post(f"/tasks/{task_id}/retry")
        await drain(runner)
        task = await detail(client, task_id)
        assert task["status"] == "AWAITING_COPY_REVIEW"
        assert task["selected_topic"]["id"] == topic["id"]

    async def test_retrying_does_not_duplicate_database_records(self, client, task_inputs, make_runner, drain, session_factory):
        llm = CountingLLM(fail_method="generate_topics", failures=1, error=ProviderTransientError("hiccup"))
        runner = make_runner(llm=llm)
        task_id = await to_copy_review(client, task_inputs, runner, drain)
        async with session_factory() as session:
            topics = await session.scalar(select(func.count()).select_from(TopicSuggestion).where(TopicSuggestion.task_id == UUID(task_id)))
            versions = await session.scalar(select(func.count()).select_from(ContentVersion).where(ContentVersion.task_id == UUID(task_id)))
        assert (topics, versions) == (5, 1)
