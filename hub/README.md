# 🚪 Agent Hub — one-link onboarding for AI agents

Give any agent one link (or one command). Seconds later it has its **own Langfuse project with LLM-as-judge evals and rating
scales**, a **LiteLLM gateway key** that traces every call into that project, access to your **knowledge base** and **tracker**,
a **social account**, and a proven smoke trace.

~300 lines of standard-library Python. No framework, no database, 16 MB RAM in production.

```
agent ──curl install.sh──▶ hub ──▶ Langfuse: project + API key + judge connection + 4 evaluators + score configs
                                 ├─▶ LiteLLM: virtual key, logging into that project
                                 ├─▶ Memos: user + personal access token        (optional)
                                 └─▶ returns .env: LANGFUSE_* · OTEL_* · LLM_* · KB_* · PLANE_* · SOCIAL_*
```

## Endpoints

| | |
|---|---|
| `GET /` | the agent guide (Markdown). `?t=<token>` pre-fills the commands — the whole onboarding is "read this link and do it" |
| `GET /install.sh` · `GET /install.ps1` | installers: enroll, merge `.env` (backup + gitignore), send a smoke trace and one gateway call |
| `POST /v1/enroll` | `{"name": "my-agent"}` + `Authorization: Bearer <ENROLL_TOKEN>` → JSON (or `?format=env`) |
| `GET /health` | `ok` |

Idempotent: the same name reuses the same project (fresh keys each time); evaluators and score configs are never duplicated;
`{"repair": true}` re-runs project setup.

## Run it

Requirements: self-hosted **Langfuse v3** (tested on v3.225) and **LiteLLM**; optionally Memos, a SilverBullet knowledge base
and Plane. Copy `.env.example` → `.env`, fill it, then:

```sh
docker compose up -d        # see docker-compose.yml
curl -fsSL https://<your-hub>/install.sh | LF_TOKEN=<ENROLL_TOKEN> sh -s -- my-first-agent
```

## How it works (the non-obvious bits)

- Project, API-key, evaluator and LLM-connection creation have no public API in self-hosted Langfuse, so the hub drives the
  web app's tRPC endpoints with an admin session (`projects.create`, `projectApiKeys.create`, `llmApiKey.create`,
  `defaultLlmModel.upsertDefaultModel`, `evals.createJob`). Score configs use the public API.
- Langfuse **test-calls** the judge model when you save it as default; some models occasionally miss the schema → retried.
- Evaluators target traces with sampling `EVAL_SAMPLING` (default 0.3) and map template variables to trace input/output.
- OTel header is emitted as `Authorization=Basic <b64>,x-langfuse-ingestion-version=4` — with a **literal space**. Some
  exporters (e.g. Claude Code's) don't URL-decode `%20`, and auth then fails silently.
- Logs never contain query strings (the guide link carries the token) or secret values.

## Security notes

- `ENROLL_TOKEN` is a shared enrollment secret: anyone holding it can mint projects and keys. Rotate by setting a new value
  (comma-separate several to roll over). Gateway keys are created with an RPM limit.
- The hub holds a Langfuse admin login and the LiteLLM master key — keep it on an internal network behind HTTPS, run it as a
  separate small container, and keep its env file root-only.

MIT licensed. Extracted from a production platform — see the [main README](../README.md).
