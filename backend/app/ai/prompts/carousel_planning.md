<!-- version: 1 -->
## Task
Turn the approved master draft into a visual storytelling plan for a social media carousel.

The data holds the brand, products, `approved_draft`, `image_count` and optionally `validation_feedback`.

## Requirements
- Return exactly `image_count` slides, numbered from 1 in order, forming one coherent story a person can follow while swiping.
- Slide 1 has `slide_type` "cover" and `layout_template` "cover". The last slide has `slide_type` "call_to_action". All other slides use `layout_template` "content".
- Keep text short: `headline` under 60 characters where possible, and `supporting_text` one or two short sentences. Never copy paragraphs onto a slide.
- `product_ids` lists products from the data shown on that slide. Use it on slides that feature a product.
- `image_prompt` describes only a background scene or lifestyle illustration for an image model. Our system adds all text and real product photos afterwards, so the prompt must request: no text, no letters, no logos, no packaging and no identifiable commercial product. Never ask the model to draw the actual product.
- Generated scenes must not look like customer-submitted photos.
- `alt_text` describes the finished slide for screen readers.
- Use only facts from the approved draft and product data.
- If `validation_feedback` is present, fix the listed problems.
