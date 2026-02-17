from pydantic import BaseModel
from datetime import datetime


class ChatMessage(BaseModel):
    role: str  # "user" or "assistant"
    content: str
    timestamp: str = ""
    source: str = ""  # "bot" | "human" | "system" | "" (user msgs)

    def model_post_init(self, __context):
        if not self.timestamp:
            self.timestamp = datetime.now().strftime("%H:%M")


class ChatSession(BaseModel):
    id: str
    phone_number: str
    messages: list[ChatMessage] = []
    prompt_context: str = ""
    created_at: str = ""
    mode: str = "bot"  # "bot" | "handoff_pending" | "human"
    handoff_reason: str = ""
    handoff_at: str = ""
    is_simulation: bool = False
    last_activity: str = ""

    def model_post_init(self, __context):
        now = datetime.now().isoformat()
        if not self.created_at:
            self.created_at = now
        if not self.last_activity:
            self.last_activity = now


class SendMessageRequest(BaseModel):
    session_id: str
    message: str
    prompt_context: str | None = None  # optional; if set, updates session and is used for this request
    system_prompt_override: str | None = None  # optional; if set, overrides agent system prompt for this turn request


class NewSessionRequest(BaseModel):
    phone_number: str = ""
    is_simulation: bool = False


class HandoffRequest(BaseModel):
    mode: str  # "handoff_pending" | "human" | "bot"
    reason: str = ""


class OperatorReplyRequest(BaseModel):
    message: str
