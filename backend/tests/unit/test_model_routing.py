"""Model profiles, routing and vendor request formats, against fake HTTP. No paid API calls."""

import json
from pathlib import Path

import anthropic
import httpx
import httpx2
import pytest

from app.ai.providers import create_model_registry, create_model_router
from app.ai.providers.anthropic_provider import DEFAULT_MAX_TOKENS, AnthropicLLMProvider
from app.ai.providers.llm_provider import (
    DeepSeekLLMProvider,
    OpenAILLMProvider,
    strict_json_schema,
)
from app.ai.providers.mock_provider import MockLLMProvider
from app.ai.providers.model_config import (
    ModelConfig,
    ModelProfile,
    ModelRole,
    ProviderType,
    load_model_config,
)
from app.ai.providers.model_registry import ModelRegistry
from app.ai.providers.model_router import FallbackLLMProvider, ModelRouter
from app.core.config import Settings
from app.core.exceptions import (
    ProviderNotConfiguredError,
    ProviderPermanentError,
    ProviderRefusalError,
    ProviderTransientError,
    StructuredOutputError,
)
from app.schemas.content import TopicBatchOutput
from tests.unit.test_real_providers import topics_json
from tests.unit.test_validators import make_context

ACCEPTANCE_YAML = """
profiles:
  topics:
    provider: deepseek
    model: ${DEEPSEEK_MODEL}
    credential_env: DEEPSEEK_KEY_TOPICS
  copy:
    provider: anthropic
    model: ${CLAUDE_MODEL}
    credential_env: ANTHROPIC_KEY
    effort: high
  instagram:
    provider: openai
    model: ${OPENAI_MODEL}
    credential_env: OPENAI_KEY
  facebook:
    provider: deepseek
    model: ${DEEPSEEK_MODEL}
    credential_env: DEEPSEEK_KEY_FACEBOOK
roles:
  topic_generation: topics
  copy_generation: copy
  copy_revision: copy
  instagram_adaptation: instagram
  facebook_adaptation: facebook
  carousel_planning: instagram
"""
ENVIRON = {
    "DEEPSEEK_MODEL": "ds-model",
    "CLAUDE_MODEL": "claude-model",
    "OPENAI_MODEL": "gpt-model",
    "DEEPSEEK_KEY_TOPICS": "key-topics",
    "DEEPSEEK_KEY_FACEBOOK": "key-facebook",
    "ANTHROPIC_KEY": "key-anthropic",
    "OPENAI_KEY": "key-openai",
}


def plain_settings(**overrides) -> Settings:
    return Settings(_env_file=None, **overrides)


def yaml_settings(tmp_path: Path, text: str) -> Settings:
    path = tmp_path / "models.yaml"
    path.write_text(text, encoding="utf-8")
    return plain_settings(llm_profiles_path=path)


def single_profile(**fields) -> ModelConfig:
    return ModelConfig(profiles={"only": ModelProfile(**fields)}, default_profile="only")


def registry_for(config: ModelConfig, credentials=None) -> ModelRegistry:
    return ModelRegistry(config, credentials if credentials is not None else {"KEY": "secret"}, plain_settings())


def real_profile(provider: ProviderType, **fields) -> ModelProfile:
    bases = {
        ProviderType.OPENAI: "https://api.openai.com/v1",
        ProviderType.DEEPSEEK: "https://api.deepseek.com",
        ProviderType.ANTHROPIC: "https://api.anthropic.com",
    }
    return ModelProfile(provider=provider, model="test-model", base_url=bases[provider], **fields)


def chat_reply(content, finish_reason="stop", **message) -> httpx.Response:
    body = {"choices": [{"finish_reason": finish_reason, "message": {"content": content, **message}}]}
    return httpx.Response(200, json=body)


def anthropic_reply(text: str, stop_reason="end_turn", **extra) -> httpx2.Response:
    body = {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "model": "test-model",
        "content": [{"type": "text", "text": text}],
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": {"input_tokens": 1, "output_tokens": 1},
        **extra,
    }
    return httpx2.Response(200, json=body)


