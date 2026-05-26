# PostForge — LinkedIn Post Agent

> **AI-assisted LinkedIn writing platform: topic research, multi-tone CrewAI generation, approve/reject refinement, tone memory, and OAuth publishing.**

This repository is a full-stack reference implementation for building an agentic content workflow. A Next.js UI streams generation progress over SSE; a FastAPI backend orchestrates jobs, memory, and LinkedIn OAuth; a CrewAI microservice drafts and polishes posts using Hugging Face models via LiteLLM. Deploy the agents service on a [Hugging Face Space](https://huggingface.co/docs/hub/spaces) or run it locally from `agents/`.

---

## Table of Contents

1. [What This Demonstrates](#1-what-this-demonstrates)
2. [Tech Stack](#2-tech-stack)
3. [How the Generation Flow Works](#3-how-the-generation-flow-works)
4. [Project Structure](#4-project-structure)
5. [Getting Started](#5-getting-started)
6. [Environment Variables](#6-environment-variables)
7. [API Reference](#7-api-reference)
8. [Agents Service](#8-agents-service)
9. [Security & Session Design](#9-security--session-design)
10. [Deploy](#10-deploy)
11. [Production Checklist](#11-production-checklist)

---

## 1. What This Demonstrates

| Concern | What the codebase shows |
|---|---|
| **Agentic content pipeline** | Research → multi-tone generation → human approval → optional LinkedIn publish |
| **CrewAI multi-agent crew** | YAML-driven Writer → Editor sequential crew (`agents/`) |
| **Async job queue** | MongoDB-backed `generation_jobs`; background worker decoupled from HTTP |
| **Real-time UX** | SSE event stream with stage labels, variant results, and draft replay |
| **Tone memory** | Learns from approved/rejected posts; injects context into future generations |
| **LinkedIn OAuth** | Sign in with LinkedIn, token lifecycle, UGC post API |
| **Optional research** | Serper news snippets ground the writer when `SERPER_API_KEY` is set |
| **Split deployment** | Frontend (Vercel/Render), API+worker (Render Docker), agents (HF Space) |

---

## 2. Tech Stack

| Layer | Technology |
|---|---|
| Frontend | [Next.js 16](https://nextjs.org) — App Router, React 19, Tailwind CSS 4, TypeScript |
| Backend API | [FastAPI](https://fastapi.tiangolo.com) — CORS, cookie sessions, CSRF on mutating routes |
| Database | [MongoDB](https://www.mongodb.com) via [Motor](https://motor.readthedocs.io) (async) |
| Agents | [CrewAI](https://docs.crewai.com) + [LiteLLM](https://docs.litellm.ai) → Hugging Face inference |
| Research (optional) | [Serper](https://serper.dev) — news search for topics and trending ideas |
| Auth | HMAC-signed session cookies; LinkedIn OAuth 2.0 |
| Local infra | Docker Compose (MongoDB + API) |
| Production blueprint | `render.yaml` — `postforge-api` + `postforge-web` |

---

## 3. How the Generation Flow Works

```
┌─────────────┐   POST /api/start { topic }        ┌─────────────┐
│   Browser   │ ──────────────────────────────────▶│   FastAPI   │
│  (Next.js)  │                                    │             │
│             │◀── { session_id } ─────────────────│  Create     │
│             │                                    │  session    │
└─────────────┘                                    └─────────────┘

┌─────────────┐   POST /api/generate               ┌─────────────┐
│   Browser   │ ──────────────────────────────────▶│   FastAPI   │
│             │   { session_id, topic, ... }        │             │
│             │                                    │  Enqueue    │
│             │◀── { job_id } ─────────────────────│  job row    │
└─────────────┘                                    └─────────────┘

┌─────────────┐   GET /api/stream/jobs/{job_id}    ┌─────────────┐
│   Browser   │ ─────── SSE (text/event-stream) ──▶│   FastAPI   │
│             │◀── status / stage / variant_* ─────│  Replays    │
│             │                                    │  job events │
└─────────────┘                                    └─────────────┘

                              ┌─────────────┐
                              │   Worker    │  polls MongoDB queue
                              │  worker.py  │
                              └──────┬──────┘
                                     │
         1. Serper research (opt.)   │
         2. For each tone variant:   ▼
                              ┌─────────────┐
                              │ Agents svc  │  POST /generate
                              │ (CrewAI)    │  Writer → Editor
                              └──────┬──────┘
                                     │
         3. Persist drafts          ▼
         4. SSE: variants event     MongoDB
```

**Approval loop**

```
User picks a draft variant
        │
        ▼
POST /api/approve { session_id, draft_id, action: "approve" | "reject", feedback? }
        │
        ├─ approve → LinkedIn UGC post (if connected) → tone memory updated
        └─ reject  → feedback stored → POST /api/generate enqueues a revision job
```

**Why a separate worker?**  
Generation can take minutes (multiple tone variants × LLM calls). The API enqueues work and streams persisted events so clients can reconnect without blocking request threads.

---

## 4. Project Structure

```
linkedin-post-agent/
├── frontend/                 # Next.js UI — drafts, SSE, LinkedIn connect, memory panel
│   ├── app/
│   │   ├── page.tsx          # Main editor + generation UI
│   │   ├── layout.tsx
│   │   └── globals.css
│   └── lib/
│       └── api.ts            # API base URL, CSRF helpers
│
├── backend/
│   ├── app/
│   │   ├── main.py           # FastAPI app factory
│   │   ├── routes/           # auth, generation, memory, linkedin, suggestions, health
│   │   ├── services/
│   │   │   ├── generation/   # pipeline, queue, approval, agent HTTP client
│   │   │   ├── tone_memory.py
│   │   │   ├── linkedin.py
│   │   │   └── security.py   # sessions, CSRF, cookie helpers
│   │   └── core/             # settings, SSE helpers, rate limit
│   ├── worker.py             # Background job processor
│   ├── scripts/
│   │   ├── render_start.sh   # API + worker (Render / docker-compose api)
│   │   └── start_worker.sh
│   ├── Dockerfile
│   └── .env.example
│
├── agents/                   # CrewAI microservice (deploy as HF Space or run locally)
│   ├── config/
│   │   ├── agents.yaml       # Writer & Editor roles
│   │   └── tasks.yaml        # Task descriptions
│   ├── crew.py               # ContentCrew definition
│   ├── service.py            # FastAPI — GET /health, POST /generate
│   ├── Dockerfile
│   └── requirements.txt
│
├── docker-compose.yml        # mongo + api (optional split-worker profile)
└── render.yaml               # Render blueprint (API + Next.js)
```

---

## 5. Getting Started

### Prerequisites

- **Node.js** 20+
- **Python** 3.11+ (backend + agents)
- **MongoDB** — [Atlas](https://www.mongodb.com/atlas) or local via Docker Compose
- **Agents service** — Hugging Face Space **or** local `agents/` with `HF_TOKEN`
- **Optional:** [Serper](https://serper.dev/) API key, [LinkedIn Developer](https://www.linkedin.com/developers/) app

### Installation

```bash
# 1. Clone and navigate
git clone <repo-url>
cd linkedin-post-agent

# 2. Backend environment
cp backend/.env.example backend/.env
# Edit backend/.env — at minimum MONGODB_URI, AGENT_SERVICE_URL, SESSION_SECRET

# 3. MongoDB (local)
docker compose up -d mongo

# 4. Backend + worker
cd backend
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m uvicorn app.main:app --port 8000 --reload
```

Separate terminal (worker):

```bash
cd backend && source .venv/bin/activate && python worker.py
```

Agents (local — separate terminal):

```bash
cd agents
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
# Set HF_TOKEN, AGENTS_LLM_MODEL (see agents/README.md)
uvicorn service:app --host 0.0.0.0 --port 9000
```

Point `AGENT_SERVICE_URL=http://localhost:9000` in `backend/.env`.

Frontend:

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:3000 (`NEXT_PUBLIC_API_BASE_URL` defaults to http://localhost:8000).

### Smoke tests

```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:9000/health

curl -X POST http://127.0.0.1:9000/generate \
  -H "Content-Type: application/json" \
  -d '{"topic":"Shipping fast without breaking quality","tone_instruction":"thought leadership"}'
```

### Docker Compose (API + Mongo)

```bash
# Requires AGENT_SERVICE_URL pointing at your HF Space or host.docker.internal:9000
docker compose up -d mongo api
```

Use profile `split-worker` if you want the worker in a separate container:

```bash
docker compose --profile split-worker up -d
```

---

## 6. Environment Variables

Copy `backend/.env.example` to `backend/.env`. Never commit `backend/.env`.

### Backend (`backend/.env`)

| Variable | Required | Description |
|---|---|---|
| `MONGODB_URI` | **Yes** | MongoDB connection string |
| `MONGODB_DB` | **Yes** | Database name (default `automatic_post_agent`) |
| `AGENT_SERVICE_URL` | **Yes** | Agents base URL, no trailing slash (e.g. `https://user-space.hf.space` or `http://localhost:9000`) |
| `SESSION_SECRET` | **Yes in prod** | HMAC key for session cookies. Generate: `python -c "import secrets; print(secrets.token_hex(32))"` |
| `API_PUBLIC_BASE_URL` | **Yes in prod** | Public backend URL (OAuth callbacks, cookies) |
| `FRONTEND_ORIGIN` | **Yes in prod** | Frontend origin for CORS |
| `ALLOWED_ORIGINS` | **Yes in prod** | Comma-separated CORS origins (often same as `FRONTEND_ORIGIN`) |
| `COOKIE_SECURE` | No | `1` in production HTTPS; `0` for local HTTP |
| `AUTH_COOKIE_SAMESITE` | No | `lax` (same-site) or `none` (split frontend/API hosts) |
| `LI_CLIENT_ID` / `LI_CLIENT_SECRET` | For LinkedIn | OAuth + posting |
| `LI_REDIRECT_URI` | No | Defaults to `{API_PUBLIC_BASE_URL}/auth/linkedin/callback` |
| `SERPER_API_KEY` | No | News research + trending topics |
| `GEN_RATE_PER_MIN` / `GEN_BURST` | No | Per-user generation rate limit (defaults `6` / `3`) |

### Frontend

| Variable | Required | Description |
|---|---|---|
| `NEXT_PUBLIC_API_BASE_URL` | No | API URL (default `http://localhost:8000`). **Set at build time on Render/Vercel.** |

### Agents (Hugging Face Space secrets or `agents/.env`)

| Variable | Required | Description |
|---|---|---|
| `HF_TOKEN` | **Yes** | [Hugging Face access token](https://huggingface.co/settings/tokens) with inference access |
| `AGENTS_LLM_MODEL` | **Yes** | LiteLLM model id, e.g. `huggingface/Qwen/Qwen2.5-7B-Instruct` |
| `AGENTS_LLM_TEMPERATURE` | No | Sampling temperature (default `0.5`) |
| `AGENTS_LLM_BASE_URL` | No | Custom OpenAI-compatible endpoint |
| `PORT` | No | HTTP port (`7860` in Docker/HF Space, `9000` for local `python service.py`) |

---

## 7. API Reference

All JSON endpoints live on the FastAPI backend unless noted. Mutating routes require a session cookie and `X-CSRF-Token` header (see [Security](#9-security--session-design)).

### Health

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | API liveness |

### Auth & session

| Method | Path | Description |
|---|---|---|
| `POST` | `/auth/bootstrap` | Create guest session; returns `csrf_token` |
| `GET` | `/auth/csrf` | Refresh CSRF token (requires session) |
| `GET` | `/auth/linkedin/login` | Redirect to LinkedIn OAuth |
| `GET` | `/auth/linkedin/callback` | OAuth callback (browser redirect) |
| `GET` | `/auth/linkedin/me` | LinkedIn profile + token status |
| `POST` | `/auth/linkedin/logout` | Revoke session / disconnect |

### Generation

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/start` | Create generation session — body `{ "topic": "..." }` |
| `POST` | `/api/generate` | Enqueue job — body `{ "session_id", "topic", "variant_id?", "feedback?" }` |
| `GET` | `/api/stream/jobs/{job_id}` | **SSE** stream of job events |
| `POST` | `/api/approve` | Approve or reject draft — body `{ "session_id", "draft_id", "action", "feedback?" }` |
| `GET` | `/api/session/{session_id}` | Session state + drafts |
| `DELETE` | `/api/session/{session_id}` | Delete session |

**SSE event types (representative):** `status`, `stage`, `variant_start`, `variant_result`, `variants`, `error`.

### Memory & publishing

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/memory` | Posted history, saved drafts, tone/writer profiles |
| `DELETE` | `/api/memory` | Clear tone memory and post history |
| `POST` | `/api/memory/saved-drafts` | Save draft (requires LinkedIn connected) |
| `DELETE` | `/api/memory/saved-drafts/{id}` | Delete saved draft |
| `POST` | `/api/memory/saved-drafts/{id}/publish` | Publish saved draft to LinkedIn |

### Suggestions

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/trending-topics` | Trending topic ideas (Serper or fallback list) |
| `POST` | `/api/suggestions` | Follow-up topic ideas from draft text — `{ "post_text", "topic?", "exclude?" }` |

### Agents service (external)

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Returns `{ "ok": true }` |
| `POST` | `/generate` | Body `{ "topic", "feedback?", "memory_context?", "tone_instruction?" }` → `{ "post": "..." }` |

Default tone variants generated per job (unless `variant_id` is set): Technical / Deep Dive, Thought Leadership, Educational, Storytelling.

---

## 8. Agents Service

The `agents/` package is a standalone FastAPI + CrewAI service. Deploy it as a **Docker Hugging Face Space** (recommended for GPU/inference) or run it beside the backend for development.

```
POST /generate
       │
       ▼
┌──────────────────┐     ┌──────────────────┐
│  Writer agent    │ ──▶ │  Editor agent    │
│  (draft post)    │     │  (polish & fmt)  │
└──────────────────┘     └──────────────────┘
```

Research context is assembled by the **backend** (Serper snippets + tone/memory strings) and passed in the `topic` / `memory_context` / `tone_instruction` fields — the crew focuses on writing and editorial quality.

See [`agents/README.md`](agents/README.md) for Space deployment, Docker build, and model configuration.

---

## 9. Security & Session Design

### Session cookies

- Opaque session token stored in an **httpOnly** cookie; only an **HMAC-SHA256** hash is persisted in MongoDB (`SESSION_SECRET`).
- Guest sessions are created via `POST /auth/bootstrap` so the UI can generate content before LinkedIn sign-in.

### CSRF

- Mutating routes (`POST` / `DELETE` with side effects) require `X-CSRF-Token` matching the `csrf_token` cookie issued at bootstrap.
- The frontend refreshes CSRF via `lib/api.ts` before credentialed fetches.

### LinkedIn OAuth

- Authorization code flow with short-lived `li_oauth_state` cookie (15 minutes).
- Access tokens stored server-side; UGC posts use `w_member_social` scope.
- Expired tokens return `needs_reconnect` so the UI can prompt re-auth.

### Rate limiting

- Token-bucket limiter on generation enqueue (`GEN_RATE_PER_MIN`, `GEN_BURST`) to reduce abuse.

### CORS

- `ALLOWED_ORIGINS` must include the frontend URL; `allow_credentials=True` for cookie-based auth.

---

## 10. Deploy

| Component | Suggested host | Notes |
|---|---|---|
| Frontend | Render (`postforge-web`) or Vercel | Set `NEXT_PUBLIC_API_BASE_URL` at **build** time |
| Backend + worker | Render Docker (`postforge-api`) | `render_start.sh` runs API + worker in one container |
| Agents | **Hugging Face Space** (Docker) | Set `HF_TOKEN` secret; configure `AGENTS_LLM_MODEL` |
| Database | MongoDB Atlas | Connection string in `MONGODB_URI` |

`render.yaml` wires default URLs for `postforge-api.onrender.com` and `postforge-web.onrender.com`. If Render assigns different hostnames, update `API_PUBLIC_BASE_URL`, `FRONTEND_ORIGIN`, `ALLOWED_ORIGINS`, `NEXT_PUBLIC_API_BASE_URL`, and `LI_REDIRECT_URI` to match.

**Render secrets (postforge-api):** `MONGODB_URI`, `SESSION_SECRET`, `AGENT_SERVICE_URL`, `LI_CLIENT_ID`, `LI_CLIENT_SECRET`, optional `SERPER_API_KEY`.

---

## 11. Production Checklist

- [ ] `SESSION_SECRET` set via secrets manager (≥ 32 random bytes)
- [ ] `MONGODB_URI` points to Atlas (or managed MongoDB) with backups enabled
- [ ] `AGENT_SERVICE_URL` set to production Hugging Face Space URL
- [ ] `API_PUBLIC_BASE_URL`, `FRONTEND_ORIGIN`, and `ALLOWED_ORIGINS` match deployed URLs
- [ ] `NEXT_PUBLIC_API_BASE_URL` set on frontend **before** production build
- [ ] `COOKIE_SECURE=1` and HTTPS on all public endpoints
- [ ] `AUTH_COOKIE_SAMESITE=none` if frontend and API are on different registrable domains
- [ ] LinkedIn app redirect URI matches `LI_REDIRECT_URI` exactly
- [ ] `HF_TOKEN` and `AGENTS_LLM_MODEL` configured on the Space (not in this repo)
- [ ] Worker process running (included in `render_start.sh` or separate `worker` service)
- [ ] Optional: `SERPER_API_KEY` for research and trending topics

---
