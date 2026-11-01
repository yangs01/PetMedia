# Model configuration

Each text generation task in the workflow is a **role**, and each role can use its own provider, model, credential and settings. Image generation is configured separately with the `IMAGE_*` settings.

Configuration is optional. Without it, the `LLM_*` settings serve every role, exactly as they did before profiles existed.

## Setting up profiles

1. Copy the example from the project root:

   ```bash
   Copy-Item config\models.example.yaml config\models.yaml
   ```

2. Edit `config/models.yaml`.
3. In `.env`, add your keys, any `${NAME}` values the file uses, and the path:

   ```dotenv
   LLM_PROFILES_PATH=config/models.yaml
   DEEPSEEK_API_KEY=your-key
   ANTHROPIC_API_KEY=your-key
   OPENAI_API_KEY=your-key
   DEEPSEEK_MODEL=a-current-deepseek-model
   CLAUDE_MODEL=claude-opus-5-5
   OPENAI_MODEL=a-current-openai-model
   ```

4. Restart the worker. Its "Worker started" log line lists the profile for each role.

The worker checks every profile a role can reach when it starts. If a key, a model or a setting is wrong, it stops and says which profile and which variable. It never falls back to mock. When `LLM_PROFILES_PATH` is set, `LLM_PROVIDER` and the other `LLM_*` settings are ignored.

## Roles

| Role | Used for |
|---|---|
| `topic_generation` | Topic batches |
| `copy_generation` | The first draft |
| `copy_revision` | Revisions the operator asks for and automatic validation fixes |
| `instagram_adaptation` | The Instagram caption |
| `facebook_adaptation` | The Facebook post |
| `carousel_planning` | The slide plan |

Map every role under `roles`, or set `default_profile` to cover the ones you leave out. A file that does neither is rejected, so a forgotten role cannot quietly use something unintended.

## Profile fields

| Field | Meaning | Default |
|---|---|---|
| `provider` | `openai`, `anthropic`, `deepseek`, `openai_compatible` or `mock` | Required |
| `model` | Model identifier. Can be `${NAME}` | Required, except for `mock` |
| `credential_env` | **Name** of the environment variable that holds the key | Required, except for `mock` |
| `base_url` | API address. Can contain `${NAME}` | See the provider table |
| `temperature` | 0 to 2, where the provider accepts it | Not sent |
| `max_tokens` | Output limit | `anthropic`: 16000. Others: not sent |
| `timeout_seconds` | Request timeout | 120 |
| `structured_mode` | `json_schema` or `json_object` | See the provider table |
| `max_structured_retries` | Calls allowed for one result when the output fails validation, 1 to 10 | 3 |
| `effort` | `low`, `medium`, `high`, `xhigh` or `max` (`anthropic` only) | Not sent |
| `fallback_profile` | Another profile to try when this one fails | None |

Keys never go in this file. An unknown field such as `api_key` is rejected, and the error does not repeat the value.

## What each provider accepts

| | `openai` | `anthropic` | `deepseek` | `openai_compatible` | `mock` |
|---|---|---|---|---|---|
| API | Chat Completions | Native Messages API, official SDK | Chat Completions | Chat Completions | None |
| Default `base_url` | `https://api.openai.com/v1` | `https://api.anthropic.com` | `https://api.deepseek.com` | Required | None |
| `structured_mode` | `json_schema` (default, strict), `json_object` | Always `json_schema`, through `output_config.format` | `json_object` only | `json_object` (default), `json_schema` | None |
| `temperature` | Yes | **No** | Yes | Yes | No |
| `max_tokens` | Yes, sent as `max_completion_tokens` | Yes | Yes | Yes | No |
| `effort` | No | Yes | No | No | No |

An unsupported combination stops the worker with a clear message. Plain `http://` is refused for `openai`, `anthropic` and `deepseek`, except on the local machine.

**Anthropic.** The SDK uses API version `2026-10-21`, which rejects `temperature`, `top_p` and `top_k` on every model, so no replacement setting exists. Use `effort` to trade quality against cost. On `claude-opus-5-5`, the default effort is `medium`.

**OpenAI.** Not every model accepts every parameter, so `temperature` is sent only if you set it. Strict mode requires every field and does not document length limits, so `strict_json_schema` removes them from the request. Pydantic still enforces them on the response.

**DeepSeek.** The official documentation lists `deepseek-flash` and `deepseek-v4-pro` at the time of writing. Check it before choosing a model. Answers made up only of spaces are treated as invalid output and retried within `max_structured_retries`. Set `max_tokens` high enough for the longest draft, because the API's default output limit is low and truncated JSON cannot be used.

## Example: a different provider per role

```yaml
profiles:
  deepseek_topics:
    provider: deepseek
    model: ${DEEPSEEK_MODEL}
    credential_env: DEEPSEEK_API_KEY
    max_tokens: 4000
  claude_copy:
    provider: anthropic
    model: ${CLAUDE_MODEL}
    credential_env: ANTHROPIC_API_KEY
    effort: high
    timeout_seconds: 300
  openai_social:
    provider: openai
    model: ${OPENAI_MODEL}
    credential_env: OPENAI_API_KEY
roles:
  topic_generation: deepseek_topics
  copy_generation: claude_copy
  copy_revision: claude_copy
  instagram_adaptation: openai_social
  facebook_adaptation: deepseek_topics
  carousel_planning: openai_social
```

Roles that share a profile share one HTTP client. To use two keys with the same vendor, define two profiles with different `credential_env` values.

## Fallback profiles

`fallback_profile` names a profile to try if this one times out, is rate limited or overloaded, keeps returning invalid output, or declines the request.

- It is not used for a rejected request or a bad key. Another model should not hide a configuration problem.
- It goes one level only, and the target cannot have a fallback of its own.
- Neither side can be `mock`.
- Each use logs a warning, and the record stores the provider that actually answered.

Anthropic's server-side `fallbacks` option is deliberately not sent. It would change the model inside a single call, where neither this configuration nor the stored records would show it. Use `fallback_profile` to choose a fallback for Claude.

## Retries

| Level | Applies to | Limit |
|---|---|---|
| Structured output | Invalid or blank output, with the error sent back to the model | The profile's `max_structured_retries` |
| Node | Timeouts, rate limits, server errors | `MAX_GENERATION_RETRIES`, for all providers |

The Anthropic SDK's own retries are turned off, so API calls are not multiplied. Hitting the token limit is not retried, because the same limit would stop the same response at the same place. Raise `max_tokens` instead.

## What changing configuration affects

Routing is read when the worker starts and is not stored in checkpoints. A paused task continues with the worker's current configuration, including steps that have not run yet. Finished steps are not redone.

## Not yet verified against live services

All provider tests use simulated HTTP servers. The request formats follow each vendor's official documentation, but none has been sent to a live API. Run one low-cost task with each provider before relying on it.