def claude_with(handler, **fields) -> AnthropicLLMProvider:
    client = anthropic.DefaultAsyncHttpxClient(transport=httpx2.MockTransport(handler))
    return AnthropicLLMProvider(real_profile(ProviderType.ANTHROPIC, **fields), "key-anthropic", http_client=client)


def deepseek_with(handler, **fields) -> DeepSeekLLMProvider:
    profile = real_profile(ProviderType.DEEPSEEK, structured_mode="json_object", **fields)
    return DeepSeekLLMProvider(profile, "key-deepseek", transport=httpx.MockTransport(handler))


def openai_with(handler, **fields) -> OpenAILLMProvider:
    profile = real_profile(ProviderType.OPENAI, structured_mode="json_schema", **fields)
    return OpenAILLMProvider(profile, "key-openai", transport=httpx.MockTransport(handler))


class TestRouting:
    def test_every_role_resolves_to_its_provider_and_model(self, tmp_path):
        settings = yaml_settings(tmp_path, ACCEPTANCE_YAML)
        router = create_model_router(settings, ENVIRON)
        assert {role.value: router.for_role(role).name for role in ModelRole} == {
            "topic_generation": "deepseek",
            "copy_generation": "anthropic",
            "copy_revision": "anthropic",
            "instagram_adaptation": "openai",
            "facebook_adaptation": "deepseek",
            "carousel_planning": "openai",
        }
        description = router.describe()
        assert description["topic_generation"] == "topics (deepseek:ds-model)"
        assert description["copy_revision"] == "copy (anthropic:claude-model)"
        assert not any(key in str(description) for key in ("key-topics", "key-anthropic", "key-openai"))

    def test_roles_receive_different_credentials(self, tmp_path):
        registry = create_model_registry(yaml_settings(tmp_path, ACCEPTANCE_YAML), ENVIRON)
        seen = {}

        def factory(profile, key):
            seen[profile.credential_env] = key
            return MockLLMProvider()

        for provider in (ProviderType.DEEPSEEK, ProviderType.ANTHROPIC, ProviderType.OPENAI):
            registry.register_provider(provider, factory)
        ModelRouter.from_registry(registry)
        assert seen == {
            "DEEPSEEK_KEY_TOPICS": "key-topics",
            "DEEPSEEK_KEY_FACEBOOK": "key-facebook",
            "ANTHROPIC_KEY": "key-anthropic",
            "OPENAI_KEY": "key-openai",
        }

    def test_profile_shared_by_roles_reuses_one_client(self, tmp_path):
        router = create_model_router(yaml_settings(tmp_path, ACCEPTANCE_YAML), ENVIRON)
        assert router.for_role("copy_generation") is router.for_role("copy_revision")
        assert router.for_role("instagram_adaptation") is router.for_role("carousel_planning")
        # The same vendor with a different key is a different client.
        assert router.for_role("topic_generation") is not router.for_role("facebook_adaptation")

    def test_unknown_role_fails_clearly(self):
        with pytest.raises(ValueError, match="not_a_role"):
            ModelRouter.uniform(MockLLMProvider()).for_role("not_a_role")

    def test_default_profile_covers_unmapped_roles(self):
        config = ModelConfig(
            profiles={
                "main": ModelProfile(provider="openai", model="m", credential_env="KEY"),
                "topics": ModelProfile(provider="deepseek", model="m", credential_env="KEY"),
            },
            default_profile="main",
            roles={"topic_generation": "topics"},
        )
        router = ModelRouter.from_registry(registry_for(config))
        assert router.for_role("topic_generation").name == "deepseek"
        assert router.for_role("carousel_planning").name == "openai"


