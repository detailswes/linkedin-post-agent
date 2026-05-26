---
title: Automatic Post — Agents
emoji: ✍️
colorFrom: purple
colorTo: blue
sdk: docker
app_port: 7860
pinned: false
---

# LinkedIn Post Agents

A production-ready **CrewAI** microservice that drafts and edits LinkedIn posts using a two-agent pipeline (**Writer → Editor**), backed by **LiteLLM** and **Hugging Face** inference.

## Highlights

- **CrewAI** with YAML-driven agents and tasks (`config/`)
- **FastAPI** HTTP API for integration with any backend or workflow
- **Docker**-ready for cloud deployment (e.g. Hugging Face Spaces)
- **Configurable LLM** via environment variables (no secrets in source code)

## Architecture

```
POST /generate
       │
       ▼
┌──────────────────┐     ┌──────────────────┐
│  Writer agent    │ ──▶ │  Editor agent    │
│  (draft post)    │     │  (polish & fmt)  │
└──────────────────┘     └──────────────────┘
```

Research context (when used) is supplied in the request payload by the calling application; the crew focuses on writing and editorial quality.

## API

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | `GET` | Liveness check — returns `{"ok": true}` |
| `/generate` | `POST` | Generate a LinkedIn post |

**Request body (`POST /generate`):**

```json
{
  "topic": "Your topic or brief",
  "feedback": "Optional revision notes",
  "memory_context": "Optional style or memory context",
  "tone_instruction": "Optional tone guidance"
}
```

**Response:**

```json
{
  "post": "Final LinkedIn post text..."
}
```

## Project layout

```
├── config/
│   ├── agents.yaml    # Agent roles, goals, backstories
│   └── tasks.yaml     # Task descriptions and outputs
├── crew.py            # CrewAI crew definition
├── service.py         # FastAPI application
├── Dockerfile
├── requirements.txt
└── .env.example       # Environment variable template
```

## Configuration

Copy `.env.example` to `.env` and set:

| Variable | Required | Description |
|----------|----------|-------------|
| `HF_TOKEN` | Yes | Hugging Face API token ([create one](https://huggingface.co/settings/tokens)) |
| `AGENTS_LLM_MODEL` | Yes | LiteLLM model id, e.g. `huggingface/Qwen/Qwen2.5-7B-Instruct` |
| `AGENTS_LLM_TEMPERATURE` | No | Sampling temperature (default `0.5`) |
| `AGENTS_LLM_BASE_URL` | No | Custom OpenAI-compatible endpoint URL |
| `PORT` | No | HTTP port (default `7860` in Docker, `9000` for local `python service.py`) |

## Local development

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env with your credentials
uvicorn service:app --host 0.0.0.0 --port 9000
```

## Docker

```bash
docker build -t linkedin-post-agents .
docker run -p 7860:7860 \
  -e HF_TOKEN=your_token \
  -e AGENTS_LLM_MODEL=huggingface/Qwen/Qwen2.5-7B-Instruct \
  linkedin-post-agents
```

## Hugging Face Spaces

This repository can be deployed as a Docker Space. Set `HF_TOKEN` as a **secret** and `AGENTS_LLM_MODEL` as a **variable** in the Space settings. The container listens on `$PORT` (default **7860**).

See [Hugging Face Spaces — managing secrets](https://huggingface.co/docs/hub/spaces-overview#managing-secrets) for deployment details.

## Tech stack

- [CrewAI](https://docs.crewai.com/) — multi-agent orchestration
- [LiteLLM](https://docs.litellm.ai/) — unified LLM interface
- [FastAPI](https://fastapi.tiangolo.com/) — HTTP API
- [Hugging Face](https://huggingface.co/) — model inference
