# PetMedia AI frontend

A Vue 3 dashboard for operating the content workflow and watching it run. It uses the backend's REST API and adds no backend behavior.

## Requirements

- [Node.js](https://nodejs.org/) 20.19 or newer, which includes npm
- The backend API and worker running. See the [main README](../README.md)

## Install

From the project root, in PowerShell:

```bash
cd frontend
```

```bash
Copy-Item .env.example .env
```

```bash
npm install
```

`VITE_API_BASE_URL` in `.env` sets the API address. The default is `http://127.0.0.1:8000`.

## Start

You need three terminals. In the first two, from the `backend` folder, start the backend:

```bash
uv run python -m app.serve
```

```bash
uv run python -m app.workers.main
```

In the third, from the `frontend` folder:

```bash
npm run dev
```

Open <http://127.0.0.1:3000>.

The dev server uses port 3000 because the backend already allows that origin. If you serve the frontend from another address, add it to `CORS_ORIGINS` in the project's `.env` and restart the API.

## Other commands

Check the production build:

```bash
npm run build
```

Test the logic that works out each node's state:

```bash
npm test
```

## How the workflow diagram gets its data

The page polls the task and its events about every 2 seconds, and stops when the task is `READY` or `CANCELLED`. Nothing is simulated in the browser.

Task statuses are coarser than graph nodes, so `src/workflow/state.js` locates the active node from saved records:

| Status | How the active node is found |
|---|---|
| `GENERATING_TOPICS` | Always shown as Generate Topics. Load Context runs within this status too, too briefly and with no record the API exposes |
| `GENERATING_COPY` | Generate Copy until a new draft is saved, then Validate Copy |
| `GENERATING_ASSETS` | Adapt Channels until every channel is saved, then Plan Carousel until a plan exists, then Generate Images |
| `FAILED`, `CANCELLED`, retried `QUEUED` | The same logic, applied to the status before it, from the event log |

Provider details come from saved records:

- **Model names** appear only for images, because the backend does not store the model for text steps yet.
- **Carousel plans** show no provider, because the API does not return it.

## Layout

| Folder | Holds |
|---|---|
| `src/api` | The API client |
| `src/composables` | Polling and task monitoring |
| `src/workflow` | The graph definition and node state logic |
| `src/components` | Workflow, review, results, catalog and shared components |
| `src/views` | One component per page |