class TestLegacyConfiguration:
    def test_mock_serves_every_role_without_any_credentials(self):
        router = create_model_router(plain_settings(llm_provider="mock", mock_llm_delay_seconds=0.5), {})
        providers = {router.for_role(role) for role in ModelRole}
        assert len(providers) == 1
        provider = providers.pop()
        assert isinstance(provider, MockLLMProvider) and provider.name == "mock"
        assert provider._delay_seconds == 0.5

    async def test_openai_compatible_serves_every_role_with_the_original_request(self):
        settings = plain_settings(
            llm_provider="openai_compatible",
            llm_api_key="legacy-key",
            llm_model="legacy-model",
            llm_base_url="https://llm.example.com/v1",
        )
        registry = create_model_registry(settings)
        seen = {}

        def handler(request):
            seen.update(url=str(request.url), auth=request.headers["authorization"], body=json.loads(request.content))
            return chat_reply(topics_json(5))

        from app.ai.providers.llm_provider import OpenAIChatProvider

        registry.register_provider(
            ProviderType.OPENAI_COMPATIBLE,
            lambda profile, key: OpenAIChatProvider(profile, key, transport=httpx.MockTransport(handler)),
        )
        router = ModelRouter.from_registry(registry)
        providers = {router.for_role(role) for role in ModelRole}
        assert len(providers) == 1
        provider = providers.pop()
        assert provider.name == "openai_compatible"

        await provider.generate_topics(make_context(), count=5)
        assert seen["url"] == "https://llm.example.com/v1/chat/completions"
        assert seen["auth"] == "Bearer legacy-key"
        assert set(seen["body"]) == {"model", "messages", "temperature", "response_format"}
        assert seen["body"]["temperature"] == 0.7
        assert seen["body"]["response_format"] == {"type": "json_object"}
        assert [m["role"] for m in seen["body"]["messages"]] == ["system", "user"]

    @pytest.mark.parametrize("overrides", [{"llm_model": "m"}, {"llm_api_key": "k"}, {}])
    def test_missing_legacy_settings_are_reported(self, overrides):
        with pytest.raises(ProviderNotConfiguredError, match="LLM_API_KEY and LLM_MODEL"):
            create_model_router(plain_settings(llm_provider="openai_compatible", **overrides))

    def test_profiles_file_replaces_the_legacy_settings(self, tmp_path):
        settings = yaml_settings(tmp_path, ACCEPTANCE_YAML)
        assert settings.llm_provider == "mock"
        router = create_model_router(settings, ENVIRON)
        assert all(router.for_role(role).name != "mock" for role in ModelRole)


class TestConfigurationErrors:
    def test_missing_credential_names_the_variable_only(self, tmp_path):
        environ = {key: value for key, value in ENVIRON.items() if key != "ANTHROPIC_KEY"}
        with pytest.raises(ProviderNotConfiguredError, match="'copy' needs the environment variable ANTHROPIC_KEY"):
            create_model_router(yaml_settings(tmp_path, ACCEPTANCE_YAML), environ)

    def test_unset_model_reference_is_reported(self, tmp_path):
        environ = {key: value for key, value in ENVIRON.items() if key != "CLAUDE_MODEL"}
        with pytest.raises(ProviderNotConfiguredError, match="CLAUDE_MODEL"):
            create_model_router(yaml_settings(tmp_path, ACCEPTANCE_YAML), environ)

    def test_credential_env_is_not_expanded_into_a_value(self, tmp_path):
        text = "profiles: {a: {provider: openai, model: m, credential_env: '${OPENAI_KEY}'}}\ndefault_profile: a\n"
        with pytest.raises(ProviderNotConfiguredError) as caught:
            load_model_config(yaml_settings(tmp_path, text).llm_profiles_path, ENVIRON)
        assert "key-openai" not in str(caught.value)

    @pytest.mark.parametrize(
        "line",
        ["api_key: sk-live-pasted-secret", "credential_env: sk-live-pasted-secret", "model: 123"],
    )
    def test_keys_in_the_file_are_rejected_without_being_repeated(self, tmp_path, line):
        text = f"profiles:\n  a:\n    provider: openai\n    {line}\ndefault_profile: a\n"
        with pytest.raises(ProviderNotConfiguredError, match="Invalid model configuration") as caught:
            load_model_config(yaml_settings(tmp_path, text).llm_profiles_path, ENVIRON)
        assert "sk-live-pasted-secret" not in str(caught.value)

    def test_invalid_yaml_does_not_quote_the_file(self, tmp_path):
        with pytest.raises(ProviderNotConfiguredError, match="not valid YAML") as caught:
            load_model_config(yaml_settings(tmp_path, "a: [sk-live-secret\nb: }").llm_profiles_path, ENVIRON)
        assert "sk-live-secret" not in str(caught.value)

    def test_missing_file_is_reported(self, tmp_path):
        with pytest.raises(ProviderNotConfiguredError, match="Could not read"):
            load_model_config(tmp_path / "absent.yaml", ENVIRON)

    def test_partial_roles_without_a_default_are_rejected(self, tmp_path):
        text = "profiles: {a: {provider: mock}}\nroles: {topic_generation: a}\n"
        with pytest.raises(ProviderNotConfiguredError, match="copy_generation"):
            load_model_config(yaml_settings(tmp_path, text).llm_profiles_path, ENVIRON)

    def test_unknown_role_and_undefined_profile_are_rejected(self, tmp_path):
        for text in (
            "profiles: {a: {provider: mock}}\ndefault_profile: a\nroles: {nope: a}\n",
            "profiles: {a: {provider: mock}}\ndefault_profile: missing\n",
        ):
            with pytest.raises(ProviderNotConfiguredError):
                load_model_config(yaml_settings(tmp_path, text).llm_profiles_path, ENVIRON)

    def test_profile_no_role_uses_needs_no_credential(self):
        config = ModelConfig(
            profiles={
                "used": ModelProfile(provider="mock"),
                "spare": ModelProfile(provider="openai", model="m", credential_env="UNSET"),
            },
            default_profile="used",
        )
        ModelRouter.from_registry(registry_for(config, {}))


