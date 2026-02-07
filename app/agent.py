import httpx
from app.models import ChatMessage

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


class WhatsAppAgent:
    def __init__(self, api_key: str, config: dict):
        self.api_key = api_key
        self.agent_config = config["agent"]
        self.system_prompt = self.agent_config["system_prompt"]
        self.model = self.agent_config.get("model", "deepseek/deepseek-chat")
        self.temperature = self.agent_config.get("temperature", 0.7)
        self.max_tokens = self.agent_config.get("max_tokens", 500)

    async def chat(self, history: list[ChatMessage], user_message: str, knowledge_base=None) -> str:
        messages = [{"role": "system", "content": self.system_prompt}]

        # RAG: inject relevant knowledge chunks
        if knowledge_base:
            chunks = knowledge_base.search(user_message, n_results=5)
            if chunks:
                context = "\n\n".join(chunks)
                messages.append({
                    "role": "system",
                    "content": f"CONTEXTO RELEVANTE DE LA BASE DE CONOCIMIENTO:\n{context}",
                })

        for msg in history:
            messages.append({"role": msg.role, "content": msg.content})

        messages.append({"role": "user", "content": user_message})

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                OPENROUTER_URL,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "messages": messages,
                    "temperature": self.temperature,
                    "max_tokens": self.max_tokens,
                },
            )
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"]
