"""HTTP behavior: status codes, validation, error format and safety."""

from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr

from app.main import create_app
from tests.conftest import BRAND_BODY, PRODUCT_BODY, png_bytes
from tests.integration.test_workflow import create_task, detail, to_copy_review, to_topic_review

pytestmark = pytest.mark.integration


class TestHealth:
    async def test_liveness(self, client):
        response = await client.get("/health")
        assert response.status_code == 200 and response.json()["status"] == "ok"

    async def test_readiness_checks_real_dependencies(self, client):
        response = await client.get("/health/ready")
        assert response.status_code == 200
        body = response.json()
        assert body["checks"] == {"database": True, "migrations": True, "checkpoints": True, "storage": True}
        assert body["providers"] == {"llm": "mock", "image": "mock"}

    async def test_openapi_is_generated_under_the_versioned_prefix(self, client):
        spec = (await client.get("http://test/openapi.json")).json()
        assert "/api/v1/tasks/{task_id}/copy-decision" in spec["paths"]
        assert "/api/v1/tasks/{task_id}/exports/all" in spec["paths"]


class TestProducts:
    async def test_crud(self, client):
        created = await client.post("/products", json={**PRODUCT_BODY, "sku": "CAT-1", "price": "19.99", "currency": "USD"})
        assert created.status_code == 201
        product = created.json()
        assert product["status"] == "ACTIVE" and product["price"] == "19.99"
        assert (await client.get(f"/products/{product['id']}")).json()["name"] == PRODUCT_BODY["name"]
        assert [p["id"] for p in (await client.get("/products")).json()] == [product["id"]]

        patched = await client.patch(f"/products/{product['id']}", json={"name": "New Name"})
        assert patched.status_code == 200
        assert patched.json()["name"] == "New Name"
        assert patched.json()["description"] == PRODUCT_BODY["description"], "Unset fields must not change."

        assert (await client.delete(f"/products/{product['id']}")).status_code == 204
        assert (await client.get("/products")).json() == []
        assert len((await client.get("/products", params={"include_archived": True})).json()) == 1

    async def test_duplicate_sku_conflicts(self, client):
        await client.post("/products", json={**PRODUCT_BODY, "sku": "DUP"})
        response = await client.post("/products", json={**PRODUCT_BODY, "sku": "DUP"})
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "DUPLICATE_SKU"

    async def test_invalid_body_uses_the_error_format(self, client):
        response = await client.post("/products", json={"name": ""})
        assert response.status_code == 422
        error = response.json()["error"]
        assert error["code"] == "VALIDATION_ERROR"
        assert error["details"]["errors"]

    async def test_missing_product_is_404_in_the_error_format(self, client):
        response = await client.get(f"/products/{uuid4()}")
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "NOT_FOUND"

    async def test_malformed_uuid_is_422(self, client):
        assert (await client.get("/products/not-a-uuid")).status_code == 422