class TestUnsupportedCombinations:
    @pytest.mark.parametrize(
        ("fields", "message"),
        [
            ({"provider": "anthropic", "temperature": 0.2}, "does not accept temperature"),
            ({"provider": "anthropic", "structured_mode": "json_object"}, "structured_mode json_object"),
            ({"provider": "deepseek", "structured_mode": "json_schema"}, "structured_mode json_schema"),
            ({"provider": "openai", "effort": "high"}, "does not accept effort"),
            ({"provider": "deepseek", "effort": "high"}, "does not accept effort"),
            ({"provider": "openai", "base_url": "http://api.example.com/v1"}, "must use HTTPS"),
            ({"provider": "openai_compatible"}, "set base_url"),
        ],
    )
    def test_real_providers(self, fields, message):
        config = single_profile(model="m", credential_env="KEY", **fields)
        with pytest.raises(ProviderNotConfiguredError, match=message):
            ModelRouter.from_registry(registry_for(config))

    @pytest.mark.parametrize("fields", [{"temperature": 0.5}, {"max_tokens": 100}])
    def test_mock(self, fields):
        with pytest.raises(ProviderNotConfiguredError, match="does not accept"):
            ModelRouter.from_registry(registry_for(single_profile(provider="mock", **fields)))

    def test_real_provider_needs_a_model(self):
        config = single_profile(provider="openai", credential_env="KEY")
        with pytest.raises(ProviderNotConfiguredError, match="set a model"):
            ModelRouter.from_registry(registry_for(config))

    def test_provider_defaults_are_applied(self):
        registry = registry_for(single_profile(provider="deepseek", model="m", credential_env="KEY"))
        profile = registry.resolve("only")
        assert profile.base_url == "https://api.deepseek.com"
        assert profile.structured_mode == "json_object"

    def test_local_http_is_allowed_for_compatible_servers(self):
        config = single_profile(
            provider="openai_compatible", model="m", credential_env="KEY", base_url="http://192.168.1.5:8080/v1"
        )
        ModelRouter.from_registry(registry_for(config))


