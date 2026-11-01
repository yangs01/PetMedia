"""Deterministic offline providers for development, tests and demos.

Everything they produce is visibly labeled: text starts with "[MOCK]", records
carry provider "mock", and images show a MOCK stamp. Copy is built only from the
supplied product facts, so it also passes the marketing integrity validators.
"""

import asyncio
import hashlib
import io

from PIL import Image, ImageDraw

from app.ai.providers.image_provider import GeneratedImage, ImageProvider
from app.ai.providers.llm_provider import LLMProvider
from app.schemas.content import (
    CarouselPlanOutput,
    CarouselSlide,
    FacebookOutput,
    GenerationContext,
    InstagramOutput,
    MasterCopy,
    TopicBatchOutput,
    TopicOutput,
)

_TOPIC_TEMPLATES = [
    ("Ways to Keep Playtime Fresh with {name}", "educational_tips", "Is playtime getting predictable?"),
    ("A Simple Daily Play Routine Featuring {name}", "lifestyle", "What does a good play routine look like?"),
    ("Enrichment Ideas Built Around {name}", "pet_enrichment", "Looking for easy enrichment ideas?"),
    ("Getting Started with {name}: A Practical Guide", "product_showcase", "New to {name}?"),
    ("When Your Pet Needs a New Activity: Meet {name}", "problem_solution", "Does your pet need something new to do?"),
    ("Cozy Season Indoor Play with {name}", "seasonal", "Staying in this season?"),
    ("Small Changes for Better Play Sessions with {name}", "educational_tips", "Could one small change help?"),
]

_BODY_PARAGRAPHS = [
    "Good routines start with noticing what your pet enjoys. Some pets love a short burst of activity, "
    "while others prefer to explore slowly and come back later. Spending a few minutes watching how your "
    "pet approaches a new object tells you far more than any general rule. Follow their lead, keep things "
    "relaxed, and treat each session as a chance to learn a little more about what holds their attention.",
    "Short and regular usually works better than long and occasional. A few minutes at a consistent time "
    "of day gives your pet something to look forward to and makes the activity easy for you to keep up. "
    "If attention drifts, stop while the mood is still good and try again later. There is no need to turn "
    "playtime into a chore for either of you, and a calm ending makes the next session easier to start.",
    "Variety keeps things interesting. Moving an item to a different room, changing the time of day, or "
    "putting it away for a while and bringing it back can make something familiar feel new again. These "
    "small adjustments cost nothing and take only moments. Keep a simple note of what got the best "
    "response, and you will soon have a short list of favorites that suit your own pet and your own home.",
    "Your involvement matters as much as the item itself. Sitting nearby, speaking gently, and joining in "
    "for a minute or two turns a solo activity into shared time. Many pet owners find this is the part of "
    "the day they enjoy most. It also gives you a natural moment to check that everything is still in good "
    "condition, and to put items away when the session is over so they stay special.",
    "Finally, keep safety simple and sensible. Follow the instructions that come with any product, stay "
    "nearby during play when the product calls for supervision, and retire anything that shows wear. Every "
    "pet is different, so if you ever have a question about what suits your pet's age or health, your "
    "veterinarian is the right person to ask. A little attention here keeps playtime relaxed for everyone.",
]


