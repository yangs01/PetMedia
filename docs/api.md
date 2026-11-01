# API

Base path: `/api/v1`. Interactive documentation with all schemas is at `/docs` when the API is running.

If `API_KEY` is set, every request needs the header `X-API-Key: <value>`.

## Task lifecycle

Generation happens in the worker, so write requests return quickly and clients poll.

1. `POST /tasks` returns 202 and a `task_id`.
2. Poll `GET /tasks/{id}` until `status` is an `AWAITING_*` value and `decision_in_progress` is false.
3. Show the review and submit a decision. It returns 202.
4. Repeat until `status` is `READY`, then download an export.

`available_actions` and `review_stage` on the task say what is currently allowed, so a frontend does not need to duplicate these rules.

## Errors

Every error has the same shape:

```json
{
  "error": {
    "code": "INVALID_TASK_STATE",
    "message": "The task is not awaiting copy approval.",
    "details": { "current_status": "GENERATING_ASSETS" }
  }
}
```

| Status | Meaning | Example codes |
|---|---|---|
| 401 | Missing or wrong API key | `UNAUTHORIZED` |
| 404 | Not found | `NOT_FOUND` |
| 409 | Conflict with current state; reload and retry | `INVALID_TASK_STATE`, `STALE_REVIEW`, `DUPLICATE_DECISION`, `CONCURRENT_UPDATE`, `EXPORT_NOT_READY`, `DUPLICATE_SKU`, `DUPLICATE_BRAND` |
| 422 | Invalid input | `VALIDATION_ERROR`, `INVALID_IMAGE`, `UNSUPPORTED_IMAGE_TYPE`, `UPLOAD_TOO_LARGE`, `IMAGE_TOO_LARGE` |
| 500 | Server problem, details in logs | `INTERNAL_ERROR`, `MEDIA_FILE_MISSING` |

## Health

| Endpoint | Purpose |
|---|---|
| `GET /health` | Process is alive |
| `GET /health/ready` | 200 if database, migrations, checkpoints and storage are all fine; otherwise 503 with `checks` naming the problem |

## Products

| Endpoint | Purpose |
|---|---|
| `POST /products` | Create |
| `GET /products?limit&offset&include_archived` | List |
| `GET /products/{id}` | Read |
| `PATCH /products/{id}` | Update the fields sent |
| `DELETE /products/{id}` | Archive; existing tasks keep their history |
| `POST /products/{id}/images` | Upload a JPEG, PNG or WebP as multipart field `file` |
| `GET /products/{id}/images` | List images |

```json
POST /products
{
  "name": "Interactive Cat Ball Toy",
  "category": "Cat Toys",
  "description": "An interactive toy designed to encourage playtime and exploration.",
  "key_features": ["Lightweight design", "Rolling ball mechanism"],
  "materials": [],
  "suitable_pets": ["Cats"],
  "price": "19.99",
  "currency": "USD"
}
```

The AI may only state facts found in these fields, so fill in what you want it to be able to say.

## Brands

| Endpoint | Purpose |
|---|---|
| `POST /brands` | Create |
| `GET /brands` | List |
| `GET /brands/{id}` | Read |
| `PATCH /brands/{id}` | Update the fields sent |
| `POST /brands/{id}/logo` | Upload an optional logo, shown on slides |

```json
POST /brands
{
  "brand_name": "Paws & Play",
  "brand_voice": ["Friendly", "Trustworthy", "Playful"],
  "target_markets": ["US"],
  "preferred_cta": "Explore the collection.",
  "prohibited_claims": ["best in the world"],
  "style_guidelines": "Warm colors, simple compositions."
}
```

## Customer reviews

| Endpoint | Purpose |
|---|---|
| `POST /products/{id}/reviews` | Store a review |
| `GET /products/{id}/reviews` | List reviews |

```json
POST /products/{id}/reviews
{
  "rating": 5,
  "review_text": "We enjoy this toy every evening at home.",
  "source": "order_review",
  "source_reference": "ORDER-1001",
  "permission_to_use": true,
  "verified_status": "VERIFIED"
}
```

Only reviews with `permission_to_use: true` **and** `verified_status: "VERIFIED"` are shown to the AI. Reviews are picked up when a task starts.

## Tasks