class TestAnthropicFormat:
    async def test_uses_the_native_messages_api(self):
        seen = {}

        def handler(request):
            seen.update(url=str(request.url), headers=dict(request.headers), body=json.loads(request.content))
            return anthropic_reply(topics_json(5))

        result = await claude_with(handler, effort="high").generate_topics(make_context(), count=5)

        assert isinstance(result, TopicBatchOutput)
        assert seen["url"] == "https://api.anthropic.com/v1/messages"
        assert seen["headers"]["anthropic-version"] == "2026-10-21"
        assert seen["headers"]["authorization"] == "Bearer key-anthropic"
        body = seen["body"]
        assert body["model"] == "test-model"
        assert body["max_tokens"] == DEFAULT_MAX_TOKENS
        # The system prompt is a top-level field, not a message.
        assert "JSON schema" in body["system"]
        assert [message["role"] for message in body["messages"]] == ["user"]
        assert body["messages"][0]["content"].startswith("<untrusted_data>")
        # No OpenAI fields and no sampling parameters, which this API version rejects.
        assert not {"temperature", "top_p", "top_k", "response_format"} & set(body)
        assert body["output_config"]["effort"] == "high"
        schema = body["output_config"]["format"]
        assert schema["type"] == "json_schema"
        assert schema["schema"]["additionalProperties"] is False
        assert '"minLength":' not in json.dumps(schema["schema"])

    async def test_max_tokens_and_timeout_come_from_the_profile(self):
        seen = {}

        def handler(request):
            seen["body"] = json.loads(request.content)
            return anthropic_reply(topics_json(5))

        await claude_with(handler, max_tokens=500).generate_topics(make_context(), count=5)
        assert seen["body"]["max_tokens"] == 500
        assert "effort" not in seen["body"]["output_config"]

    async def test_reads_text_blocks_and_skips_thinking(self):
        def handler(request):
            return anthropic_reply(
                "", content=[{"type": "thinking", "thinking": "", "signature": "s"}, {"type": "text", "text": topics_json(5)}]
            )

        result = await claude_with(handler).generate_topics(make_context(), count=5)
        assert len(result.topics) == 5

    async def test_refusal_is_a_distinct_permanent_error(self):
        def handler(request):
            return anthropic_reply("", stop_reason="refusal", content=[], stop_details={"type": "refusal", "category": "bio"})

        with pytest.raises(ProviderRefusalError) as caught:
            await claude_with(handler).generate_topics(make_context(), count=5)
        assert caught.value.details == {"category": "bio"}

    async def test_truncation_fails_without_a_wasted_retry(self):
        calls = []

        def handler(request):
            calls.append(1)
            return anthropic_reply('{"topics": [', stop_reason="max_tokens")

        with pytest.raises(StructuredOutputError, match="max_tokens"):
            await claude_with(handler).generate_topics(make_context(), count=5)
        assert len(calls) == 1

    @pytest.mark.parametrize("status", [429, 500, 503, 529])
    async def test_retryable_statuses_are_transient_and_the_sdk_does_not_retry(self, status):
        calls = []

        def handler(request):
            calls.append(1)
            return httpx2.Response(status, json={"type": "error", "error": {"type": "x", "message": "busy"}})

        with pytest.raises(ProviderTransientError):
            await claude_with(handler).generate_topics(make_context(), count=5)
        assert len(calls) == 1

    @pytest.mark.parametrize("status", [400, 401, 402, 403, 404, 413])
    async def test_client_errors_are_permanent(self, status):
        def handler(request):
            return httpx2.Response(status, json={"type": "error", "error": {"type": "x", "message": "no"}})

        with pytest.raises(ProviderPermanentError) as caught:
            await claude_with(handler).generate_topics(make_context(), count=5)
        assert "key-anthropic" not in str(caught.value) + str(caught.value.details)

    @pytest.mark.parametrize("failure", [httpx2.ReadTimeout, httpx2.ConnectError])
    async def test_network_failures_are_transient(self, failure):
        def handler(request):
            raise failure("down", request=request)

        with pytest.raises(ProviderTransientError):
            await claude_with(handler).generate_topics(make_context(), count=5)


