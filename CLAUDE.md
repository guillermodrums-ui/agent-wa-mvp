# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

WhatsApp chatbot agent MVP for **La Fórmula** (personal training + sports supplements in Uruguay). The agent **"Nico"** handles customer inquiries via WhatsApp (Evolution API) and a web-based simulator. Built with Python/FastAPI, OpenRouter (DeepSeek) for LLM, ChromaDB for RAG, SQLite for sessions.

**All agent responses must be in Argentine/Uruguayan Spanish** (vos, tenés, che).

## Commands

### Run with Docker (recommended — starts all 3 services)
```bash
docker compose up --build
# Agent: http://localhost:7070  |  Admin: http://localhost:7070/admin
# Evolution API: http://localhost:8080
```

### Run locally (agent only, no WhatsApp)
```bash
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 7070
```

Requires `.env` with at minimum `OPENROUTER_API_KEY` and `CLIENT_CONFIG_PATH=config/config.yaml` (see `.env.example`).

### No test framework configured yet

## Architecture

### Two Message Paths

1. **Simulator** (web UI): `POST /api/chat` → session lookup → RAG search → LLM call → response returned to browser
2. **WhatsApp** (real): Evolution API webhook → `POST /api/webhooks/evolution` → parse + dedup → get/create session by phone → RAG + LLM → send reply back via Evolution API

Both paths share the same agent (`WhatsAppAgent.chat()`), knowledge base, and session store.

### Module Responsibilities

- **`app/main.py`** — FastAPI server, all HTTP routes, webhook handler, session orchestration. Wires together agent, KB, session store, and channel manager at module level.
- **`app/agent.py`** — `WhatsAppAgent` class. Builds message array (system prompt + optional prompt_context + RAG chunks + history) and calls OpenRouter. Returns reply + debug info (token usage, RAG sources, response time).
- **`app/knowledge.py`** — `KnowledgeBase` wrapping ChromaDB. Ingests PDFs (PyMuPDF), text, WhatsApp chat exports. Chunks by paragraph (500 chars max), searches with cosine similarity (top-5).
- **`app/sessions.py`** — `SessionStore` using `aiosqlite`. Tables: `sessions`, `messages`, `processed_webhooks`. WAL mode. Handles session CRUD, message persistence, and webhook deduplication.
- **`app/models.py`** — Pydantic models: `ChatMessage`, `ChatSession`, `SendMessageRequest`, `NewSessionRequest`.
- **`app/config.py`** — Loads YAML from `CLIENT_CONFIG_PATH`. Auto-appends `config/catalogo.txt` (if present) into the system prompt.
- **`app/channels/`** — Channel abstraction: `BaseChannel` ABC, `ChannelManager` registry, `WhatsAppChannel` (Evolution API v2 client).

### Webhook Filtering (Evolution API)

The webhook handler in `main.py` aggressively filters incoming events:
- Only processes `messages.upsert` events
- Skips: `fromMe` (prevents reply loops), group messages (`@g.us`), non-text messages
- Deduplicates via `message_id` in SQLite (cleaned up every 5 min)

### Config-Driven Agent

Business logic, personality, and product catalog live in `config/config.yaml`. The system prompt, model, temperature, and max_tokens are all configurable there. Product catalog can also be loaded from `config/catalogo.txt`.

### Frontend

Two vanilla HTML/JS/CSS pages (no build step):
- **`app/static/index.html`** — WhatsApp-style chat UI with session sidebar (shows WA badge + sender_name for real sessions)
- **`app/static/admin.html`** — 3 tabs: Personalidad (edit system prompt), Conocimiento (KB management), Canales (WhatsApp QR connect/disconnect)

## Docker Setup

Three services in `docker-compose.yml`:
- **`agent`** (port 7070) — this app, with hot-reload volumes for `app/`, `config/`, `data/`
- **`evolution-api`** (port 8080) — `evoapicloud/evolution-api:v2.3.7` with PostgreSQL + Prisma. Sends webhooks to `http://agent:7070/api/webhooks/evolution`
- **`postgres`** (5432) — backing store for Evolution API only

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `OPENROUTER_API_KEY` | Yes | OpenRouter API key for LLM |
| `CLIENT_CONFIG_PATH` | Yes | Path to client YAML config (default: `config/config.yaml`) |
| `EVOLUTION_API_URL` | For WhatsApp | Evolution API base URL (e.g. `http://evolution-api:8080`) |
| `EVOLUTION_API_KEY` | For WhatsApp | Evolution API authentication key |
| `EVOLUTION_INSTANCE_NAME` | No | Instance name (default: `laformula`) |
| `PORT` | No | Server port (default: `7070`) |

## Data Persistence

- **Sessions + messages**: SQLite at `data/sessions.db` (WAL mode)
- **Knowledge base**: ChromaDB at `data/chroma/`
- **Webhook dedup**: `processed_webhooks` table in same SQLite DB (auto-cleaned every 5 min)
- All persisted via `./data` Docker volume mount