class TestImages:
    async def _product(self, client) -> str:
        return (await client.post("/products", json=PRODUCT_BODY)).json()["id"]

    async def test_upload_list_and_download(self, client):
        product_id = await self._product(client)
        data = png_bytes((120, 80))
        response = await client.post(f"/products/{product_id}/images", files={"file": ("x.png", data, "image/png")})
        assert response.status_code == 201
        image = response.json()
        assert (image["width"], image["height"], image["mime_type"]) == (120, 80, "image/png")
        assert "file_path" not in image

        listing = (await client.get(f"/products/{product_id}/images")).json()
        assert [i["id"] for i in listing] == [image["id"]]
        download = await client.get(image["url"].removeprefix("/api/v1"))
        assert download.status_code == 200 and download.content == data

    async def test_client_filename_cannot_affect_the_stored_path(self, client, session_factory):
        from sqlalchemy import select

        from app.models import ProductAsset

        product_id = await self._product(client)
        files = {"file": ("../../../evil.png", png_bytes(), "image/png")}
        assert (await client.post(f"/products/{product_id}/images", files=files)).status_code == 201
        async with session_factory() as session:
            record = await session.scalar(select(ProductAsset))
        assert "evil" not in record.file_path and ".." not in record.file_path

    async def test_declared_type_is_not_trusted(self, client):
        product_id = await self._product(client)
        files = {"file": ("x.png", b"<script>alert(1)</script>", "image/png")}
        response = await client.post(f"/products/{product_id}/images", files=files)
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "INVALID_IMAGE"

    async def test_oversized_upload_is_rejected(self, client, settings, monkeypatch):
        product_id = await self._product(client)
        monkeypatch.setattr(settings, "max_upload_bytes", 100)
        files = {"file": ("x.png", png_bytes((300, 300)), "image/png")}
        response = await client.post(f"/products/{product_id}/images", files=files)
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "UPLOAD_TOO_LARGE"

    async def test_unknown_asset_is_404(self, client):
        assert (await client.get(f"/assets/{uuid4()}")).status_code == 404

    async def test_missing_file_gives_an_error_without_leaking_paths(self, client, storage):
        product_id = await self._product(client)
        image = (await client.post(f"/products/{product_id}/images", files={"file": ("x.png", png_bytes(), "image/png")})).json()
        for path in (storage.root / "products" / product_id).iterdir():
            path.unlink()
        response = await client.get(image["url"].removeprefix("/api/v1"))
        assert response.status_code == 500
        assert response.json()["error"]["code"] == "MEDIA_FILE_MISSING"
        assert str(storage.root) not in response.text


class TestBrands:
    async def test_crud(self, client):
        created = await client.post("/brands", json=BRAND_BODY)
        assert created.status_code == 201
        brand = created.json()
        assert brand["default_locale"] == "en-US" and brand["has_logo"] is False
        assert len((await client.get("/brands")).json()) == 1
        patched = await client.patch(f"/brands/{brand['id']}", json={"preferred_cta": "Shop now"})
        assert patched.json()["preferred_cta"] == "Shop now"
        assert patched.json()["brand_voice"] == BRAND_BODY["brand_voice"]

    async def test_duplicate_name_conflicts(self, client):
        await client.post("/brands", json=BRAND_BODY)
        response = await client.post("/brands", json=BRAND_BODY)
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "DUPLICATE_BRAND"

    async def test_non_english_locale_is_rejected(self, client):
        assert (await client.post("/brands", json={**BRAND_BODY, "default_locale": "zh-CN"})).status_code == 422

    async def test_logo_upload(self, client):
        brand = (await client.post("/brands", json=BRAND_BODY)).json()
        response = await client.post(f"/brands/{brand['id']}/logo", files={"file": ("l.png", png_bytes(), "image/png")})
        assert response.status_code == 200 and response.json()["has_logo"] is True

    async def test_missing_brand_is_404(self, client):
        assert (await client.get(f"/brands/{uuid4()}")).status_code == 404


class TestReviews:
    REVIEW = {
        "rating": 5,
        "review_text": "We enjoy this toy every evening at home.",
        "source": "order_review",
        "source_reference": "ORDER-1001",
        "permission_to_use": True,
        "verified_status": "VERIFIED",
    }

    async def test_store_and_list_with_provenance(self, client):
        product_id = (await client.post("/products", json=PRODUCT_BODY)).json()["id"]
        created = await client.post(f"/products/{product_id}/reviews", json=self.REVIEW)
        assert created.status_code == 201
        listed = (await client.get(f"/products/{product_id}/reviews")).json()
        assert listed[0]["source_reference"] == "ORDER-1001"

    @pytest.mark.parametrize("change", [{"rating": 6}, {"rating": 0}, {"source_reference": ""}, {"review_text": ""}])
    async def test_invalid_reviews_are_rejected(self, client, change):
        product_id = (await client.post("/products", json=PRODUCT_BODY)).json()["id"]
        response = await client.post(f"/products/{product_id}/reviews", json={**self.REVIEW, **change})
        assert response.status_code == 422

    async def test_review_needs_an_existing_product(self, client):
        assert (await client.post(f"/products/{uuid4()}/reviews", json=self.REVIEW)).status_code == 404

    @pytest.mark.parametrize(
        ("change", "usable"),
        [
            ({}, True),
            ({"permission_to_use": False}, False),
            ({"verified_status": "UNVERIFIED"}, False),
        ],
    )
    async def test_only_authorized_verified_reviews_reach_the_ai(
        self, client, task_inputs, make_runner, drain, change, usable
    ):
        product_id = task_inputs["product_ids"][0]
        review = (await client.post(f"/products/{product_id}/reviews", json={**self.REVIEW, **change})).json()
        runner = make_runner()
        task_id = await to_copy_review(client, task_inputs, runner, drain)
        content = (await detail(client, task_id))["current_version"]["content"]
        if usable:
            assert content["source_review_ids"] == [review["id"]]
            assert self.REVIEW["review_text"] in content["body"]
        else:
            assert content["source_review_ids"] == []
            assert self.REVIEW["review_text"] not in content["body"]