class MockLLMProvider(LLMProvider):
    name = "mock"

    def __init__(self, *, delay_seconds: float = 0) -> None:
        self._delay_seconds = delay_seconds

    async def _pause(self) -> None:
        if self._delay_seconds:
            await asyncio.sleep(self._delay_seconds)

    async def generate_topics(self, context, *, count, feedback=None, previous_titles=None):
        await self._pause()
        product = context.products[0]
        previous = set(previous_titles or [])
        audience = context.target_audience or context.brand.target_audience or "Pet owners"
        topics: list[TopicOutput] = []
        round_number = 0
        while len(topics) < count:
            for template, content_type, hook in _TOPIC_TEMPLATES:
                suffix = f" (Idea Set {round_number + 1})" if round_number else ""
                title = f"[MOCK] {template.format(name=product.name)}{suffix}"
                if title in previous or len(topics) == count:
                    continue
                topics.append(
                    TopicOutput(
                        title=title,
                        angle=f"Practical, friendly guidance for owners considering {product.name}.",
                        target_audience=audience,
                        hook=hook.format(name=product.name),
                        product_relevance=f"{product.name}: {product.description}",
                        content_type=content_type,
                        rationale=(
                            f"Connects an everyday concern to {product.category}."
                            + (f" Operator direction: {feedback}" if feedback else "")
                        ),
                    )
                )
            round_number += 1
        return TopicBatchOutput(topics=topics)

    async def generate_master_copy(self, context, *, topic):
        await self._pause()
        return self._draft(context, topic, ["[MOCK] This draft was produced by the offline mock provider."])

    async def revise_master_copy(self, context, *, topic, current, feedback):
        await self._pause()
        note = (
            "[MOCK] Revised by the offline mock provider. "
            f"Editorial feedback received: {feedback.strip()}"
        )
        return current.model_copy(
            update={"body": f"{note}\n\n{current.body}", "opening_hook": f"{topic.hook} Here is what helps."}
        )

    def _draft(self, context: GenerationContext, topic: TopicOutput, intro: list[str]) -> MasterCopy:
        word_goal = context.target_word_count
        product = context.products[0]
        features = "; ".join(product.key_features) or product.description
        product_paragraph = (
            f"This is where {product.name} can fit in. {product.description} "
            f"Key features: {features}."
            + (f" How to use it: {product.usage_instructions}" if product.usage_instructions else "")
            + (f" Safety note: {product.safety_notes}" if product.safety_notes else "")
        )
        paragraphs = [*intro, topic.hook, _BODY_PARAGRAPHS[0], product_paragraph, *_BODY_PARAGRAPHS[1:]]
        source_review_ids: list[str] = []
        if context.reviews:
            review = context.reviews[0]
            source_review_ids.append(review.id)
            paragraphs.append(f'One verified customer shared: "{review.review_text}"')
        body = "\n\n".join(paragraphs)
        # Trim on a word boundary for short targets; never pad with filler.
        words = body.split(" ")
        if len(words) > word_goal * 1.4:
            body = " ".join(words[: int(word_goal * 1.4)])
        return MasterCopy(
            title=topic.title,
            opening_hook=topic.hook,
            body=body,
            key_takeaways=[
                "Follow your pet's lead and keep sessions short.",
                "Rotate activities to keep them interesting.",
                f"{product.name}: {product.key_features[0] if product.key_features else product.category}.",
            ],
            featured_product_ids=[p.id for p in context.products],
            call_to_action=context.brand.preferred_cta or f"Take a closer look at {product.name}.",
            source_review_ids=source_review_ids,
        )

    async def adapt_instagram(self, context, *, master, feedback=None):
        await self._pause()
        takeaways = "\n".join(f"- {item}" for item in master.key_takeaways)
        return InstagramOutput(
            caption=f"[MOCK] {master.opening_hook}\n\nA few simple ideas worth trying:\n{takeaways}",
            hashtags=["PetCare", "PetEnrichment", "HappyPets", "PetLife", context.products[0].category.replace(" ", "")],
            call_to_action=master.call_to_action,
        )

    async def adapt_facebook(self, context, *, master, feedback=None):
        await self._pause()
        product = context.products[0]
        return FacebookOutput(
            opening_hook=f"[MOCK] {master.opening_hook}",
            post_text=(
                f"[MOCK] {master.opening_hook}\n\n"
                "Small routines make a big difference to everyday life with a pet. Keep sessions short, "
                "follow your pet's lead, and change things up now and then.\n\n"
                f"{product.name} is one option to consider. {product.description}\n\n"
                f"{master.call_to_action}"
            ),
            call_to_action=master.call_to_action,
        )

    async def plan_carousel(self, context, *, master, image_count, feedback=None):
        await self._pause()
        product = context.products[0]
        takeaways = master.key_takeaways or [master.opening_hook]
        slides = [
            CarouselSlide(
                slide_number=1,
                slide_type="cover",
                headline=master.opening_hook[:90],
                supporting_text="[MOCK] Swipe for simple ideas.",
                visual_description="A cozy home scene with soft natural light.",
                layout_template="cover",
                image_prompt="Cozy living room in soft natural light, warm colors, no text, no logos, no products.",
                alt_text=f"Cover slide with the headline: {master.opening_hook[:200]}",
            )
        ]
        for number in range(2, image_count):
            is_product = number == image_count - 1
            text = (
                product.description if is_product else takeaways[(number - 2) % len(takeaways)]
            )[:250]
            slides.append(
                CarouselSlide(
                    slide_number=number,
                    slide_type="product" if is_product else "education",
                    headline=product.name[:90] if is_product else f"Idea {number - 1}",
                    supporting_text=text,
                    visual_description="A calm abstract background in brand colors.",
                    product_ids=[product.id] if is_product else [],
                    layout_template="content",
                    image_prompt=f"Calm abstract pet-themed background variation {number}, no text, no logos, no products.",
                    alt_text=f"Slide {number}: {text[:200]}",
                )
            )
        slides.append(
            CarouselSlide(
                slide_number=image_count,
                slide_type="call_to_action",
                headline=master.call_to_action[:90],
                supporting_text=context.brand.brand_name,
                visual_description="A cheerful, simple background with room for text.",
                product_ids=[product.id],
                layout_template="content",
                image_prompt="Cheerful simple background with soft shapes, no text, no logos, no products.",
                alt_text=f"Call to action: {master.call_to_action[:200]}",
            )
        )
        return CarouselPlanOutput(slides=slides)


class MockImageProvider(ImageProvider):
    """Paints a gradient derived from the prompt hash: same prompt, same image."""

    name = "mock"

    async def generate_background(self, prompt: str, *, width: int, height: int) -> GeneratedImage:
        data = await asyncio.to_thread(_paint_gradient, prompt, width, height)
        return GeneratedImage(data=data, provider=self.name, is_mock=True)


def _paint_gradient(prompt: str, width: int, height: int) -> bytes:
    digest = hashlib.sha256(prompt.encode("utf-8")).digest()
    top, bottom = digest[:3], digest[3:6]
    # Painting a small image and scaling it up is fast and gives a smooth gradient.
    small = Image.new("RGB", (4, 32))
    for y in range(32):
        ratio = y / 31
        color = tuple(int(a + (b - a) * ratio) for a, b in zip(top, bottom, strict=True))
        for x in range(4):
            small.putpixel((x, y), color)
    image = small.resize((width, height), Image.Resampling.BICUBIC)
    ImageDraw.Draw(image).text((24, 24), "MOCK", fill=(255, 255, 255), font_size=36)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()
