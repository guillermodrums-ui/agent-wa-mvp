import uuid
import random
import logging
import os
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.config import load_client_config, OPENROUTER_API_KEY
from app.models import (
    ChatMessage, ChatSession, SendMessageRequest, NewSessionRequest,
    HandoffRequest, OperatorReplyRequest,
)
from app.agent import WhatsAppAgent
from app.knowledge import KnowledgeBase
from app.config_store import ConfigStore
from app.evaluator import Evaluator
from app.introspector import Introspector
from app import images as image_registry
from app.image_processor import process_reply

# --- Logging ---
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("app.main")

# Load config and create agent
client_config = load_client_config()
agent = WhatsAppAgent(api_key=OPENROUTER_API_KEY, config=client_config)

# Persistent config store (data/runtime_config.yaml)
config_store = ConfigStore(runtime_path="data/runtime_config.yaml", defaults=client_config)
runtime = config_store.load()

# Apply persisted runtime config to agent on startup
agent.system_prompt = runtime.get("system_prompt", agent.system_prompt)
agent.update_params(
    model=runtime.get("model", agent.model),
    temperature=runtime.get("temperature", agent.temperature),
    max_tokens=runtime.get("max_tokens", agent.max_tokens),
)

# Knowledge base (ChromaDB with disk persistence)
kb = KnowledgeBase(persist_dir="data/chroma")

# In-memory session storage
sessions: dict[str, ChatSession] = {}

# Default prompt context — loaded from persisted config
default_prompt_context: str = runtime.get("prompt_context_default", "")

# Session timeout — clears conversation context after inactivity
session_timeout_minutes: int = runtime.get("session_timeout_minutes", 120)

# Fixed greeting — bypasses LLM for first message in a session
greeting_config = {
    "enabled": runtime.get("greeting_enabled", True),
    "text": runtime.get("greeting_text", ""),
    "patterns": runtime.get("greeting_patterns", []),
}

app = FastAPI(title="La Fórmula - WhatsApp Agent MVP")

# Serve product images (must be before /static)
os.makedirs("data/images", exist_ok=True)
app.mount("/images", StaticFiles(directory="data/images"), name="images")

# Serve static files
app.mount("/static", StaticFiles(directory="app/static"), name="static")


# --- Pages ---

@app.get("/")
async def root():
    return FileResponse("app/static/index.html")


@app.get("/admin")
async def admin_page():
    return FileResponse("app/static/admin.html")


# --- Config ---

@app.get("/api/config")
async def get_config():
    return {
        "business_name": client_config["business"]["name"],
        "agent_name": client_config["agent"]["name"],
        "description": client_config["business"]["description"],
    }


# --- Prompt (persisted) ---

@app.get("/api/config/prompt")
async def get_prompt():
    return {"system_prompt": agent.system_prompt}


class UpdatePromptRequest(BaseModel):
    system_prompt: str


@app.post("/api/config/prompt")
async def update_prompt(req: UpdatePromptRequest):
    if not req.system_prompt.strip():
        raise HTTPException(status_code=400, detail="Prompt cannot be empty")
    agent.system_prompt = req.system_prompt
    config_store.save_prompt(req.system_prompt)
    return {"ok": True}


# --- Model Parameters (persisted) ---

class UpdateModelParamsRequest(BaseModel):
    model: str
    temperature: float
    max_tokens: int


@app.get("/api/config/model-params")
async def get_model_params():
    return {
        "model": agent.model,
        "temperature": agent.temperature,
        "max_tokens": agent.max_tokens,
    }


@app.put("/api/config/model-params")
async def update_model_params(req: UpdateModelParamsRequest):
    if not req.model.strip():
        raise HTTPException(status_code=400, detail="Model cannot be empty")
    if not (0.0 <= req.temperature <= 1.5):
        raise HTTPException(status_code=400, detail="Temperature must be 0.0–1.5")
    if not (50 <= req.max_tokens <= 4000):
        raise HTTPException(status_code=400, detail="max_tokens must be 50–4000")
    agent.update_params(req.model, req.temperature, req.max_tokens)
    config_store.save_model_params(req.model, req.temperature, req.max_tokens)
    return {"ok": True}


