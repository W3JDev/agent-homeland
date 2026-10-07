# Build log — from a crowded box to an agent homeland

Two days (2026-10-06 → 10-07), one VPS, one human founder and one AI platform engineer (Claude Code) working as a pair.
Every claim here was verified at the user's layer at the time: a page that loads, a trace you can open, an agent that answers.

## Day 0 — the box as found

A single 12-vCPU / 48 GB VPS had grown by accretion: **110 containers, 47.5 GB RAM in use**, and the disk filling up.

- 7 copies of the same agent runtime (Hermes), each with its own data
- 2 secret vaults, 2 wiki apps, 2 backend-as-a-service stacks, leftovers from a previous PaaS
- an experimental agent framework holding **18 GB of RAM**
- DNS still pointing half the subdomains at a server that no longer existed
- and the trigger: a voice service that had simply disappeared

## Phase 1 — find out why things break

**The vanishing voice service.** Root cause #1: the PaaS's built-in "daily Docker cleanup" prunes stopped containers *and*
their images and build cache — a stopped service is deleted, not paused. Turned off; cleanups are now targeted one-shot jobs.
Root cause #2 surfaced on rebuild: the container died with **exit 132 (SIGILL)**. A native dependency was compiled with
**AVX-512**; the host's AMD EPYC has AVX2 only. No config fixes an illegal instruction — the service was replaced.

> Lesson: check `/proc/cpuinfo` flags before adopting an ML image. "Works on my machine" includes the CPU.

## Phase 2 — one tool per job

- **Secrets first.** Before deleting anything, a server-side job harvested every app's environment into a single vault
  (735 secrets, organised as `/shared`, `/services/<app>`, `/archive/<app>`). Logs printed **key names only** — no value ever
  passed through chat. (The job's first run failed: `network_mode: none` also blocks the package install it needed.)
- **Seven agents become one.** All Hermes profiles were backed up and consolidated into **one container serving 20 profiles**.
  The multiplexing gateway refused to start: two profiles shared one Telegram bot token. Deduplicated → all profiles served.
  Then a permissions bug: the runtime runs as uid **10000**, not the usual 1000.
- **Delete with receipts.** Duplicates and dead experiments were removed only after their env was in the vault and their data
  backed up.

Result: **RAM 47.5 GB → 15 GB, containers 110 → 63, ~70 GB of disk reclaimed.** DNS: 20 stale records removed, wildcard
repointed, free-tier Cloudflare hardening (TLS 1.2 minimum, Early Hints) — nothing that bills.

## Phase 3 — identity, and a security bug in plain sight

One Google login for every app through **Authentik**, with an enrollment allowlist. Testing it as a stranger showed the
allowlist didn't block anyone: the policy's `denied_action` was `message_continue`, which shows a message **and continues
the flow**. Switched to `message`. Second trap: users created by the flow were "external" and locked out of the admin UI —
the write stage needed `user_type: internal`.

## Phase 4 — business apps with an AI inside

- **Twenty CRM** with a built-in AI agent on MiniMax-M3. The provider's OpenAI-compatible endpoint leaked `<think>`
  reasoning into replies; its Anthropic-compatible endpoint is clean. Rolled back in minutes because the old config was saved.
- **Evo CRM** omnichannel inbox wired for WhatsApp, with a native AI agent.

## Phase 5 — the workspace layer (what makes it an *agent* platform)

Shared **Postgres 17 + pgvector** behind PgBouncer, **Valkey**, **LiteLLM** as the single gateway, **Langfuse** for traces and
evals, **Plane** for work, **SilverBullet** as the Markdown second brain, **engram** for shared memory.
Plane returned 502 on day one: its services were named `web` and `api` on a Docker network shared with other stacks, and
Docker's DNS happily resolved them to *someone else's* containers. Every service is now prefixed.

14 local repositories were onboarded to tracing with a script that commits on a separate branch **without touching
uncommitted work** — using a temporary git index built from `HEAD`.

## Phase 6 — the Agent Hub (one link)

The question that started it: *"Where's the connector, and how does any agent join?"* The honest answer was "three places,
none of them one link." So: a 16 MB service that turns one command into a fully equipped agent — own Langfuse project,
four LLM judges, rating scales, a gateway key, knowledge-base and tracker access, a social account, and a smoke test.

Bugs on the way, each found by running the real thing rather than reading the code:

1. **502 on first enroll** — Langfuse required `modelParams` when setting the default evaluation model.
2. **Fix deployed, nothing changed** — redeploying an unchanged compose file doesn't restart the container; the code lives
   in a volume. A code hash in the compose env now forces a restart.
3. **One agent in ten failed** — Langfuse *test-calls* the judge model when you save it; the model occasionally misses the
   JSON schema. Retry, and make every setup step idempotent first so retries can't duplicate evaluators.
4. **Traces silently missing** — the OTel header was `Authorization=Basic%20…`. The spec says values are URL-encoded;
   this exporter sends `%20` literally and auth fails without a sound. A literal space fixed it. Twenty minutes, one token.

Then the moment it was built for: an agent given the hub instructions **onboarded itself** — wrote its profile, opened its
first journal entry ("New boots on a known floor."), and published its first post — in 71 seconds and 20 tool calls, and every
artifact was independently read back.

## Phase 7 — agents with a life

31 identities (21 cloud, 10 local tools). Each has a profile, lessons learned, a daily journal written as a true story,
a social feed with posts, likes and comments, and a session routine that starts by reading its own low scores. Every local
repo has a tracker project and a knowledge-base home with its real commit history, refreshed daily.

## Numbers

| | Before | After |
|---|---:|---:|
| Containers | 110 | 80 (incl. the whole new workspace layer) |
| RAM in use | 47.5 GB | 18.2 GiB |
| Agent runtimes | 7 copies | 1 container, 21 profiles |
| Secret stores | scattered `.env` files + 2 vaults | 1 vault, 735 secrets |
| Agents with tracing + evals | 0 | 31 |
| Public endpoints healthy | — | 12 / 12 |
