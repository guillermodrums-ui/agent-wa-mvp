import asyncio
import logging
import os
import uuid
import random

from fastapi import FastAPI, HTTPException, Request, UploadFile, File, Form
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.config import load_client_config, OPENROUTER_API_KEY
from app.models import ChatMessage, ChatSession, SendMessageRequest, NewSessionRequest
from app.agent import WhatsAppAgent
from app.knowledge import KnowledgeBase
from app.sessions import SessionStore
from app.channels import ChannelManager, ChannelType, OutgoingMessage, WhatsAppChannel

logger = logging.getLogger(__name__)

# Load config and create agent
client_config = load_client_config()
agent = WhatsAppAgent(api_key=OPENROUTER_API_KEY, config=client_config)

# Knowledge base (ChromaDB with disk persistence)
kb = KnowledgeBase(persist_dir="data/chroma")

# Session store (SQLite)
session_store = SessionStore("data/sessions.db")

# Default prompt context for new sessions (in-memory, lost on restart)
default_prompt_context: str = ""

# Channel manager
channel_manager = ChannelManager()

# Evolution API config
EVOLUTION_API_URL = os.getenv("EVOLUTION_API_URL", "")
EVOLUTION_API_KEY = os.getenv("EVOLUTION_API_KEY", "")
EVOLUTION_INSTANCE_NAME = os.getenv("EVOLUTION_INSTANCE_NAME", "laformula")

if EVOLUTION_API_URL and EVOLUTION_API_KEY:
    wa_channel = WhatsAppChannel(
        api_url=EVOLUTION_API_URL,
        api_key=EVOLUTION_API_KEY,
        instance_name=EVOLUTION_INSTANCE_NAME,
    )
    channel_manager.register(wa_channel)

app = FastAPI(title="La Fórmula - WhatsApp Agent MVP")


# --- Lifecycle ---

@app.on_event("startup")
async def startup():
    await session_store.init()
    # Periodic cleanup of webhook deduplication records
    asyncio.create_task(_webhook_cleanup_loop())


async def _webhook_cleanup_loop():
    while True:
        await asyncio.sleep(300)  # every 5 minutes
        try:
            await session_store.cleanup_old_webhooks()
        except Exception as e:
            logger.error("Webhook cleanup error: %s", e)


@app.on_event("shutdown")
async def shutdown():
    await session_store.close()


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
        channel="simulator",
    )
    await session_store.put(session)
    return {"id": session_id, "phone_number": phone}


@app.get("/api/sessions")
async def list_sessions():
    return await session_store.get_all()


@app.get("/api/sessions/{session_id}")
async def get_session(session_id: str):
    session = await session_store.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


@app.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str):
    deleted = await session_store.delete(session_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"ok": True}


class UpdatePromptContextRequest(BaseModel):
    prompt_context: str


@app.put("/api/sessions/{session_id}/prompt-context")
async def update_session_prompt_context(session_id: str, req: UpdatePromptContextRequest):
    session = await session_store.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    await session_store.update_prompt_context(session_id, req.prompt_context or "")
    return {"ok": True, "prompt_context": req.prompt_context or ""}


# --- Config: default prompt context (for new sessions) ---

@app.get("/api/config/prompt-context")
async def get_default_prompt_context():
    return {"prompt_context": default_prompt_context}


@app.put("/api/config/prompt-context")
async def update_default_prompt_context(req: UpdatePromptContextRequest):
    global default_prompt_context
    default_prompt_context = req.prompt_context or ""
    return {"ok": True, "prompt_context": default_prompt_context}


# --- Chat (with RAG) — simulator ---

