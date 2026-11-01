import pytest

from app.ai.providers.mock_provider import MockLLMProvider
from app.ai.validators.content_validator import validate_master_copy, validate_text
from app.ai.validators.product_validator import ensure_context_is_usable
from app.core.exceptions import WorkflowError
from app.schemas.content import (
    BrandFacts,
    GenerationContext,
    MasterCopy,
    ProductFacts,
    ReviewFacts,
    TopicOutput,
)


def make_context(**overrides) -> GenerationContext:
    values = {
        "brand": BrandFacts(brand_name="Paws & Play", prohibited_claims=["best in the world"]),
        "products": [
            ProductFacts(
                id="p1",
                name="Cat Ball",
                category="Cat Toys",
                description="An interactive toy for playtime.",
                key_features=["Lightweight design"],
            )
        ],
        "target_market": "US",
        "channels": ["instagram"],
        "image_count": 4,
        "target_word_count": 700,
    }
    return GenerationContext(**{**values, **overrides})


@pytest.mark.parametrize(
    ("text", "code"),
    [
        ("Thousands of customers love this toy.", "UNSUPPORTED_SOCIAL_PROOF"),
        ("Every dog owner recommends this product.", "UNSUPPORTED_SOCIAL_PROOF"),
        ("Our best-selling toy of the year.", "UNSUPPORTED_SOCIAL_PROOF"),
        ("95% of cats play more.", "UNSUPPORTED_STATISTIC"),
        ("It is clinically proven to help.", "UNSUPPORTED_MEDICAL_CLAIM"),
        ("A vet-approved design.", "UNSUPPORTED_MEDICAL_CLAIM"),
        ("This toy reduces anxiety in cats.", "UNSUPPORTED_MEDICAL_CLAIM"),
        ("Made from BPA-free plastic.", "UNSUPPORTED_CERTIFICATION"),
        ("Fully non-toxic materials.", "UNSUPPORTED_CERTIFICATION"),
        ("Get 20% off today.", "UNSUPPORTED_OFFER"),
        ("Includes a lifetime warranty.", "UNSUPPORTED_OFFER"),
        ("My cat has used this every day for six months.", "IMPERSONATED_EXPERIENCE"),
        ("We tried it for a week and loved it.", "IMPERSONATED_EXPERIENCE"),
    ],
)
def test_unsupported_claims_are_errors(text, code):
    report = validate_text(text, make_context())
    assert report.has_errors
    assert code in {finding.code for finding in report.findings}


@pytest.mark.parametrize(
    "text",
    [
        "Is your indoor cat getting bored?",
        "Short play sessions keep things interesting.",
        "This lightweight toy rolls easily across the floor.",
        "Ask your veterinarian if you have health questions.",
        "Reward your dog with treats after playtime.",
    ],
)
def test_ordinary_marketing_copy_passes(text):
    assert not validate_text(text, make_context()).findings


def test_claim_present_in_product_data_is_allowed():
    product = ProductFacts(
        id="p1", name="Bowl", category="Feeding", description="A sturdy bowl.", materials=["BPA-free plastic"]
    )
    assert not validate_text("Made from BPA-free plastic.", make_context(products=[product])).has_errors


def test_brand_prohibited_claim_is_an_error():
    report = validate_text("This is the Best In The World!", make_context())
    assert "PROHIBITED_CLAIM" in {finding.code for finding in report.findings}


def test_non_english_text_is_an_error():
    report = validate_text("A great toy 好玩的玩具", make_context())
    assert "NON_ENGLISH_TEXT" in {finding.code for finding in report.findings}


def test_untraceable_quote_is_flagged_but_authorized_quote_is_not():
    quote = "My cat chases this ball around every single evening"
    reviews = [ReviewFacts(id="r1", product_id="p1", rating=5, review_text=quote)]
    with_review = validate_text(f'One customer said: "{quote}"', make_context(reviews=reviews))
    assert not with_review.findings
    without_review = validate_text('One customer said: "This changed our whole family routine"', make_context())
    assert "UNTRACEABLE_QUOTE" in {finding.code for finding in without_review.findings}


def _copy(**overrides) -> MasterCopy:
    values = {
        "title": "A title",
        "opening_hook": "A hook",
        "body": "word " * 700,
        "key_takeaways": ["One"],
        "featured_product_ids": ["p1"],
        "call_to_action": "Take a look",
    }
    return MasterCopy(**{**values, **overrides})