class TestDeepSeekFormat:
    async def test_uses_the_compatible_format_with_json_mode(self):
        seen = {}

        def handler(request):
            seen.update(url=str(request.url), auth=request.headers["authorization"], body=json.loads(request.content))
            return chat_reply(topics_json(5))

        await deepseek_with(handler, max_tokens=4000, temperature=1.0).generate_topics(make_context(), count=5)

        assert seen["url"] == "https://api.deepseek.com/chat/completions"
        assert seen["auth"] == "Bearer key-deepseek"
        body = seen["body"]
        assert body["response_format"] == {"type": "json_object"}
        assert body["max_tokens"] == 4000
        assert body["temperature"] == 1.0
        # DeepSeek requires the word "json" in the prompt for JSON mode.
        assert "json" in body["messages"][0]["content"].lower()

    async def test_blank_answer_is_retried_with_no_empty_assistant_turn(self):
        requests = []

        def handler(request):
            requests.append(json.loads(request.content))
            return chat_reply("   \n " if len(requests) == 1 else topics_json(5))

        result = await deepseek_with(handler).generate_topics(make_context(), count=5)
        assert len(result.topics) == 5
        assert [m["role"] for m in requests[1]["messages"]] == ["system", "user", "user"]

    async def test_blank_answers_do_not_retry_forever(self):
        calls = []

        def handler(request):
            calls.append(1)
            return chat_reply("  ")

        with pytest.raises(StructuredOutputError):
            await deepseek_with(handler, max_structured_retries=2).generate_topics(make_context(), count=5)
        assert len(calls) == 2

    @pytest.mark.parametrize(
        ("status", "error"),
        [(402, ProviderPermanentError), (422, ProviderPermanentError), (429, ProviderTransientError), (503, ProviderTransientError)],
    )
    async def test_documented_status_codes(self, status, error):
        with pytest.raises(error):
            await deepseek_with(lambda r: httpx.Response(status, text="x")).generate_topics(make_context(), count=5)

    async def test_capacity_finish_reason_is_transient(self):
        reply = chat_reply("", finish_reason="insufficient_system_resource")
        with pytest.raises(ProviderTransientError):
            await deepseek_with(lambda r: reply).generate_topics(make_context(), count=5)


class TestOpenAIFormat:
    async def test_uses_strict_schema_and_the_current_token_field(self):
        seen = {}

        def handler(request):
            seen.update(url=str(request.url), body=json.loads(request.content))
            return chat_reply(topics_json(5))

        await openai_with(handler, max_tokens=4000).generate_topics(make_context(), count=5)

        body = seen["body"]
        assert seen["url"] == "https://api.openai.com/v1/chat/completions"
        assert body["max_completion_tokens"] == 4000
        assert "max_tokens" not in body and "temperature" not in body
        assert body["response_format"]["type"] == "json_schema"
        assert body["response_format"]["json_schema"]["strict"] is True

    def test_strict_schema_closes_objects_and_keeps_field_names(self):
        schema = {
            "type": "object",
            "properties": {
                "default": {"type": "string", "minLength": 2},
                "tags": {"type": "array", "items": {"$ref": "#/$defs/Tag"}, "default": [], "maxItems": 3},
            },
            "required": ["default"],
            "$defs": {"Tag": {"type": "object", "properties": {"title": {"type": "string", "maxLength": 9}}}},
        }
        assert strict_json_schema(schema) == {
            "type": "object",
            "properties": {
                "default": {"type": "string"},
                "tags": {"type": "array", "items": {"$ref": "#/$defs/Tag"}, "maxItems": 3},
            },
            "required": ["default", "tags"],
            "additionalProperties": False,
            "$defs": {
                "Tag": {
                    "type": "object",
                    "properties": {"title": {"type": "string"}},
                    "required": ["title"],
                    "additionalProperties": False,
                }
            },
        }

    async def test_refusal_and_truncation_are_reported(self):
        with pytest.raises(ProviderRefusalError):
            reply = chat_reply(None, refusal="I can't help with that.")
            await openai_with(lambda r: reply).generate_topics(make_context(), count=5)
        with pytest.raises(ProviderRefusalError):
            reply = chat_reply(None, finish_reason="content_filter")
            await openai_with(lambda r: reply).generate_topics(make_context(), count=5)
        with pytest.raises(StructuredOutputError, match="max_tokens"):
            reply = chat_reply('{"topics":', finish_reason="length")
            await openai_with(lambda r: reply).generate_topics(make_context(), count=5)


