# Butler MVP

A local chat-first multi-model orchestrator integrated into the CLI Proxy API Management Center repository.

## Included in this first version

- Project creation and project-scoped chat history
- SQLite persistence
- Dynamic model discovery through CLI Proxy API `/v1/models`
- `fast` mode using one selected model
- `verified` mode using independent primary and reviewer calls, followed by judge synthesis
- A minimal browser UI served by FastAPI
- Separation between normal Gateway API access and future privileged coding-agent execution

## Quick start

```bash
cd butler
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
```

Export the variables from `.env`, or set them in your shell, then run:

```bash
python -m app.main
```

Open:

```text
http://127.0.0.1:8318
```

## Required Gateway configuration

```env
BUTLER_GATEWAY_BASE_URL=http://127.0.0.1:8317
BUTLER_GATEWAY_API_KEY=your-cli-proxy-api-key
```

Optional explicit routing:

```env
BUTLER_PRIMARY_MODEL=
BUTLER_REVIEW_MODEL=
BUTLER_JUDGE_MODEL=
```

When these are blank, Butler reads the current model list and selects models heuristically.

## API endpoints

- `GET /api/health`
- `GET /api/models`
- `GET /api/projects`
- `POST /api/projects`
- `GET /api/projects/{project_id}/messages`
- `POST /api/projects/{project_id}/chat`

Example project creation:

```bash
curl -X POST http://127.0.0.1:8318/api/projects \
  -H 'Content-Type: application/json' \
  -d '{"name":"Coupleboard","description":"React application"}'
```

## Current safety boundary

This MVP does not give models filesystem, shell, Git push, email, or deployment permissions. Codex CLI and Claude Code executors should be added behind workspace allowlists, command policies, explicit approval gates, and auditable task records.

## Next implementation steps

1. Merge the Butler UI into the existing React navigation.
2. Add model capability registry and provider-aware routing.
3. Add tasks, runs, artifacts, and token accounting tables.
4. Add SSE task events.
5. Add sandboxed Codex CLI and Claude Code adapters.
6. Add automated test, lint, build, and cross-supplier review workflows.
