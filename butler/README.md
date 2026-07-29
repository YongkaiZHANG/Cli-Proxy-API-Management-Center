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

## Alibaba Cloud deployment

The deployment scripts target `112.74.109.99`, keep Butler bound to `127.0.0.1:8318`, place Nginx in front, and enable HTTP Basic Authentication.

Open TCP ports `80` and `443` in the Alibaba Cloud security group before running the scripts. Preserve the ports already used by SSH and Xray.

On the server:

```bash
git clone --branch agent/butler-mvp \
  https://github.com/YongkaiZHANG/Cli-Proxy-API-Management-Center.git
cd Cli-Proxy-API-Management-Center

export BUTLER_GATEWAY_API_KEY='replace-with-your-proxy-api-key'
export BUTLER_BASIC_USER='butler'
export BUTLER_BASIC_PASSWORD='replace-with-a-long-random-password'

sudo -E bash butler/deploy/install.sh
```

This first activates authenticated HTTP. Verify it before requesting a certificate:

```bash
curl -u 'butler:your-password' http://112.74.109.99/api/health
```

Then enable a publicly trusted Let's Encrypt IP-address certificate:

```bash
sudo bash /opt/cli-proxy-management/butler/deploy/enable-ip-https.sh
```

Optionally provide a renewal/contact email:

```bash
sudo LETSENCRYPT_EMAIL='you@example.com' \
  bash /opt/cli-proxy-management/butler/deploy/enable-ip-https.sh
```

The resulting address is:

```text
https://112.74.109.99
```

Useful checks:

```bash
sudo systemctl status butler --no-pager
sudo systemctl status nginx --no-pager
sudo systemctl list-timers | grep certbot-ip-renew
sudo journalctl -u butler -n 100 --no-pager
```

The Let's Encrypt IP certificate is short-lived, so the included systemd timer checks renewal twice daily.

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
