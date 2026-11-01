# Revision Plan

A controlled series of improvements to the existing backend. The architecture stays as it is: a FastAPI and LangGraph modular monolith with an independent worker and PostgreSQL. Nothing here is a rewrite.

## Baseline

| Item | Value |
|---|---|
| Repository | `https://github.com/yangs01/PetMedia` |
| Baseline commit | `e9a6e2943a47358585dd5dc1ef7b722725fd20b2` (`main`, same as `origin/main` when recorded) |
| Revision branch | `improvement/backend-hardening` |
| Recorded | 2026-11-01 |

### Environment

| Tool | Version |
|---|---|
| Windows | 10 Pro for Workstations 10.0.19045 |
| uv | 0.13.6 |
| Python, as pinned by the project | 3.13.15 |
| Ruff | 0.17.3 |
| PostgreSQL | 17.11, a temporary local server on `127.0.0.1:5432` |

The tests used only the `petmedia_test` database on that temporary server. No production or user database was touched. Its `petmedia` role is a superuser, so this run does not show the suite passing with fewer privileges. An earlier 243-test run did pass as a non-superuser database owner.

### Results

Run from `backend`.

| Command | Result |
|---|---|
| `uv sync` | Passed; `uv.lock` unchanged |
| `uv run python --version` | Python 3.13.15 |
| `uv run ruff check .` | **Failed: 15 findings** |
| `uv run ruff format --check .` | **Failed: 68 of 128 files would be reformatted** |
| `uv run pytest tests/unit` | 129 passed |
| `uv run pytest -m "integration and not e2e"` | 116 passed |
| `uv run pytest -m e2e` | 3 passed |
| `uv run pytest` | 248 passed, none failed or skipped, in 82 seconds |

Ruff findings by rule:

| Rule | Count | Where |
|---|---:|---|
| `ISC004` implicit string concatenation in a collection | 5 | `mock_provider.py` |
| `RUF100` unused `noqa` | 3 | Tests |
| `C408` unnecessary `dict()` call | 2 | Tests |
| `BLE001` blind `except` | 1 | `job_runner.py`, deliberate |
| `B008` function call in argument default | 1 | `tasks.py`, FastAPI's `Query` idiom |
| `I001` unsorted imports | 1 | Initial migration |
| `RUF012` mutable class default | 1 | Tests |
| `SIM117` nested `with` | 1 | Tests |

### Not verified at baseline

- **Real providers against a live vendor API.** They have only been tested against a simulated HTTP server.
- **`infra/docker-compose.yml`.** It has never been run, and the Docker daemon was not running for this baseline.
- **Linux and macOS.** All verification has been on Windows.

## Baseline defects

| # | Defect | Status |
|---|---|---|
| 1 | `README.md` contained committed merge conflict markers and placeholder text | Fixed in Phase 0 locally. Still present on `origin/main` until this branch is merged |
| 2 | `ruff check` fails. `pyproject.toml` selects no rules, so results depend on the installed Ruff version's defaults | Open, phase 6 |
| 3 | `ruff format --check` fails on 68 files, so formatting cannot yet be enforced in CI | Open, phase 6 |
| 4 | `.gitignore` does not cover `storage/brands/`, where uploaded logos are stored | Open, phase 6 |
| 5 | `.gitignore` does not cover database dumps (`*.sql`, `*.dump`) or private keys (`*.pem`) | Open, phase 6 |
| 6 | There is no CI | Open, phase 6 |
| 7 | One LLM provider and model serve every workflow step | Open, phase 1 |
| 8 | Text records store only `openai_compatible` as the provider, not the model. Image records store provider and model. Tokens and latency are not stored | Open, phase 3 |
| 9 | Slide text cannot be edited. Image feedback only changes the background art | Open, phase 4 |
| 10 | Image downloads follow redirects without re-checking for HTTPS, and the size limit is applied only after the whole file is in memory. Found by reading the code, not by a failing test | Open, phase 5 |

## Planned improvements

The order below is proposed and can change. Each phase ends with its own tests and a progress entry.

### 1. Per-role LLM model selection

Choose provider and model separately for each role, such as topics, copy, channel adaptation and carousel planning. Today's single `LLM_*` settings must keep working as the default. The likely starting points are `app/core/config.py`, the factories in `app/ai/providers/__init__.py` and `LLMProvider` in `app/ai/runtime.py`.

### 2. Native Anthropic and compatible DeepSeek integration

Add an Anthropic provider that uses its native API, and support DeepSeek through the OpenAI-compatible path. A missing key or model must still stop the worker at startup, and nothing may silently fall back to mock.

### 3. Model configuration snapshots and observability

Freeze each task's model configuration when it starts, as `context_snapshot` already does for product facts, so that a retry or a restart cannot change models midway. Record the model on generated records and in export metadata, and add token and latency data. Snapshots must never contain API keys.

### 4. Editable carousel slide content

Let the operator edit slide headlines and supporting text during image review, then re-render only the affected slides. Edits must keep version history and pass the existing validators. This changes the `README.md` limitation about image feedback.

### 5. Real provider smoke tests

Add low-cost tests against live vendor APIs that are opt-in and skipped by default, so the normal suite never makes a paid call. Use this phase to settle defect 10.

### 6. CI/CD and documentation hardening

Add CI that runs Ruff and the test suite against PostgreSQL. Agree on Ruff rules and apply formatting in a separate commit, so it does not hide functional changes. Close the `.gitignore` gaps, verify Docker Compose, and bring the docs up to date.

## Constraints for every phase

- Keep the existing architecture and working components.
- Never load secrets into logs, snapshots, exports or commits.
- Run tests only against a dedicated test database, because they erase it.
- Report only the results of tests that were actually run.
- Push to GitHub only with explicit authorization.
