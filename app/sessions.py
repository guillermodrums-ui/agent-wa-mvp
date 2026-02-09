import os
import time

import aiosqlite

from app.models import ChatMessage, ChatSession


class SessionStore:
    """SQLite-backed session persistence. Replaces in-memory dict."""

    def __init__(self, db_path: str = "data/sessions.db"):
        self.db_path = db_path
        self._db: aiosqlite.Connection | None = None

    async def init(self):
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._db = await aiosqlite.connect(self.db_path)
        self._db.row_factory = aiosqlite.Row
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.executescript("""
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                phone_number TEXT NOT NULL,
                channel TEXT NOT NULL DEFAULT 'simulator',
                sender_name TEXT NOT NULL DEFAULT '',
                prompt_context TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                timestamp TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id);
            CREATE INDEX IF NOT EXISTS idx_sessions_phone_channel ON sessions(phone_number, channel);
            CREATE TABLE IF NOT EXISTS processed_webhooks (
                message_id TEXT PRIMARY KEY,
                created_at REAL NOT NULL
            );
        """)
        await self._db.commit()

    async def close(self):
        if self._db:
            await self._db.close()

    async def get(self, session_id: str) -> ChatSession | None:
        row = await self._db.execute_fetchall(
            "SELECT * FROM sessions WHERE id = ?", (session_id,)
        )
        if not row:
            return None
        s = row[0]
        messages = await self._load_messages(session_id)
        return ChatSession(
            id=s["id"],
            phone_number=s["phone_number"],
            messages=messages,
            prompt_context=s["prompt_context"],
            created_at=s["created_at"],
            channel=s["channel"],
            sender_name=s["sender_name"],
        )

    async def put(self, session: ChatSession):
        await self._db.execute(
            """INSERT INTO sessions (id, phone_number, channel, sender_name, prompt_context, created_at)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                 phone_number=excluded.phone_number,
                 channel=excluded.channel,
                 sender_name=excluded.sender_name,
                 prompt_context=excluded.prompt_context""",
            (session.id, session.phone_number, session.channel,
             session.sender_name, session.prompt_context, session.created_at),
        )
        await self._db.commit()

    async def delete(self, session_id: str) -> bool:
        await self._db.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
        cursor = await self._db.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        await self._db.commit()
        return cursor.rowcount > 0

    async def get_all(self) -> list[dict]:
        rows = await self._db.execute_fetchall(
            "SELECT id, phone_number, channel, sender_name FROM sessions ORDER BY created_at DESC"
        )
        result = []
        for s in rows:
            last_msg = await self._db.execute_fetchall(
                "SELECT content FROM messages WHERE session_id = ? ORDER BY id DESC LIMIT 1",
                (s["id"],),
            )
            msg_count = await self._db.execute_fetchall(
                "SELECT COUNT(*) as cnt FROM messages WHERE session_id = ?",
                (s["id"],),
            )
            result.append({
                "id": s["id"],
                "phone_number": s["phone_number"],
                "channel": s["channel"],
                "sender_name": s["sender_name"],
                "last_message": last_msg[0]["content"][:50] if last_msg else "",
                "message_count": msg_count[0]["cnt"],
            })
        return result

    async def get_or_create_by_phone(
        self, phone: str, channel: str, sender_name: str
    ) -> ChatSession:
        rows = await self._db.execute_fetchall(
            "SELECT id FROM sessions WHERE phone_number = ? AND channel = ?",
            (phone, channel),
        )
        if rows:
            return await self.get(rows[0]["id"])

        import uuid
        from datetime import datetime

        session = ChatSession(
            id=str(uuid.uuid4())[:8],
            phone_number=phone,
            channel=channel,
            sender_name=sender_name,
            created_at=datetime.now().isoformat(),
        )
        await self.put(session)
        return session

    async def add_message(self, session_id: str, role: str, content: str) -> ChatMessage:
        msg = ChatMessage(role=role, content=content)
        await self._db.execute(
            "INSERT INTO messages (session_id, role, content, timestamp) VALUES (?, ?, ?, ?)",
            (session_id, msg.role, msg.content, msg.timestamp),
        )
        await self._db.commit()
        return msg

    async def update_prompt_context(self, session_id: str, prompt_context: str):
        await self._db.execute(
            "UPDATE sessions SET prompt_context = ? WHERE id = ?",
            (prompt_context, session_id),
        )
        await self._db.commit()

    # --- Webhook deduplication ---

    async def is_webhook_duplicate(self, message_id: str) -> bool:
        rows = await self._db.execute_fetchall(
            "SELECT 1 FROM processed_webhooks WHERE message_id = ?", (message_id,)
        )
        return len(rows) > 0

    async def mark_webhook_processed(self, message_id: str):
        await self._db.execute(
            "INSERT OR IGNORE INTO processed_webhooks (message_id, created_at) VALUES (?, ?)",
            (message_id, time.time()),
        )
        await self._db.commit()

    async def cleanup_old_webhooks(self, max_age_seconds: int = 600):
        cutoff = time.time() - max_age_seconds
        await self._db.execute(
            "DELETE FROM processed_webhooks WHERE created_at < ?", (cutoff,)
        )
        await self._db.commit()

    # --- Internal ---

    async def _load_messages(self, session_id: str) -> list[ChatMessage]:
        rows = await self._db.execute_fetchall(
            "SELECT role, content, timestamp FROM messages WHERE session_id = ? ORDER BY id",
            (session_id,),
        )
        return [ChatMessage(role=r["role"], content=r["content"], timestamp=r["timestamp"]) for r in rows]
