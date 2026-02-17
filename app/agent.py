import time
import logging
import httpx
from app.models import ChatMessage

logger = logging.getLogger("app.agent")

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


class WhatsAppAgent:
    def __init__(self, api_key: str, config: dict):
        self.api_key = api_key
        self.agent_config = config["agent"]
        self.system_prompt = self.agent_config["system_prompt"]
        self.model = self.agent_config.get("model", "deepseek/deepseek-chat")
        self.temperature = self.agent_config.get("temperature", 0.7)
        self.max_tokens = self.agent_config.get("max_tokens", 500)

    def update_params(self, model: str, temperature: float, max_tokens: int) -> None:
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens

    async def chat(
        self,
        history: list[ChatMessage],
        user_message: str,
        knowledge_base=None,
        prompt_context: str = "",
        system_prompt_override: str | None = None,
    ) -> dict:
        system_content = system_prompt_override if system_prompt_override is not None else self.system_prompt
        if (prompt_context or "").strip():
            system_content = system_content.rstrip() + "\n\n--- CONTEXTO ADICIONAL ---\n" + prompt_context.strip()

        messages = [{"role": "system", "content": system_content}]

        rag_chunks = []
        rag_debug = []

        # RAG: inject relevant knowledge chunks
        if knowledge_base:
            result = knowledge_base.search_with_debug(user_message, n_results=5)
            rag_chunks = result["chunks"]
            rag_debug = result.get("debug", [])
            if rag_chunks:
                context = "\n\n".join(rag_chunks)
                messages.append({
                    "role": "system",
                    "content": f"CONTEXTO RELEVANTE DE LA BASE DE CONOCIMIENTO:\n{context}",
                })

        for msg in history:
            messages.append({"role": msg.role, "content": msg.content})

        messages.append({"role": "user", "content": user_message})

        request_body = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        logger.debug("OpenRouter request: model=%s messages=%d temp=%.1f max_tokens=%d",
                      self.model, len(messages), self.temperature, self.max_tokens)
        logger.debug("OpenRouter request body: %s", request_body)

        t_start = time.monotonic()
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                OPENROUTER_URL,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=request_body,
            )
            response.raise_for_status()
            data = response.json()
        t_end = time.monotonic()
        elapsed_ms = round((t_end - t_start) * 1000)

        reply_text = data["choices"][0]["message"]["content"]
        usage = data.get("usage", {})
        logger.debug("OpenRouter response: %dms tokens=%s reply=%r",
                      elapsed_ms, usage, reply_text[:200])

        return {
            "reply": reply_text,
            "debug": {
                "model": self.model,
                "temperature": self.temperature,
                "max_tokens": self.max_tokens,
                "response_time_ms": elapsed_ms,
                "history_message_count": len(history),
                "rag": {
                    "chunk_count": len(rag_chunks),
                    "sources": list({d["source"] for d in rag_debug}),
                    "chunks": rag_debug,
                },
                "token_usage": {
                    "prompt_tokens": usage.get("prompt_tokens"),
                    "completion_tokens": usage.get("completion_tokens"),
                    "total_tokens": usage.get("total_tokens"),
                },
                "system_prompt": messages[0]["content"],
                "messages_sent": messages,
            },
        }