| Endpoint | Purpose |
|---|---|
| `POST /tasks` | Create and queue (202) |
| `GET /tasks?status&limit&offset` | List |
| `GET /tasks/{id}` | Full details |
| `GET /tasks/{id}/events?after_id&limit` | Event log, with `after_id` as a polling cursor |
| `GET /tasks/{id}/topics` | All topic batches |
| `GET /tasks/{id}/versions` | All draft versions |
| `GET /tasks/{id}/assets?include_history` | Current images, or all versions |
| `GET /tasks/{id}/channels` | Platform content |
| `POST /tasks/{id}/retry` | Continue a `FAILED` task from its checkpoint (202) |
| `POST /tasks/{id}/cancel` | Cancel a `QUEUED` or `FAILED` task |

```json
POST /tasks
{
  "brand_id": "<uuid>",
  "product_ids": ["<uuid>"],
  "target_market": "US",
  "target_audience": "First-time cat owners",
  "marketing_goal": "Brand awareness",
  "operator_instructions": "Focus on indoor cats.",
  "channels": ["instagram", "facebook"],
  "image_count": 4,
  "target_word_count": 700
}
```

Only `brand_id` and `product_ids` are required.

```json
202 Accepted
{ "task_id": "<uuid>", "thread_id": "content-task-<uuid>", "status": "QUEUED" }
```

Abridged `GET /tasks/{id}` response:

```json
{
  "id": "<uuid>",
  "status": "AWAITING_COPY_REVIEW",
  "version": 6,
  "review_stage": "COPY",
  "review_key": "copy:<version uuid>",
  "available_actions": ["approve", "revise", "edit_and_approve", "cancel"],
  "decision_in_progress": false,
  "selected_topic": { "id": "<uuid>", "title": "..." },
  "current_version": {
    "id": "<uuid>",
    "version_number": 2,
    "generation_source": "AI_REVISION",
    "content": { "title": "...", "opening_hook": "...", "body": "...", "key_takeaways": [], "featured_product_ids": [], "call_to_action": "...", "source_review_ids": [] },
    "validation": { "passed": true, "findings": [] }
  },
  "approved_version_id": null,
  "carousel_plan": null,
  "assets": [],
  "channel_contents": [],
  "error": null
}
```

Check `current_version.validation` before approving. It lists any unsupported claims the checks found.

## Review decisions

Each returns 202 with the new status and a `decision_id`, or 409 if the task is not at that stage.

### `POST /tasks/{id}/topic-decision`

| Action | Required fields |
|---|---|
| `select` | `selected_topic_id`, from the latest batch |
| `regenerate` | Optional `feedback` |
| `cancel` | None |

```json
{ "action": "select", "selected_topic_id": "<uuid>", "feedback": null }
```

### `POST /tasks/{id}/copy-decision`

`current_version_id` is always required. A version that is no longer current gives `409 STALE_REVIEW`.

| Action | Required fields |
|---|---|
| `approve` | None beyond the above |
| `revise` | `feedback` |
| `edit_and_approve` | `edited_content`, with all draft fields |
| `cancel` | None beyond the above |

```json
{
  "action": "revise",
  "current_version_id": "<uuid>",
  "feedback": "Make the article more natural and less promotional."
}
```

### `POST /tasks/{id}/image-decision`

| Action | Required fields |
|---|---|
| `approve` | None |
| `regenerate` | `slide_numbers`; optional `feedback` |
| `cancel` | None |

```json
{ "action": "regenerate", "slide_numbers": [2, 3], "feedback": "Use a cleaner design." }
```

Optionally send `review_key` from the task details. If the images changed since you loaded them, you get `409 STALE_REVIEW` instead of approving images you have not seen.

## Assets and exports

| Endpoint | Purpose |
|---|---|
| `GET /assets/{id}` | Download a generated or product image |
| `GET /tasks/{id}/exports` | List exports and whether they are available |
| `GET /tasks/{id}/exports/instagram` | Instagram ZIP |
| `GET /tasks/{id}/exports/facebook` | Facebook ZIP |
| `GET /tasks/{id}/exports/all` | Combined ZIP |

Downloads return `409 EXPORT_NOT_READY` until the task is `READY`. Contents of the combined ZIP:

```text
instagram/caption.txt
instagram/hashtags.txt
instagram/alt_text.json
instagram/slide_01.jpg ...
facebook/post.txt
facebook/images/image_01.jpg ...
metadata.json
README.md
```

`metadata.json` records the approved version, the providers and prompt versions used, and a SHA-256 hash per image. `contains_mock_content: true` means the package must not be published.
