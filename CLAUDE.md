# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

WhatsApp chatbot agent MVP for **La Fórmula** (personal training + sports supplements + pharmaceuticals). The agent is called **"Nico"** and communicates in **Argentine Spanish**. Built with Python/FastAPI, uses OpenRouter (DeepSeek model) for LLM calls, and ChromaDB for RAG-based knowledge retrieval. Maintain Argentine Spanish dialect in any prompt or user-facing text changes.

## Commands

### Run with Docker (recommended)
```bash
docker compose up --build
# Chat UI: http://localhost:7070
# Admin panel: http://localhost:7070/admin
```

### Run locally
```bash
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 7070
```

Requires `.env` with `OPENROUTER_API_KEY` (see `.env.example`).

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

### Module Responsibilities

- **`app/main.py`** — FastAPI server, all HTTP routes, global state (agent, KB, config store, sessions dict). Routes cover: chat, sessions, config CRUD, knowledge base, images, training import, evaluations, introspection.
- **`app/agent.py`** — `WhatsAppAgent` class. Builds message arrays (system prompt + RAG context + history) and calls OpenRouter API via async httpx. Returns reply + debug info (tokens, RAG sources, full messages).
- **`app/knowledge.py`** — `KnowledgeBase` wrapping ChromaDB. Ingests PDFs (PyMuPDF), text, WhatsApp chat exports. Chunks at ~500 chars. Search uses priority-weighted re-ranking: fetches 2x results, scores by `similarity * (1 + priority * 0.1)`, returns top-N.
- **`app/models.py`** — Pydantic models: `ChatMessage`, `ChatSession`, `SendMessageRequest`, `NewSessionRequest`.
- **`app/config.py`** — Loads YAML config from `CLIENT_CONFIG_PATH`, auto-injects product catalog into system prompt.
- **`app/config_store.py`** — `ConfigStore` persists runtime config to `data/runtime_config.yaml`. Bootstraps from `config/config.yaml` if missing. Stores prompt versions (last 20) with rollback.
- **`app/evaluator.py`** — `Evaluator` runs test cases from `training/evaluaciones/test-cases.yaml`. Rules: `must_contain`/`must_not_contain` (case-insensitive). Optional LLM judge (score 1-5, fail if <3).
- **`app/introspector.py`** — `Introspector` analyzes agent responses using debug snapshots. Returns explanation + actionable suggestions (edit_prompt, delete_rag_doc, update_rag_priority).
- **`app/images.py`** — Product image registry (filesystem + `data/images/registry.json`). Fuzzy title matching via slug comparison.
- **`app/image_processor.py`** — Post-processes agent replies: resolves `[IMAGEN: Title]` markers to image URLs.

### Chat Request Flow

1. `POST /api/chat` with `session_id` + `message`
2. Session timeout check — clears history if inactive > N minutes
3. Optional fixed greeting bypass (first message matching patterns → skip LLM)
4. Knowledge base queried: top-5 chunks with priority re-ranking
5. Agent builds message array: system prompt → session context → RAG context → history → user message
6. Async POST to OpenRouter API
7. Image marker post-processing (`[IMAGEN: ...]` → resolved URLs)
8. Response saved to session and returned with optional debug info

### Config Layering

`config/config.yaml` (factory defaults) → `data/runtime_config.yaml` (user edits via admin panel). Runtime file is auto-created from factory defaults on first run. All admin panel changes (prompt, model params, greeting, timeout) persist to runtime config.

### Frontend

Two vanilla HTML/JS/CSS pages (no build step):
- **`app/static/index.html`** — WhatsApp-style chat UI with session sidebar, debug panel per message
- **`app/static/admin.html`** — 3 tabs: Personalidad (prompt editor + versions), Conocimiento (KB docs + training import + images), Entrenamiento (model params + test cases + eval runner + introspection)

### Data Persistence

| Storage | Location | Survives restart |
|---------|----------|-----------------|
| Sessions | In-memory dict | No |
| Knowledge base (ChromaDB) | `data/chroma/` | Yes |
| Product images | `data/images/` | Yes |
| Runtime config | `data/runtime_config.yaml` | Yes |
| Test cases | `training/evaluaciones/test-cases.yaml` | Yes |

### Docker

Single service on port 7070. Mounts `app/`, `config/`, `data/`, `training/` as volumes for hot-reload and persistence.

## Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `OPENROUTER_API_KEY` | Yes | — | OpenRouter API key |
| `CLIENT_CONFIG_PATH` | No | `config/config.yaml` | Business config path |
| `PORT` | No | `7070` | Server port |

## Key Design Decisions

- **Configuration-driven**: Business logic, personality, products all in YAML — same codebase serves different clients.
- **RAG with priority re-ranking**: Documents have `category` + `priority` (1-5) metadata. Higher priority docs score higher in retrieval.
- **All async**: FastAPI + httpx for non-blocking I/O throughout.
- **Debug-first**: Every agent response includes full debug snapshot (prompt sent, RAG chunks with scores, token usage) for introspection.
- **Two-tier config**: Factory defaults in `config/` (version controlled) vs runtime edits in `data/` (user's working copy).
