# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

WhatsApp chatbot agent MVP for **La Fórmula** (personal training + sports supplements). The agent is called **"Nico"** and uses a local web-based WhatsApp simulator before real WhatsApp API integration. Built with Python/FastAPI, uses OpenRouter (DeepSeek model) for LLM calls, and ChromaDB for RAG-based knowledge retrieval.

## Commands

### Run with Docker (recommended)
```bash
docker compose up --build
# App at http://localhost:7070
```

### Run locally
```bash
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 7070
```

Requires `.env` with `OPENROUTER_API_KEY` and `CLIENT_CONFIG_PATH=config/config.yaml` (see `.env.example`).

### No test framework configured yet

## Architecture

### Module Responsibilities

- **`app/main.py`** — FastAPI server, all HTTP routes, session orchestration. Holds global state: agent instance, knowledge base, and in-memory sessions dict.
- **`app/agent.py`** — `WhatsAppAgent` class. Constructs message payloads (system prompt + RAG context + history) and calls OpenRouter API asynchronously via httpx.
- **`app/knowledge.py`** — `KnowledgeBase` class wrapping ChromaDB. Handles document ingestion (PDF via PyMuPDF, text, WhatsApp chat exports), chunking, semantic search (top-5 results), and document management.
- **`app/models.py`** — Pydantic models: `ChatMessage`, `ChatSession`, `SendMessageRequest`, `NewSessionRequest`.
- **`app/config.py`** — Loads YAML config from `CLIENT_CONFIG_PATH`, auto-injects product catalog into the system prompt.
- **`config/config.yaml`** — All business-specific config: business info, agent personality/system prompt, model settings, discount rules.

### Request Flow

1. User sends message via web UI → `POST /api/chat` with `session_id` + `message`
2. Message appended to in-memory session history
3. Knowledge base queried for top-5 semantically relevant chunks
4. Agent builds message array: system prompt → KB context → conversation history → new message
5. Async POST to OpenRouter API (`deepseek/deepseek-chat`)
6. Response saved to session and returned to frontend

### Frontend

Two vanilla HTML/JS/CSS pages served as static files (no build step):
- **`app/static/index.html`** — WhatsApp-style chat UI with sidebar for session management
- **`app/static/admin.html`** — Knowledge base admin panel (upload PDFs, add text/notes, import WhatsApp exports, manage documents)

### Data Persistence

- **Sessions**: In-memory dict (lost on restart — intentional for MVP)
- **Knowledge base**: ChromaDB persisted to `data/chroma/` (survives restarts via Docker volume)

### Docker

- `docker-compose.yml` mounts three volumes for development: `app/` (code hot-reload), `config/` (runtime config changes), `data/chroma/` (vector DB persistence)
- Port 7070. `PORT` env var supported for cloud platforms (Railway, Render).

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `OPENROUTER_API_KEY` | Yes | OpenRouter API key for LLM access |
| `CLIENT_CONFIG_PATH` | Yes | Path to client YAML config (default: `config/config.yaml`) |
| `PORT` | No | Server port (default: `7070`) |

## Key Design Decisions

- **Configuration-driven**: Business logic, agent personality, and product catalog all live in `config/config.yaml` — same codebase can serve different clients.
- **RAG over stuffing**: Product knowledge is indexed in ChromaDB rather than always included in the prompt, reducing token cost per message.
- **All async**: FastAPI + httpx for non-blocking I/O throughout.
- **Spanish (Argentine dialect)**: The agent speaks in Argentine Spanish with natural speech patterns — maintain this in any prompt changes.
