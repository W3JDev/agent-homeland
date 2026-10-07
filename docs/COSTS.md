# The bill — self-hosted vs SaaS

Prices were read from each vendor's official pricing page on **2026-10-07** (third-party sources are marked).
Assumption: a small team (3 seats) with moderate usage, monthly billing unless noted. "Cheapest" = the cheapest plan that
credibly covers what runs here; "typical" = the plan most teams would actually pick.

## Self-hosted

| Item | Monthly |
|---|---:|
| Contabo Cloud VPS 12 — 12 vCPU, 48 GB RAM, 400 GB SSD (list price on a 24-month term, incl. VAT) | ≈ €25 (≈ $29) |
| All software (open source) | $0 |
| Cloudflare (free plan: DNS, proxy, TLS, tunnels) | $0 |
| **Total** | **≈ $29** |

For reference, a comparable dedicated-vCPU cloud box (Hetzner CCX43, 16 vCPU / 64 GB) lists at €275.99/month — the stack
would still be ~3–6× cheaper than SaaS there.

## SaaS equivalents

| What runs here | Cheapest credible | $/mo | Typical | $/mo | Source |
|---|---|---:|---|---:|---|
| Langfuse (tracing, evals) | Langfuse Cloud Core | 29 | Langfuse Cloud Pro | 199 | [langfuse.com/pricing](https://langfuse.com/pricing) |
| LiteLLM (LLM gateway) | Portkey Production | 49 | Portkey Production | 49 | [portkey.ai/pricing](https://portkey.ai/pricing) |
| Infisical (secrets) | Infisical Pro, 3 identities | 69 | Infisical Pro | 69 | [infisical.com/pricing](https://infisical.com/pricing) |
| Authentik (SSO) | Clerk Pro | 25 | Auth0 B2C Essentials, 1k MAU | 70 | [clerk.com](https://clerk.com/pricing) · [auth0.com](https://auth0.com/pricing) |
| Twenty CRM | Twenty Cloud Pro (≈ monthly) | 36 | HubSpot Sales Hub Starter | 60 | [twenty.com](https://twenty.com/pricing) · [hubspot.com](https://www.hubspot.com/pricing/sales) |
| Evo CRM (omnichannel + WhatsApp) | Chatwoot Business, 3 agents | 117 | Chatwoot Business | 117 | [chatwoot.com/pricing](https://www.chatwoot.com/pricing) |
| Plane (tracker) | Plane Cloud Pro | 24 | Linear Business (annual) | 48 | [plane.so](https://plane.so/pricing) · [linear.app](https://linear.app/pricing) |
| SilverBullet (knowledge base) | Notion Plus | 30 | Notion Business | 60 | [notion.com/pricing](https://www.notion.com/pricing) |
| Memos (agent feed) | Slack Pro | 26 | Slack Pro | 26 | [slack.com/pricing](https://slack.com/pricing) |
| Hermes (21-agent runtime) | Lindy, entry credits ¹ | 30 | Lindy, 3 users ¹ | 90 | [lindy.ai/pricing](https://www.lindy.ai/pricing) |
| OpenHands (coding agent) | OpenHands Cloud Individual | 0 | Devin Teams | 200 | [openhands.dev](https://www.openhands.dev/pricing) · [devin.ai](https://devin.ai/pricing) |
| engram (agent memory) | Mem0 Starter | 19 | Zep Flex | 125 | [mem0.ai](https://mem0.ai/pricing) · [getzep.com](https://www.getzep.com/pricing) |
| Dokploy (hosting ~80 containers) | Railway Pro + 18 GB RAM usage ² | 202 | Railway Pro + 18 GB RAM usage ² | 202 | [railway.com/pricing](https://railway.com/pricing) |
| Postgres + pgvector | Neon Launch, 1 CU 24/7 | 77 | Supabase Pro + Large compute | 125 | [neon.com](https://neon.com/pricing) · [supabase.com](https://supabase.com/pricing) |
| Valkey (Redis) | Upstash fixed 250 MB | 10 | Upstash fixed 250 MB | 10 | [upstash.com](https://upstash.com/pricing/redis) |
| Voice studio | ElevenLabs Creator | 22 | ElevenLabs Pro | 99 | [elevenlabs.io/pricing](https://elevenlabs.io/pricing) |
| Blob storage (~50 GB) | Cloudflare R2 | 0.60 | Cloudflare R2 | 0.60 | [R2 pricing](https://developers.cloudflare.com/r2/pricing/) |
| **Total** | | **≈ $766** | | **≈ $1,550** | |

¹ Low confidence: Lindy bills workspace users separately and 21 always-on agents would likely need a larger credit tier.
² Railway rates (~$10 per GB RAM per month) × the 18.2 GiB this stack actually uses + $20 plan; CPU excluded, so this is a floor.

## What this comparison leaves out

- **LLM tokens** — identical on both sides (the gateway routes to the same providers).
- **Engineering time** — real. Consolidating, securing and wiring this took days of focused work; see the [build log](BUILD-LOG.md).
  The trade only makes sense when you'd build the skills anyway — or when per-seat pricing would punish 31 agents.
- **Scale effects** — seat-based SaaS gets *more* expensive as agents multiply; here, agent #32 costs ~0 extra.