class TestStructuredOutputAcrossProviders:
    @staticmethod
    def build(provider_name, replies, requests):
        def next_reply(request):
            requests.append(json.loads(request.content))
            return replies[len(requests) - 1]

        if provider_name == "anthropic":
            return claude_with(lambda request: anthropic_reply(next_reply(request)))
        if provider_name == "deepseek":
            return deepseek_with(lambda request: chat_reply(next_reply(request)))
        return openai_with(lambda request: chat_reply(next_reply(request)))

    @pytest.mark.parametrize("provider_name", ["anthropic", "deepseek", "openai"])
    async def test_invalid_output_is_corrected_within_the_limit(self, provider_name):
        requests = []
        provider = self.build(provider_name, ["not json", topics_json(4), topics_json(5)], requests)
        result = await provider.generate_topics(make_context(), count=5)
        assert len(result.topics) == 5
        assert len(requests) == 3
        assert "invalid" in requests[2]["messages"][-1]["content"]
        assert requests[2]["messages"][-2] == {"role": "assistant", "content": topics_json(4)}

    @pytest.mark.parametrize("provider_name", ["anthropic", "deepseek", "openai"])
    async def test_malformed_output_is_never_accepted(self, provider_name):
        requests = []
        provider = self.build(provider_name, ['{"topics": []}'] * 3, requests)
        with pytest.raises(StructuredOutputError):
            await provider.generate_topics(make_context(), count=5)
        assert len(requests) == 3


class ScriptedLLM(MockLLMProvider):
    def __init__(self, name, error=None):
        super().__init__()
        self.name = name
        self.error = error
        self.calls = 0

    async def generate_topics(self, context, *, count, feedback=None, previous_titles=None):
        self.calls += 1
        if self.error:
            raise self.error
        return await super().generate_topics(context, count=count)


class TestFallback:
    def wrap(self, primary, fallback):
        return FallbackLLMProvider(ModelRole.TOPIC_GENERATION, primary, fallback)

    async def test_primary_answers_when_healthy(self):
        primary, fallback = ScriptedLLM("primary"), ScriptedLLM("fallback")
        llm = self.wrap(primary, fallback)
        await llm.generate_topics(make_context(), count=2)
        assert llm.name == "primary" and fallback.calls == 0

    @pytest.mark.parametrize(
        "error",
        [ProviderTransientError("x"), StructuredOutputError("x"), ProviderRefusalError("x")],
    )
    async def test_recoverable_failures_use_the_fallback_and_record_it(self, error):
        llm = self.wrap(ScriptedLLM("primary", error), ScriptedLLM("fallback"))
        await llm.generate_topics(make_context(), count=2)
        assert llm.name == "fallback"

    @pytest.mark.parametrize("error", [ProviderPermanentError("bad key"), ProviderNotConfiguredError("x")])
    async def test_configuration_failures_are_not_hidden(self, error):
        fallback = ScriptedLLM("fallback")
        with pytest.raises(type(error)):
            await self.wrap(ScriptedLLM("primary", error), fallback).generate_topics(make_context(), count=2)
        assert fallback.calls == 0

    async def test_fallback_failure_surfaces(self):
        llm = self.wrap(ScriptedLLM("primary", ProviderTransientError("a")), ScriptedLLM("fallback", ProviderTransientError("b")))
        with pytest.raises(ProviderTransientError, match="b"):
            await llm.generate_topics(make_context(), count=2)

    def test_router_wraps_only_roles_with_a_fallback(self):
        config = ModelConfig(
            profiles={
                "a": ModelProfile(provider="openai", model="m", credential_env="KEY", fallback_profile="b"),
                "b": ModelProfile(provider="deepseek", model="m", credential_env="KEY"),
            },
            default_profile="b",
            roles={"copy_generation": "a"},
        )
        router = ModelRouter.from_registry(registry_for(config))
        assert isinstance(router.for_role("copy_generation"), FallbackLLMProvider)
        assert router.for_role("copy_generation") is not router.for_role("copy_generation")
        assert isinstance(router.for_role("topic_generation"), DeepSeekLLMProvider)

    def test_fallback_credential_is_checked_at_startup(self):
        config = ModelConfig(
            profiles={
                "a": ModelProfile(provider="openai", model="m", credential_env="KEY", fallback_profile="b"),
                "b": ModelProfile(provider="deepseek", model="m", credential_env="OTHER"),
            },
            default_profile="a",
        )
        with pytest.raises(ProviderNotConfiguredError, match="OTHER"):
            ModelRouter.from_registry(registry_for(config))

    @pytest.mark.parametrize(
        "profiles",
        [
            {"a": {"provider": "openai", "fallback_profile": "absent"}},
            {"a": {"provider": "openai", "fallback_profile": "a"}},
            {
                "a": {"provider": "openai", "fallback_profile": "b"},
                "b": {"provider": "openai", "fallback_profile": "c"},
                "c": {"provider": "openai"},
            },
            {"a": {"provider": "openai", "fallback_profile": "m"}, "m": {"provider": "mock"}},
            {"a": {"provider": "mock", "fallback_profile": "b"}, "b": {"provider": "openai"}},
        ],
    )
    def test_invalid_fallback_chains_are_rejected(self, profiles):
        with pytest.raises(ValueError):
            ModelConfig(profiles=profiles, default_profile="a")