class TestTasks:
    async def test_creation_returns_202_without_doing_ai_work(self, client, task_inputs):
        response = await client.post("/tasks", json=task_inputs)
        assert response.status_code == 202
        body = response.json()
        assert body["status"] == "QUEUED" and body["thread_id"].startswith("content-task-")
        assert (await client.get(f"/tasks/{body['task_id']}/topics")).json() == []

    @pytest.mark.parametrize(
        "change",
        [{"image_count": 2}, {"image_count": 6}, {"product_ids": []}, {"channels": []}, {"brand_id": "not-a-uuid"}],
    )
    async def test_invalid_requests_are_rejected(self, client, task_inputs, change):
        assert (await client.post("/tasks", json={**task_inputs, **change})).status_code == 422

    async def test_unknown_references_are_rejected(self, client, task_inputs):
        for change in ({"brand_id": str(uuid4())}, {"product_ids": [str(uuid4())]}):
            response = await client.post("/tasks", json={**task_inputs, **change})
            assert response.status_code == 422

    async def test_archived_product_is_rejected(self, client, task_inputs):
        await client.delete(f"/products/{task_inputs['product_ids'][0]}")
        assert (await client.post("/tasks", json=task_inputs)).status_code == 422

    async def test_unsupported_channel_is_rejected_and_channels_are_normalized(self, client, task_inputs):
        response = await client.post("/tasks", json={**task_inputs, "channels": ["tiktok"]})
        assert response.status_code == 422
        assert response.json()["error"]["details"]["supported"] == ["facebook", "instagram"]
        task_id = await create_task(client, {**task_inputs, "channels": ["Instagram", "instagram"]})
        assert (await detail(client, task_id))["channels"] == ["instagram"]

    async def test_defaults_are_applied(self, client, task_inputs, settings):
        body = {key: value for key, value in task_inputs.items() if key != "image_count"}
        task_id = await create_task(client, body)
        task = await detail(client, task_id)
        assert task["image_count"] == settings.default_image_count
        assert task["target_market"] == settings.default_target_market
        assert task["channels"] == ["instagram", "facebook"]

    async def test_detail_describes_the_review_stage_for_a_frontend(self, client, task_inputs, make_runner, drain):
        runner = make_runner()
        task_id = await to_topic_review(client, task_inputs, runner, drain)
        task = await detail(client, task_id)
        assert task["review_stage"] == "TOPIC"
        assert task["review_key"] == "topic:batch:1"
        assert task["decision_in_progress"] is False
        assert "__interrupt__" not in str(task)

    async def test_list_filters_by_status(self, client, task_inputs):
        await create_task(client, task_inputs)
        assert len((await client.get("/tasks", params={"status": "QUEUED"})).json()) == 1
        assert (await client.get("/tasks", params={"status": "READY"})).json() == []
        assert (await client.get("/tasks", params={"status": "NONSENSE"})).status_code == 422

    async def test_missing_task_endpoints_are_404(self, client):
        missing = uuid4()
        for path in ("", "/events", "/topics", "/versions", "/assets", "/channels", "/exports", "/exports/all"):
            assert (await client.get(f"/tasks/{missing}{path}")).status_code == 404, path


