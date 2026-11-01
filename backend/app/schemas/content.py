"""Structured AI inputs and outputs. Provider responses are validated against these models."""

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class BrandFacts(BaseModel):
    brand_name: str
    brand_description: str | None = None
    brand_voice: list[str] = Field(default_factory=list)
    target_audience: str | None = None
    preferred_cta: str | None = None
    prohibited_claims: list[str] = Field(default_factory=list)
    style_guidelines: str | None = None
    logo_path: str | None = None


class ProductFacts(BaseModel):
    id: str
    sku: str | None = None
    name: str
    category: str
    description: str
    key_features: list[str] = Field(default_factory=list)
    materials: list[str] = Field(default_factory=list)
    suitable_pets: list[str] = Field(default_factory=list)
    usage_instructions: str | None = None
    safety_notes: str | None = None
    price: str | None = None
    currency: str | None = None
    product_url: str | None = None
    image_paths: list[str] = Field(default_factory=list)


class ReviewFacts(BaseModel):
    """Only reviews with permission to use and a verified status reach the AI."""

    id: str
    product_id: str
    rating: int
    review_text: str


class GenerationContext(BaseModel):
    """The facts frozen by the load_context node. All generation is grounded in this."""

    brand: BrandFacts
    products: list[ProductFacts]
    reviews: list[ReviewFacts] = Field(default_factory=list)
    target_market: str
    target_audience: str | None = None
    marketing_goal: str | None = None
    operator_instructions: str | None = None
    locale: str = "en-US"
    channels: list[str]
    image_count: int
    target_word_count: int
    recent_topics: list[str] = Field(default_factory=list)


ContentType = Literal[
    "product_showcase",
    "educational_tips",
    "problem_solution",
    "pet_enrichment",
    "lifestyle",
    "seasonal",
    "product_comparison",
]


class TopicOutput(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    angle: str = Field(min_length=3)
    target_audience: str = Field(min_length=3)
    hook: str = Field(min_length=3)
    product_relevance: str = Field(min_length=3)
    content_type: ContentType
    rationale: str = Field(min_length=3)


class TopicBatchOutput(BaseModel):
    topics: list[TopicOutput] = Field(min_length=1, max_length=10)


class MasterCopy(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    opening_hook: str = Field(min_length=3)
    body: str = Field(min_length=20)
    key_takeaways: list[str] = Field(min_length=1, max_length=10)
    featured_product_ids: list[str] = Field(min_length=1)
    call_to_action: str = Field(min_length=3)
    source_review_ids: list[str] = Field(default_factory=list)

    def full_text(self) -> str:
        return "\n".join(
            [self.title, self.opening_hook, self.body, *self.key_takeaways, self.call_to_action]
        )


class InstagramOutput(BaseModel):
    caption: str = Field(min_length=10, max_length=2200)
    hashtags: list[str] = Field(min_length=1, max_length=30)
    call_to_action: str = Field(min_length=3)

    @field_validator("hashtags")
    @classmethod
    def _normalize_hashtags(cls, hashtags: list[str]) -> list[str]:
        normalized: dict[str, str] = {}
        for tag in hashtags:
            cleaned = "".join(ch for ch in tag if ch.isalnum() or ch == "_")
            if cleaned:
                normalized.setdefault(cleaned.lower(), f"#{cleaned}")
        if not normalized:
            raise ValueError("At least one valid hashtag is required.")
        return list(normalized.values())

    def full_text(self) -> str:
        return f"{self.caption}\n{self.call_to_action}"


class FacebookOutput(BaseModel):
    opening_hook: str = Field(min_length=3)
    post_text: str = Field(min_length=20, max_length=10000)
    call_to_action: str = Field(min_length=3)

    def full_text(self) -> str:
        return f"{self.opening_hook}\n{self.post_text}\n{self.call_to_action}"


class CarouselSlide(BaseModel):
    slide_number: int = Field(ge=1, le=5)
    slide_type: Literal["cover", "problem", "education", "product", "call_to_action"]
    headline: str = Field(min_length=1, max_length=90)
    supporting_text: str = Field(default="", max_length=260)
    visual_description: str = Field(min_length=3)
    product_ids: list[str] = Field(default_factory=list)
    layout_template: Literal["cover", "content"]
    image_prompt: str = Field(min_length=3)
    alt_text: str = Field(min_length=3, max_length=500)


class CarouselPlanOutput(BaseModel):
    slides: list[CarouselSlide] = Field(min_length=3, max_length=5)

    @model_validator(mode="after")
    def _slides_are_numbered_in_order(self) -> "CarouselPlanOutput":
        numbers = [slide.slide_number for slide in self.slides]
        if numbers != list(range(1, len(numbers) + 1)):
            raise ValueError("slide_number values must be 1, 2, 3, ... in order.")
        return self

    def full_text(self) -> str:
        return "\n".join(f"{s.headline}\n{s.supporting_text}" for s in self.slides)
