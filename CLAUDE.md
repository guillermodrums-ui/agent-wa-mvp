# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

WhatsApp chatbot agent MVP for **La Fórmula** (personal training + sports supplements + pharmaceuticals). The agent **"Nico"** handles customer inquiries via WhatsApp (Evolution API) and a web-based simulator. Built with Python/FastAPI, OpenRouter (DeepSeek) for LLM, ChromaDB for RAG. Maintains **Argentine Spanish** dialect in all prompts and user-facing text.

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

### Import catalog to RAG (with server running)
```bash
bash scripts/import-catalogo-rag.sh
```

### Reset data (deletes ChromaDB, images, sessions, runtime config)
```bash
bash reset.sh
```

### Run evaluation test suite
Via admin panel (Entrenamiento tab) or `POST /api/evaluations/run`.

### No automated test framework configured yet

## Architecture

### Two Message Paths

1. **Simulator** (web UI): `POST /api/chat` → session lookup → RAG search → LLM call → response returned to browser
2. **WhatsApp** (real): Evolution API webhook → `POST /api/webhooks/evolution` → parse + dedup → get/create session by phone → RAG + LLM → send reply back via Evolution API

Both paths share the same agent (`WhatsAppAgent.chat()`), knowledge base, and session store.

### Module Responsibilities

- **`app/main.py`** — FastAPI server, all HTTP routes, global state (agent, KB, config store, sessions dict). Routes cover: chat, sessions, config CRUD, knowledge base, images, training import, evaluations, introspection, handoff endpoints.
- **`app/agent.py`** — `WhatsAppAgent` class. Builds message arrays (system prompt + RAG context + history) and calls OpenRouter API via async httpx. Returns reply + debug info (tokens, RAG sources, full messages).
- **`app/knowledge.py`** — `KnowledgeBase` wrapping ChromaDB. Ingests PDFs (PyMuPDF), text, WhatsApp chat exports. Chunks at ~500 chars. Search uses priority-weighted re-ranking: fetches 2x results, scores by `similarity * (1 + priority * 0.1)`, returns top-N.
- **`app/models.py`** — Pydantic models: `ChatMessage`, `ChatSession`, `SendMessageRequest`, `NewSessionRequest`, `HandoffRequest`, `OperatorReplyRequest`.
- **`app/config.py`** — Loads YAML config from `CLIENT_CONFIG_PATH`, auto-injects product catalog into system prompt.
- **`app/config_store.py`** — `ConfigStore` persists runtime config to `data/runtime_config.yaml`. Bootstraps from `config/config.yaml` if missing. Stores prompt versions (last 20) with rollback.
- **`app/evaluator.py`** — `Evaluator` runs test cases from `training/evaluaciones/test-cases.yaml`. Rules: `must_contain`/`must_not_contain` (case-insensitive). Optional LLM judge (score 1-5, fail if <3).
- **`app/introspector.py`** — `Introspector` analyzes agent responses using debug snapshots. Returns explanation + actionable suggestions (edit_prompt, delete_rag_doc, update_rag_priority).
- **`app/images.py`** — Product image registry (filesystem + `data/images/registry.json`). Fuzzy title matching via slug comparison.
- **`app/image_processor.py`** — Post-processes agent replies: resolves `[IMAGEN: Title]` markers to image URLs.

### Chat Request Flow

1. `POST /api/chat` with `session_id` + `message`
2. Session timeout check — clears history if inactive > N minutes
3. If session is in handoff/human mode → save message, skip LLM, return `handoff: true`
4. Optional fixed greeting bypass (first message matching patterns → skip LLM)
5. Knowledge base queried: top-5 chunks with priority re-ranking
6. Agent builds message array: system prompt → session context → RAG context → history → user message
7. Async POST to OpenRouter API
8. Image marker post-processing (`[IMAGEN: ...]` → resolved URLs)
9. `[HANDOFF]` tag detection — if present, set session to `handoff_pending`
10. Response saved to session and returned with optional debug info

### Human Handoff

Sessions have a `mode` field: `bot` | `handoff_pending` | `human`. The agent triggers handoff by prefixing its reply with `[HANDOFF]`. Operators manage handoffs via the Conversaciones tab in admin:
- `POST /api/sessions/{id}/handoff` — change mode (handoff_pending/human/bot)
- `POST /api/sessions/{id}/reply` — send operator message (source="human")
- `GET /api/handoffs/pending` — list sessions awaiting operator

### Config Layering

`config/config.yaml` (factory defaults) → `data/runtime_config.yaml` (user edits via admin panel). Runtime file is auto-created from factory defaults on first run. All admin panel changes (prompt, model params, greeting, timeout) persist to runtime config.

### Frontend

Two vanilla HTML/JS/CSS pages (no build step):
- **`app/static/index.html`** — WhatsApp-style chat UI with session sidebar, debug panel per message, handoff banner
- **`app/static/admin.html`** — 4 tabs: Personalidad (prompt editor + versions), Conocimiento (KB docs + training import + images), Entrenamiento (model params + test cases + eval runner + introspection), Conversaciones (handoff management with operator reply)

## Docker Setup

| Storage | Location | Survives restart |
|---------|----------|-----------------|
| Sessions | In-memory dict | No |
| Knowledge base (ChromaDB) | `data/chroma/` | Yes |
| Product images | `data/images/` | Yes |
| Runtime config | `data/runtime_config.yaml` | Yes |
| Test cases | `training/evaluaciones/test-cases.yaml` | Yes |

### Docker

Three services in `docker-compose.yml`:
- **`agent`** (port 7070) — this app, with hot-reload volumes for `app/`, `config/`, `data/`, `training/`
- **`evolution-api`** (port 8080) — `evoapicloud/evolution-api:v2.3.7` with PostgreSQL + Prisma. Sends webhooks to `http://agent:7070/api/webhooks/evolution`
- **`postgres`** (5432) — backing store for Evolution API only

## Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `OPENROUTER_API_KEY` | Yes | — | OpenRouter API key |
| `CLIENT_CONFIG_PATH` | No | `config/config.yaml` | Business config path |
| `EVOLUTION_API_URL` | For WhatsApp | — | Evolution API base URL (e.g. `http://evolution-api:8080`) |
| `EVOLUTION_API_KEY` | For WhatsApp | — | Evolution API authentication key |
| `EVOLUTION_INSTANCE_NAME` | No | `laformula` | Instance name |
| `PORT` | No | `7070` | Server port |

## Data Persistence

- **Configuration-driven**: Business logic, personality, products all in YAML — same codebase serves different clients.
- **RAG with priority re-ranking**: Documents have `category` + `priority` (1-5) metadata. Higher priority docs score higher in retrieval.
- **All async**: FastAPI + httpx for non-blocking I/O throughout.
- **Debug-first**: Every agent response includes full debug snapshot (prompt sent, RAG chunks with scores, token usage) for introspection.
- **Two-tier config**: Factory defaults in `config/` (version controlled) vs runtime edits in `data/` (user's working copy).