@app.post("/api/chat")
async def send_message(req: SendMessageRequest):
    session = await session_store.get(req.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Add user message
    await session_store.add_message(req.session_id, "user", req.message)

    # Update session prompt_context if provided in request
    if req.prompt_context is not None:
        await session_store.update_prompt_context(req.session_id, req.prompt_context)
        session.prompt_context = req.prompt_context

    # Get agent response with RAG
    debug_info = None
    try:
        result = await agent.chat(
            session.messages,  # history (without the new message — it's already added to DB)
            req.message,
            knowledge_base=kb,
            prompt_context=session.prompt_context or "",
        )
        reply = result["reply"]
        debug_info = result.get("debug")
    except Exception as e:
        reply = f"[Error del agente: {e}]"

    # Add assistant message
    assistant_msg = await session_store.add_message(req.session_id, "assistant", reply)

    out = {"reply": reply, "timestamp": assistant_msg.timestamp}
    if debug_info is not None:
        out["debug"] = debug_info
    return out


# --- Channels ---

@app.get("/api/channels/status")
async def get_all_channel_statuses():
    return await channel_manager.get_all_statuses()


@app.get("/api/channels/whatsapp/status")
async def get_whatsapp_status():
    wa = channel_manager.get(ChannelType.WHATSAPP)
    if not wa:
        return {"connected": False, "state": "not_configured"}
    return await wa.get_status()


@app.post("/api/channels/whatsapp/connect")
async def connect_whatsapp():
    wa = channel_manager.get(ChannelType.WHATSAPP)
    if not wa:
        raise HTTPException(status_code=400, detail="WhatsApp channel not configured. Set EVOLUTION_API_URL and EVOLUTION_API_KEY.")
    return await wa.connect()


@app.post("/api/channels/whatsapp/disconnect")
async def disconnect_whatsapp():
    wa = channel_manager.get(ChannelType.WHATSAPP)
    if not wa:
        raise HTTPException(status_code=400, detail="WhatsApp channel not configured")
    ok = await wa.disconnect()
    return {"ok": ok}


# --- Webhook (Evolution API) ---

@app.post("/api/webhooks/evolution")
async def evolution_webhook(request: Request):
    """Receive webhook events from Evolution API. Always returns 200."""
    try:
        payload = await request.json()
    except Exception:
        return {"ok": True}

    event = payload.get("event", "")
    logger.info("Webhook event: %s", event)

    # Connection updates — just log
    if event == "connection.update":
        state = payload.get("data", {}).get("state", "unknown")
        logger.info("WhatsApp connection update: %s", state)
        return {"ok": True}

    # Parse incoming message
    wa = channel_manager.get(ChannelType.WHATSAPP)
    if not wa:
        return {"ok": True}

    incoming = wa.parse_webhook(payload)
    if not incoming:
        return {"ok": True}

    # Deduplication
    if incoming.message_id and await session_store.is_webhook_duplicate(incoming.message_id):
        logger.info("Duplicate webhook message_id=%s, skipping", incoming.message_id)
        return {"ok": True}

    if incoming.message_id:
        await session_store.mark_webhook_processed(incoming.message_id)

    # Get or create session for this phone+channel
    session = await session_store.get_or_create_by_phone(
        incoming.phone_number, "whatsapp", incoming.sender_name
    )

    # Save user message
    await session_store.add_message(session.id, "user", incoming.text)

    # Generate agent reply with timeout
    try:
        result = await asyncio.wait_for(
            agent.chat(
                session.messages,
                incoming.text,
                knowledge_base=kb,
                prompt_context=session.prompt_context or "",
            ),
            timeout=25,
        )
        reply = result["reply"]
    except asyncio.TimeoutError:
        reply = "Disculpá, tardé demasiado en responder. ¿Podés repetir tu consulta?"
        logger.error("Agent timeout for phone=%s", incoming.phone_number)
    except Exception as e:
        reply = "Perdón, tuve un error procesando tu mensaje. Intentá de nuevo en un momento."
        logger.error("Agent error for phone=%s: %s", incoming.phone_number, e)

    # Save assistant message
    await session_store.add_message(session.id, "assistant", reply)

    # Send reply via WhatsApp
    await wa.send_message(OutgoingMessage(
        channel=ChannelType.WHATSAPP,
        phone_number=incoming.phone_number,
        text=reply,
    ))

    return {"ok": True}


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
