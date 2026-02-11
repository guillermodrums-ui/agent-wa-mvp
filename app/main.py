import uuid
import random
import logging
import os
from datetime import datetime

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

# Knowledge base (ChromaDB with disk persistence)
kb = KnowledgeBase(persist_dir="data/chroma")

# In-memory session storage
sessions: dict[str, ChatSession] = {}

# Default prompt context for new sessions (in-memory, lost on restart)
default_prompt_context: str = ""

app = FastAPI(title="La Fórmula - WhatsApp Agent MVP")

# Serve static files
app.mount("/static", StaticFiles(directory="app/static"), name="static")


# --- Pages ---

@app.get("/")
async def root():
    return FileResponse("app/static/index.html")


# Admin functionality now integrated into main UI
# @app.get("/admin")
# async def admin_page():
#     return FileResponse("app/static/admin.html")


# --- Config ---

@app.get("/api/config")
async def get_config():
    return {
        "business_name": client_config["business"]["name"],
        "agent_name": client_config["agent"]["name"],
        "description": client_config["business"]["description"],
    }


# --- Prompt (in-memory) ---

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
    return {"ok": True}


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


# --- Config: default prompt context (for new sessions) ---

@app.get("/api/config/prompt-context")
async def get_default_prompt_context():
    return {"prompt_context": default_prompt_context}


@app.put("/api/config/prompt-context")
async def update_default_prompt_context(req: UpdatePromptContextRequest):
    global default_prompt_context
    default_prompt_context = req.prompt_context or ""
    return {"ok": True, "prompt_context": default_prompt_context}


# --- Chat (with RAG) ---

@app.post("/api/chat")
async def send_message(req: SendMessageRequest):
    session = sessions.get(req.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Add user message
    user_msg = ChatMessage(role="user", content=req.message)
    session.messages.append(user_msg)
    logger.debug("chat session=%s mode=%s message=%r", req.session_id, session.mode, req.message[:100])

    # Update session prompt_context if provided in request
    if req.prompt_context is not None:
        session.prompt_context = req.prompt_context

    # If session is in handoff/human mode, save message but don't call LLM
    if session.mode in ("handoff_pending", "human"):
        logger.debug("chat session=%s skipped (mode=%s)", req.session_id, session.mode)
        return {"reply": None, "mode": session.mode, "handoff": True}

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

    # Detect [HANDOFF] tag in reply
    handoff = False
    if reply.lstrip().startswith("[HANDOFF]"):
        reply = reply.lstrip().removeprefix("[HANDOFF]").strip()
        session.mode = "handoff_pending"
        session.handoff_reason = "Derivado por Nico"
        session.handoff_at = datetime.now().isoformat()
        handoff = True
        logger.info("handoff triggered session=%s reason='Derivado por Nico'", req.session_id)

    # Add assistant message
    assistant_msg = ChatMessage(role="assistant", content=reply, source="bot")
    session.messages.append(assistant_msg)

    out = {"reply": reply, "timestamp": assistant_msg.timestamp, "mode": session.mode, "handoff": handoff}
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