class TestClientLifecycle:
    async def test_real_clients_close_once_and_are_not_recreated_per_call(self, tmp_path):
        router = create_model_router(yaml_settings(tmp_path, ACCEPTANCE_YAML), ENVIRON)
        first = router.for_role("topic_generation")
        http_client = first._client
        assert router.for_role("topic_generation")._client is http_client
        claude = router.for_role("copy_generation")
        await router.aclose()
        assert http_client.is_closed
        assert claude._client.is_closed()
        await router.aclose()  # A second close is harmless.

    async def test_one_failed_close_does_not_stop_the_others(self):
        closed = []

        class Closable(MockLLMProvider):
            def __init__(self, label, fail=False):
                super().__init__()
                self.label, self.fail = label, fail

            async def aclose(self):
                closed.append(self.label)
                if self.fail:
                    raise RuntimeError("boom")

        config = ModelConfig(
            profiles={
                "a": ModelProfile(provider="openai", model="m", credential_env="KEY"),
                "b": ModelProfile(provider="deepseek", model="m", credential_env="KEY"),
            },
            default_profile="a",
            roles={"topic_generation": "b"},
        )
        registry = registry_for(config)
        registry.register_provider(ProviderType.OPENAI, lambda p, k: Closable("a", fail=True))
        registry.register_provider(ProviderType.DEEPSEEK, lambda p, k: Closable("b"))
        await ModelRouter.from_registry(registry).aclose()
        assert sorted(closed) == ["a", "b"]

    async def test_mock_only_router_closes_cleanly(self):
        await create_model_router(plain_settings(), {}).aclose()


def test_example_profiles_file_is_valid():
    path = Path(__file__).resolve().parents[3] / "config" / "models.example.yaml"
    config = load_model_config(
        path,
        {"DEEPSEEK_MODEL": "d", "CLAUDE_MODEL": "c", "OPENAI_MODEL": "o"},
    )
    registry = ModelRegistry(
        config,
        {"DEEPSEEK_API_KEY": "1", "ANTHROPIC_API_KEY": "2", "OPENAI_API_KEY": "3"},
        plain_settings(),
    )
    registry.validate()
    assert {config.profiles[config.profile_name_for(role)].provider for role in ModelRole} == {
        ProviderType.DEEPSEEK,
        ProviderType.ANTHROPIC,
        ProviderType.OPENAI,
    }