class TestDecisionValidation:
    async def test_wrong_stage_conflicts_with_the_documented_format(self, client, task_inputs, make_runner, drain):
        runner = make_runner()
        task_id = await to_topic_review(client, task_inputs, runner, drain)
        response = await client.post(
            f"/tasks/{task_id}/copy-decision", json={"action": "approve", "current_version_id": str(uuid4())}
        )
        assert response.status_code == 409
        assert response.json() == {
            "error": {
                "code": "INVALID_TASK_STATE",
                "message": "The task is not awaiting copy approval.",
                "details": {"current_status": "AWAITING_TOPIC_REVIEW"},
            }
        }
        response = await client.post(f"/tasks/{task_id}/image-decision", json={"action": "approve"})
        assert response.status_code == 409

    async def test_decision_before_the_graph_has_paused_conflicts(self, client, task_inputs):
        task_id = await create_task(client, task_inputs)
        response = await client.post(f"/tasks/{task_id}/topic-decision", json={"action": "regenerate"})
        assert response.status_code == 409

    async def test_invalid_actions_are_422(self, client, task_inputs, make_runner, drain):
        runner = make_runner()
        task_id = await to_topic_review(client, task_inputs, runner, drain)
        for body in ({"action": "approve"}, {"action": "select"}, {}):
            assert (await client.post(f"/tasks/{task_id}/topic-decision", json=body)).status_code == 422

    async def test_topic_from_another_task_is_rejected(self, client, task_inputs, make_runner, drain):
        runner = make_runner()
        first = await to_topic_review(client, task_inputs, runner, drain)
        second = await to_topic_review(client, task_inputs, runner, drain)
        foreign = (await client.get(f"/tasks/{second}/topics")).json()[0]["id"]
        response = await client.post(f"/tasks/{first}/topic-decision", json={"action": "select", "selected_topic_id": foreign})
        assert response.status_code == 422

    async def test_decision_on_a_missing_task_is_404(self, client):
        response = await client.post(f"/tasks/{uuid4()}/topic-decision", json={"action": "regenerate"})
        assert response.status_code == 404


class TestSecurity:
    async def test_api_key_is_enforced_when_configured(self, settings, session_factory, storage, clean_db):
        secured = settings.model_copy(update={"api_key": SecretStr("local-secret")})
        from app.core import security

        original = security.get_settings
        security.get_settings = lambda: secured
        try:
            app = create_app(secured)
            app.state.settings = secured
            app.state.session_factory = session_factory
            app.state.storage = storage
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test/api/v1") as client:
                denied = await client.get("/brands")
                assert denied.status_code == 401
                assert denied.json()["error"]["code"] == "UNAUTHORIZED"
                wrong = await client.get("/brands", headers={"X-API-Key": "wrong"})
                assert wrong.status_code == 401
                allowed = await client.get("/brands", headers={"X-API-Key": "local-secret"})
                assert allowed.status_code == 200
        finally:
            security.get_settings = original

    async def test_unexpected_errors_do_not_leak_details(self, settings, storage):
        app = create_app(settings)

        class BrokenFactory:
            def __call__(self):
                raise RuntimeError("password=hunter2 at C:\\secret\\path")

        app.state.settings = settings
        app.state.session_factory = BrokenFactory()
        app.state.storage = storage
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://test/api/v1") as client:
            response = await client.get("/brands")
        assert response.status_code == 500
        assert response.json()["error"]["code"] == "INTERNAL_ERROR"
        assert "hunter2" not in response.text and "secret" not in response.text

    async def test_responses_never_contain_server_paths(self, client, task_inputs, make_runner, drain, storage):
        runner = make_runner()
        task_id = await to_copy_review(client, task_inputs, runner, drain)
        current = (await detail(client, task_id))["current_version"]["id"]
        await client.post(f"/tasks/{task_id}/copy-decision", json={"action": "approve", "current_version_id": current})
        await drain(runner)
        for path in (f"/tasks/{task_id}", f"/tasks/{task_id}/assets", f"/products/{task_inputs['product_ids'][0]}/images"):
            text = (await client.get(path)).text
            assert str(storage.root) not in text
            assert "file_path" not in text
