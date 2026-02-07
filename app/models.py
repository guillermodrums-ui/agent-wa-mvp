from pydantic import BaseModel
from datetime import datetime


class ChatMessage(BaseModel):
    role: str  # "user" or "assistant"
    content: str
    timestamp: str = ""

    def model_post_init(self, __context):
        if not self.timestamp:
            self.timestamp = datetime.now().strftime("%H:%M")


class ChatSession(BaseModel):
    id: str
    phone_number: str
    messages: list[ChatMessage] = []
    prompt_context: str = ""
    created_at: str = ""

    def model_post_init(self, __context):
        if not self.created_at:
            self.created_at = datetime.now().isoformat()


class SendMessageRequest(BaseModel):
    session_id: str
    message: str
    prompt_context: str | None = None  # optional; if set, updates session and is used for this request


class NewSessionRequest(BaseModel):
    phone_number: str = ""
