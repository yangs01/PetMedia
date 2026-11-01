# Revision Progress

Details and baseline results are in [revision-plan.md](revision-plan.md).

| Phase | Scope | Status |
|---|---|---|
| 0 | Repository cleanup and baseline | Done, not pushed |
| 1 | Per-role LLM model selection | Not started |
| 2 | Native Anthropic and compatible DeepSeek integration | Not started |
| 3 | Model configuration snapshots and observability | Not started |
| 4 | Editable carousel slide content | Not started |
| 5 | Real provider smoke tests | Not started |
| 6 | CI/CD and documentation hardening | Not started |

## Phase 0 (2026-11-01)

- Created `improvement/backend-hardening` from `e9a6e29`.
- Removed the merge conflict markers and placeholder text from `README.md`. Its content now matches the pre-merge commit `0144c19`. No other tracked file has conflict markers.
- Recorded the baseline: 248 of 248 tests pass, while `ruff check` and `ruff format --check` fail.
- Reviewed tracked files and history. No `.env`, credentials, generated images or database dumps are tracked. The only key-like match is a fake test constant in `backend/tests/unit/test_real_providers.py`.
- Application code, tests and databases outside the temporary test server were not changed.
