<!-- version: 1 -->
## Task
Suggest content topics for Instagram and Facebook that connect real pet-owner concerns to the given products.

The data holds the brand, products, target market, audience, marketing goal, `topic_count`, `recent_topics`, and optionally `previous_titles` and `operator_feedback`.

## Requirements
- Return exactly `topic_count` topics, each clearly different in angle.
- Do not repeat `recent_topics` or `previous_titles`.
- If `operator_feedback` is present, follow its direction.
- `hook` is a short opening line that would stop someone scrolling.
- `product_relevance` explains factually how the product fits. Use only product facts from the data.
- `rationale` explains in one or two sentences why this topic suits the audience and goal.
- `content_type` is one of: product_showcase, educational_tips, problem_solution, pet_enrichment, lifestyle, seasonal, product_comparison. Use product_comparison only when the data supports the comparison.
