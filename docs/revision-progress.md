# Revision Progress

Details and baseline results are in [revision-plan.md](revision-plan.md).

| Phase | Scope | Status |
|---|---|---|
| 0 | Repository cleanup and baseline | Done |
| 1 | Per-role LLM model selection | Done in code and simulated tests, not run against live APIs |
| 2 | Native Anthropic and compatible DeepSeek integration | Delivered with phase 1. Live verification belongs to phase 5 |
| 3 | Model configuration snapshots and observability | Not started |
| 4 | Editable carousel slide content | Not started |
| 5 | Real provider smoke tests | Not started |
| 6 | CI/CD and documentation hardening | Not started |
| Added | Browser frontend in `frontend/` | Done, tested with mock providers only |

## Phase 0 (2026-11-01)

- Created `improvement/backend-hardening` from `e9a6e29`.
- Removed the merge conflict markers and placeholder text from `README.md`. Its content now matches the pre-merge commit `0144c19`. No other tracked file has conflict markers.
- Recorded the baseline: 248 of 248 tests pass, while `ruff check` and `ruff format --check` fail.
- Reviewed tracked files and history. No `.env`, credentials, generated images or database dumps are tracked. The only key-like match is a fake test constant in `backend/tests/unit/test_real_providers.py`.
- Application code, tests and databases outside the temporary test server were not changed.

## Phase 1 (2026-11-01)

- Added typed model profiles, `ModelRegistry` and `ModelRouter`, configured through `LLM_PROFILES_PATH`. See [model-configuration.md](model-configuration.md).
- Added OpenAI, native Anthropic (official SDK, API version `2026-10-21`) and DeepSeek providers. Without a profiles file, the `LLM_*` settings serve every role as before.
- Changed `generate_topics`, `generate_copy`, `adapt_channels` and `plan_carousel` to ask for a role. `content_graph.py`, graph state, migrations and approval APIs were not changed.
- Added runtime dependencies `anthropic`, `pyyaml` and `python-dotenv`, and development dependency `httpx2`.
- Results, on a temporary PostgreSQL 17.11 test server on port 5433: 338 of 338 tests pass (215 unit, 120 integration, 3 end-to-end), on two consecutive full runs. `ruff check` still reports the same 15 baseline findings, none in new code. `ruff format --check` still fails.

Not verified:

- No request has been sent to a live OpenAI, Anthropic or DeepSeek API.
- The test role on the temporary server is a superuser.

Behavior changes to the original provider:

- Blank model output is now retried within the structured-output limit. It used to fail at once.
- Output cut off at the token limit now fails with a clear message and no retry.
- A model refusal now has its own error code, `PROVIDER_REFUSAL`.