def test_master_copy_must_reference_known_records():
    report = validate_master_copy(_copy(featured_product_ids=["nope"], source_review_ids=["fake"]), make_context())
    assert {"UNKNOWN_PRODUCT", "UNKNOWN_REVIEW"} <= {finding.code for finding in report.findings}


def test_word_count_is_a_warning_not_an_error():
    report = validate_master_copy(_copy(body="too short for the target length"), make_context())
    assert not report.has_errors
    assert "WORD_COUNT_OUT_OF_RANGE" in {finding.code for finding in report.findings}


def test_incomplete_product_is_rejected_before_generation():
    product = ProductFacts(id="p1", name="Ball", category="Toys", description="  ")
    with pytest.raises(WorkflowError):
        ensure_context_is_usable(make_context(products=[product]))
    with pytest.raises(WorkflowError):
        ensure_context_is_usable(make_context(products=[]))


class TestMockProvider:
    @pytest.fixture
    def topic(self) -> TopicOutput:
        return TopicOutput(
            title="[MOCK] A topic",
            angle="An angle",
            target_audience="Cat owners",
            hook="Is your cat bored?",
            product_relevance="Relevant",
            content_type="educational_tips",
            rationale="A reason",
        )

    async def test_topics_are_deterministic_and_labeled(self):
        first = await MockLLMProvider().generate_topics(make_context(), count=5)
        second = await MockLLMProvider().generate_topics(make_context(), count=5)
        assert first == second
        assert len(first.topics) == 5
        assert all(topic.title.startswith("[MOCK]") for topic in first.topics)

    async def test_regenerated_topics_are_new(self):
        first = await MockLLMProvider().generate_topics(make_context(), count=5)
        second = await MockLLMProvider().generate_topics(
            make_context(), count=5, previous_titles=[t.title for t in first.topics]
        )
        assert not {t.title for t in first.topics} & {t.title for t in second.topics}

    async def test_draft_is_in_range_and_passes_validation(self, topic):
        draft = await MockLLMProvider().generate_master_copy(make_context(), topic=topic)
        assert 350 <= len(draft.body.split()) <= 1050
        assert not validate_master_copy(draft, make_context()).has_errors

    async def test_revision_keeps_previous_text_and_applies_feedback(self, topic):
        provider = MockLLMProvider()
        draft = await provider.generate_master_copy(make_context(), topic=topic)
        revised = await provider.revise_master_copy(
            make_context(), topic=topic, current=draft, feedback="Be less sales-oriented."
        )
        assert "Be less sales-oriented." in revised.body
        assert draft.body in revised.body

    async def test_does_not_invent_reviews_when_none_exist(self, topic):
        draft = await MockLLMProvider().generate_master_copy(make_context(), topic=topic)
        assert draft.source_review_ids == []
        assert "customer" not in draft.body.lower()

    async def test_uses_only_authorized_reviews(self, topic):
        reviews = [ReviewFacts(id="r1", product_id="p1", rating=5, review_text="We enjoy it every evening at home.")]
        draft = await MockLLMProvider().generate_master_copy(make_context(reviews=reviews), topic=topic)
        assert draft.source_review_ids == ["r1"]
        assert "We enjoy it every evening at home." in draft.body

    @pytest.mark.parametrize("count", [3, 4, 5])
    async def test_carousel_has_requested_slide_count(self, topic, count):
        provider = MockLLMProvider()
        draft = await provider.generate_master_copy(make_context(), topic=topic)
        plan = await provider.plan_carousel(make_context(), master=draft, image_count=count)
        assert len(plan.slides) == count
        assert plan.slides[0].layout_template == "cover"
        assert plan.slides[-1].slide_type == "call_to_action"

    async def test_instagram_and_facebook_differ(self, topic):
        provider = MockLLMProvider()
        draft = await provider.generate_master_copy(make_context(), topic=topic)
        instagram = await provider.adapt_instagram(make_context(), master=draft)
        facebook = await provider.adapt_facebook(make_context(), master=draft)
        assert instagram.caption != facebook.post_text
        assert len(facebook.post_text) > 0 and instagram.hashtags