# --- Prompt Versions ---

@app.get("/api/config/prompt-versions")
async def get_prompt_versions():
    return config_store.get_prompt_versions()


@app.post("/api/config/prompt-versions/{index}/restore")
async def restore_prompt_version(index: int):
    try:
        text = config_store.restore_version(index)
    except IndexError as e:
        raise HTTPException(status_code=404, detail=str(e))
    agent.system_prompt = text
    return {"ok": True, "system_prompt": text}


# --- Sessions ---

@app.post("/api/sessions")
async def create_session(req: NewSessionRequest = NewSessionRequest()):
    session_id = str(uuid.uuid4())[:8]
    phone = req.phone_number or f"+54 9 11 {random.randint(1000, 9999)}-{random.randint(1000, 9999)}"
    session = ChatSession(
        id=session_id,
        phone_number=phone,
        prompt_context=default_prompt_context,
        is_simulation=req.is_simulation,
    )
    sessions[session_id] = session
    return {"id": session_id, "phone_number": phone}


@app.get("/api/sessions")
async def list_sessions(mode: str = Query(None), is_simulation: bool = Query(None)):
    result = []
    for s in sessions.values():
        if mode and s.mode != mode:
            continue
        if is_simulation is not None and s.is_simulation != is_simulation:
            continue
        result.append({
            "id": s.id,
            "phone_number": s.phone_number,
            "last_message": s.messages[-1].content[:50] if s.messages else "",
            "message_count": len(s.messages),
            "mode": s.mode,
            "handoff_reason": s.handoff_reason,
            "handoff_at": s.handoff_at,
        })
    return result


@app.get("/api/sessions/{session_id}")
async def get_session(session_id: str):
    session = sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


@app.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str):
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    del sessions[session_id]
    return {"ok": True}


class UpdatePromptContextRequest(BaseModel):
    prompt_context: str


@app.put("/api/sessions/{session_id}/prompt-context")
async def update_session_prompt_context(session_id: str, req: UpdatePromptContextRequest):
    session = sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    session.prompt_context = req.prompt_context or ""
    return {"ok": True, "prompt_context": session.prompt_context}


# --- Config: default prompt context (persisted) ---

@app.get("/api/config/prompt-context")
async def get_default_prompt_context():
    return {"prompt_context": default_prompt_context}


@app.put("/api/config/prompt-context")
async def update_default_prompt_context(req: UpdatePromptContextRequest):
    global default_prompt_context
    default_prompt_context = req.prompt_context or ""
    config_store.save_default_context(default_prompt_context)
    return {"ok": True, "prompt_context": default_prompt_context}


# --- Session Timeout (persisted) ---

@app.get("/api/config/session-timeout")
async def get_session_timeout():
    return {"timeout_minutes": session_timeout_minutes}


class UpdateSessionTimeoutRequest(BaseModel):
    timeout_minutes: int


@app.put("/api/config/session-timeout")
async def update_session_timeout(req: UpdateSessionTimeoutRequest):
    global session_timeout_minutes
    if req.timeout_minutes < 1:
        raise HTTPException(status_code=400, detail="Timeout must be at least 1 minute")
    session_timeout_minutes = req.timeout_minutes
    config_store.save_session_timeout(req.timeout_minutes)
    return {"ok": True}


# --- Fixed Greeting (persisted) ---

@app.get("/api/config/greeting")
async def get_greeting():
    return greeting_config


class UpdateGreetingRequest(BaseModel):
    enabled: bool
    text: str
    patterns: list[str] = []


@app.put("/api/config/greeting")
async def update_greeting(req: UpdateGreetingRequest):
    greeting_config["enabled"] = req.enabled
    greeting_config["text"] = req.text
    greeting_config["patterns"] = req.patterns
    config_store.save_greeting(req.enabled, req.text, req.patterns)
    return {"ok": True}


