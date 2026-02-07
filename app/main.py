import uuid
import random

from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.config import load_client_config, OPENROUTER_API_KEY
from app.models import ChatMessage, ChatSession, SendMessageRequest, NewSessionRequest
from app.agent import WhatsAppAgent
from app.knowledge import KnowledgeBase

# Load config and create agent
client_config = load_client_config()
agent = WhatsAppAgent(api_key=OPENROUTER_API_KEY, config=client_config)

# Knowledge base (ChromaDB with disk persistence)
kb = KnowledgeBase(persist_dir="data/chroma")

# In-memory session storage
sessions: dict[str, ChatSession] = {}

app = FastAPI(title="La Fórmula - WhatsApp Agent MVP")

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
    session = ChatSession(id=session_id, phone_number=phone)
    sessions[session_id] = session
    return {"id": session_id, "phone_number": phone}


@app.get("/api/sessions")
async def list_sessions():
    return [
        {
            "id": s.id,
            "phone_number": s.phone_number,
            "last_message": s.messages[-1].content[:50] if s.messages else "",
            "message_count": len(s.messages),
        }
        for s in sessions.values()
    ]


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


# --- Chat (with RAG) ---

@app.post("/api/chat")
async def send_message(req: SendMessageRequest):
    session = sessions.get(req.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Add user message
    user_msg = ChatMessage(role="user", content=req.message)
    session.messages.append(user_msg)

    # Get agent response with RAG
    try:
        reply = await agent.chat(session.messages[:-1], req.message, knowledge_base=kb)
    except Exception as e:
        reply = f"[Error del agente: {e}]"

    # Add assistant message
    assistant_msg = ChatMessage(role="assistant", content=reply)
    session.messages.append(assistant_msg)

    return {"reply": reply, "timestamp": assistant_msg.timestamp}


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