# --- Chat (with RAG) ---

@app.post("/api/chat")
async def send_message(req: SendMessageRequest):
    session = sessions.get(req.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Session timeout — clear old context if inactive too long
    if session.messages:
        try:
            last = datetime.fromisoformat(session.last_activity)
            elapsed = (datetime.now() - last).total_seconds() / 60
            if elapsed >= session_timeout_minutes:
                session.messages.clear()
        except (ValueError, TypeError):
            pass

    # Add user message
    user_msg = ChatMessage(role="user", content=req.message)
    session.messages.append(user_msg)
    logger.debug("chat session=%s mode=%s message=%r", req.session_id, session.mode, req.message[:100])
    session.last_activity = datetime.now().isoformat()

    # Update session prompt_context if provided in request
    if req.prompt_context is not None:
        session.prompt_context = req.prompt_context

    # If session is in handoff/human mode, save message but don't call LLM
    if session.mode in ("handoff_pending", "human"):
        logger.debug("chat session=%s skipped (mode=%s)", req.session_id, session.mode)
        return {"reply": None, "mode": session.mode, "handoff": True}

    # Fixed greeting bypass — return exact text without LLM
    if greeting_config["enabled"] and greeting_config["text"].strip():
        is_first_message = len(session.messages) <= 1
        if is_first_message:
            patterns = greeting_config["patterns"]
            msg_lower = req.message.strip().lower()
            if not patterns or any(p.lower() in msg_lower for p in patterns):
                reply = greeting_config["text"]
                assistant_msg = ChatMessage(role="assistant", content=reply)
                session.messages.append(assistant_msg)
                return {"reply": reply, "timestamp": assistant_msg.timestamp}

    # Get agent response with RAG
    debug_info = None
    try:
        result = await agent.chat(
            session.messages[:-1],
            req.message,
            knowledge_base=kb,
            prompt_context=getattr(session, "prompt_context", "") or "",
            system_prompt_override=req.system_prompt_override,
        )
        reply = result["reply"]
        debug_info = result.get("debug")
    except Exception as e:
        reply = f"[Error del agente: {e}]"

    # Post-process image markers
    processed = process_reply(reply)
    clean_reply = processed["text"]

    # Detect [HANDOFF] tag anywhere in reply
    # The LLM may place it at the start, middle, or end.
    # Everything after [HANDOFF] is an internal note to the operator — strip it from the client reply.
    handoff = False
    handoff_idx = clean_reply.find("[HANDOFF]")
    if handoff_idx != -1:
        # Keep only the client-facing part (before the tag)
        client_part = clean_reply[:handoff_idx].strip()
        # If there's nothing before the tag, use whatever comes after it
        if not client_part:
            client_part = clean_reply[handoff_idx + len("[HANDOFF]"):].strip()
        clean_reply = client_part
        session.mode = "handoff_pending"
        session.handoff_reason = "Derivado por Nico"
        session.handoff_at = datetime.now().isoformat()
        handoff = True
        logger.info("handoff triggered session=%s reason='Derivado por Nico'", req.session_id)

    # Add assistant message (clean text, no markers)
    assistant_msg = ChatMessage(role="assistant", content=clean_reply, source="bot")
    session.messages.append(assistant_msg)

    out = {"reply": clean_reply, "timestamp": assistant_msg.timestamp, "mode": session.mode, "handoff": handoff}
    if processed["images"]:
        out["images"] = processed["images"]
    if debug_info is not None:
        out["debug"] = debug_info
    return out


# --- Handoff ---

@app.post("/api/sessions/{session_id}/handoff")
async def set_handoff(session_id: str, req: HandoffRequest):
    session = sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if req.mode not in ("handoff_pending", "human", "bot"):
        raise HTTPException(status_code=400, detail="Invalid mode")

    session.mode = req.mode

    if req.mode == "handoff_pending":
        session.handoff_reason = req.reason or "Derivacion manual"
        session.handoff_at = datetime.now().isoformat()
        sys_msg = ChatMessage(role="assistant", content="[Sistema] Sesion derivada a un operador.", source="system")
        session.messages.append(sys_msg)
    elif req.mode == "bot":
        session.handoff_reason = ""
        session.handoff_at = ""
        sys_msg = ChatMessage(role="assistant", content="[Sistema] Nico retomo la conversacion.", source="system")
        session.messages.append(sys_msg)

    return {"ok": True, "mode": session.mode}


@app.post("/api/sessions/{session_id}/reply")
async def operator_reply(session_id: str, req: OperatorReplyRequest):
    session = sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.mode not in ("handoff_pending", "human"):
        raise HTTPException(status_code=400, detail="Session is not in handoff mode")

    if session.mode == "handoff_pending":
        session.mode = "human"

    msg = ChatMessage(role="assistant", content=req.message, source="human")
    session.messages.append(msg)
    return {"ok": True, "timestamp": msg.timestamp, "mode": session.mode}


@app.get("/api/handoffs/pending")
async def pending_handoffs():
    pending = [
        {
            "id": s.id,
            "phone_number": s.phone_number,
            "handoff_reason": s.handoff_reason,
            "handoff_at": s.handoff_at,
        }
        for s in sessions.values()
        if s.mode in ("handoff_pending", "human")
    ]
    return {"count": len(pending), "sessions": pending}


# --- Knowledge Base ---

@app.post("/api/knowledge/upload")
async def upload_file(file: UploadFile = File(...)):
    content = await file.read()
    filename = file.filename or "documento"

    if filename.lower().endswith(".pdf"):
        result = kb.add_pdf(content, filename)
    else:
        text = content.decode("utf-8", errors="ignore")
        result = kb.add_text(text, filename, "note")

    return result


@app.post("/api/knowledge/text")
async def add_text(title: str = Form(...), text: str = Form(...), doc_type: str = Form("note")):
    if not text.strip():
        raise HTTPException(status_code=400, detail="Text cannot be empty")
    result = kb.add_text(text, title, doc_type)
    return result


@app.post("/api/knowledge/chat-export")
async def add_chat_export(title: str = Form(...), text: str = Form(...)):
    if not text.strip():
        raise HTTPException(status_code=400, detail="Text cannot be empty")
    result = kb.add_chat_export(text, title)
    return result


@app.get("/api/knowledge/documents")
async def list_documents():
    return kb.list_documents()


@app.delete("/api/knowledge/documents/{doc_id}")
async def delete_document(doc_id: str):
    deleted = kb.delete_document(doc_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Document not found")
    return {"ok": True}


@app.put("/api/knowledge/documents/{doc_id}/metadata")
async def update_document_metadata(doc_id: str, req: dict):
    category = req.get("category")
    priority = req.get("priority")
    updated = kb.update_document_metadata(doc_id, category=category, priority=priority)
    if not updated:
        raise HTTPException(status_code=404, detail="Document not found")
    return {"ok": True}


# --- Product Images ---

@app.post("/api/images/upload")
async def upload_image(
    file: UploadFile = File(...),
    title: str = Form(...),
    description: str = Form(""),
    tags: str = Form(""),
):
    if not title.strip():
        raise HTTPException(status_code=400, detail="Title is required")

    file_bytes = await file.read()
    original_filename = file.filename or "image.jpg"
    entry = image_registry.add_image(file_bytes, original_filename, title.strip(), description.strip(), tags.strip())

    # Index description in RAG so the agent knows the image exists
    rag_text = (
        f"IMAGEN DISPONIBLE: {title.strip()}\n"
        f"Descripcion: {description.strip()}\n"
        f"Tags: {tags.strip()}\n"
        f"Para mostrar esta imagen en la respuesta, escribi: [IMAGEN: {title.strip()}]"
    )
    rag_result = kb.add_text(rag_text, f"img:{title.strip()}", "image")
    entry["rag_doc_id"] = rag_result["id"]

    return entry


@app.get("/api/images")
async def list_images():
    return image_registry.list_images()


@app.delete("/api/images/{image_id}")
async def delete_image(image_id: str):
    entry = image_registry.delete_image(image_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Image not found")

    # Remove from RAG: find doc with source "img:{title}"
    rag_source = f"img:{entry['title']}"
    docs = kb.list_documents()
    for doc in docs:
        if doc["filename"] == rag_source:
            kb.delete_document(doc["id"])
            break

    return {"ok": True}


# --- Training Materials ---

TRAINING_DIR = Path("training")
SUPPORTED_EXTENSIONS = {".txt", ".pdf", ".yaml", ".yml"}


@app.get("/api/training/materials")
async def list_training_materials():
    if not TRAINING_DIR.exists():
        return []

    indexed_sources = {d["filename"] for d in kb.list_documents()}
    files = []
    exclude_dirs = {"evaluaciones"}
    for path in sorted(TRAINING_DIR.rglob("*")):
        if not path.is_file():
            continue
        if any(part in exclude_dirs for part in path.relative_to(TRAINING_DIR).parts):
            continue
        if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue
        rel = str(path.relative_to(TRAINING_DIR))
        file_type = "chat" if ".chat." in path.name.lower() else path.suffix.lstrip(".")
        files.append({
            "path": rel,
            "type": file_type,
            "imported": rel in indexed_sources,
        })
    return files


class ImportTrainingRequest(BaseModel):
    paths: list[str]


@app.post("/api/training/import")
async def import_training(req: ImportTrainingRequest):
    imported = 0
    for rel_path in req.paths:
        full = TRAINING_DIR / rel_path
        if not full.exists() or not full.is_file():
            continue
        # Prevent path traversal
        try:
            full.resolve().relative_to(TRAINING_DIR.resolve())
        except ValueError:
            continue

        suffix = full.suffix.lower()
        if suffix == ".pdf":
            content = full.read_bytes()
            kb.add_pdf(content, rel_path)
        elif suffix in (".txt",):
            text = full.read_text(encoding="utf-8", errors="ignore")
            if ".chat." in full.name.lower():
                kb.add_chat_export(text, rel_path)
            else:
                kb.add_text(text, rel_path, "training")
        else:
            continue
        imported += 1
    return {"imported": imported}


# --- Evaluations ---

evaluator = Evaluator(
    agent=agent,
    knowledge_base=kb,
    test_cases_path="training/evaluaciones/test-cases.yaml",
)

introspector = Introspector(agent=agent, knowledge_base=kb)


@app.get("/api/evaluations/test-cases")
async def list_test_cases():
    return evaluator.load_test_cases()


class AddTestCaseRequest(BaseModel):
    name: str
    user_message: str
    expected_behaviors: list[str]
    tags: list[str] = []


@app.post("/api/evaluations/test-cases")
async def add_test_case(req: AddTestCaseRequest):
    tc = evaluator.add_test_case(req.name, req.user_message, req.expected_behaviors, req.tags)
    return tc


class RunEvalRequest(BaseModel):
    use_llm_judge: bool = False


@app.post("/api/evaluations/run")
async def run_all_evaluations(req: RunEvalRequest):
    report = await evaluator.run_all(use_llm_judge=req.use_llm_judge)
    return report


@app.post("/api/evaluations/run/{test_id}")
async def run_single_evaluation(test_id: str, req: RunEvalRequest):
    cases = evaluator.load_test_cases()
    tc = next((c for c in cases if c["id"] == test_id), None)
    if not tc:
        raise HTTPException(status_code=404, detail="Test case not found")
    result = await evaluator.run_single(tc, use_llm_judge=req.use_llm_judge)
    return result


# --- Introspection ---

class IntrospectRequest(BaseModel):
    debug_snapshot: dict
    introspection_history: list[dict] = []
    question: str


@app.post("/api/introspect")
async def introspect(req: IntrospectRequest):
    result = await introspector.ask(req.debug_snapshot, req.introspection_history, req.question)
    return result
