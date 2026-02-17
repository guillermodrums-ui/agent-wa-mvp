import re

import httpx

from app.agent import OPENROUTER_URL


class Introspector:
    """Analyses agent responses citing concrete evidence (RAG chunks, prompt sections)
    and suggests executable actions (edit prompt, delete doc, change priority)."""

    def __init__(self, agent, knowledge_base):
        self.agent = agent
        self.kb = knowledge_base

    async def ask(self, debug_snapshot: dict, history: list[dict], question: str) -> dict:
        meta_prompt = self._build_meta_prompt(debug_snapshot)
        messages = [{"role": "system", "content": meta_prompt}]
        messages.extend(history)
        messages.append({"role": "user", "content": question})

        raw = await self._call_llm(messages)
        answer, actions = self._parse_actions(raw)
        actions = self._validate_actions(actions)

        return {"answer": answer, "actions": actions}

    # ------------------------------------------------------------------
    # Meta-prompt
    # ------------------------------------------------------------------

    def _build_meta_prompt(self, snap: dict) -> str:
        rag = snap.get("rag", {})
        tokens = snap.get("token_usage", {})
        msgs = snap.get("messages_sent", [])

        # Extract user message and agent reply from messages_sent
        user_message = ""
        agent_reply = ""
        for m in reversed(msgs):
            if m.get("role") == "user" and not user_message:
                user_message = m["content"]
            if m.get("role") == "assistant" and not agent_reply:
                agent_reply = m["content"]
        # If agent_reply not in messages_sent, it may come from outer context
        if not agent_reply:
            agent_reply = snap.get("agent_reply", "")
        if not user_message:
            user_message = snap.get("user_message", "")

        # Build RAG chunks section
        chunks_text = ""
        for i, c in enumerate(rag.get("chunks", []), 1):
            chunks_text += (
                f"Chunk {i} (de '{c.get('source', '?')}', similarity: {c.get('similarity', '?')}, "
                f"priority: {c.get('priority', '?')}):\n\"{c.get('text', '')}\"\n\n"
            )

        # Build available docs list for actions
        docs = self.kb.list_documents()
        docs_text = ""
        for d in docs:
            docs_text += (
                f"- doc_id=\"{d['id']}\" -> \"{d['filename']}\" "
                f"(priority: {d.get('priority', 3)}, {d['chunk_count']} chunks)\n"
            )

        # Last 5 conversation turns
        conv_turns = [m for m in msgs if m.get("role") in ("user", "assistant")]
        last_turns = conv_turns[-10:]  # 5 pairs = 10 messages max
        history_text = ""
        for m in last_turns:
            role_label = "Usuario" if m["role"] == "user" else "Agente"
            history_text += f"{role_label}: {m['content'][:300]}\n"

        return f"""Sos un analista de calidad para el agente "Nico". Explica POR QUE respondio asi, citando evidencia concreta.

### RESPUESTA ANALIZADA
Mensaje del usuario: {user_message}
Respuesta del agente: {agent_reply}
Modelo: {snap.get('model', '?')} | Temp: {snap.get('temperature', '?')} | Tokens completados: {tokens.get('completion_tokens', '?')}

### SYSTEM PROMPT QUE RECIBIO:
{snap.get('system_prompt', '')}

### CHUNKS RAG RECUPERADOS:
{chunks_text if chunks_text else '(ninguno)'}

### DOCUMENTOS RAG DISPONIBLES (para acciones):
{docs_text if docs_text else '(ninguno)'}

### HISTORIAL ({len(last_turns)} mensajes):
{history_text if history_text else '(vacio)'}

### REGLAS:
1. SIEMPRE cita evidencia concreta. Nunca digas "probablemente" sin respaldo.
2. Cuando cites un chunk RAG: "Viene del chunk de 'nombre.pdf' (similarity: 0.87): 'texto del chunk'"
3. Cuando cites el prompt: copia las lineas exactas entre comillas.
4. Cuando sugieras mejoras, usa formato ACTION al final de tu respuesta.
   El formato es ACTION:tipo:descripcion corta del boton:parametros
   La descripcion va ANTES de los parametros (nunca al reves). Ejemplos:
   ACTION:edit_prompt:Agregar regla de stock:append=- Nunca confirmar stock sin verificar
   ACTION:delete_rag_doc:Eliminar documento viejo:doc_id=abc123
   ACTION:update_rag_priority:Bajar prioridad:doc_id=abc123,priority=1
   IMPORTANTE: el texto despues de "append=" es EXACTAMENTE lo que se agrega al prompt. Que sea una regla clara y corta. Una sola linea por ACTION.
5. Habla en argentino casual.
6. Se conciso: causa raiz en 2-3 oraciones, despues acciones concretas."""

    # ------------------------------------------------------------------
    # LLM call (same pattern as evaluator._llm_judge)
    # ------------------------------------------------------------------

    async def _call_llm(self, messages: list[dict]) -> str:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                OPENROUTER_URL,
                headers={
                    "Authorization": f"Bearer {self.agent.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.agent.model,
                    "messages": messages,
                    "temperature": 0.3,
                    "max_tokens": 1000,
                },
            )
            response.raise_for_status()
            data = response.json()

        return data["choices"][0]["message"]["content"].strip()

    # ------------------------------------------------------------------
    # Parse and validate ACTION lines
    # ------------------------------------------------------------------

    # Format: ACTION:type:label:params  (label has no colons, params can have anything)
    ACTION_RE = re.compile(r"^ACTION:(\w+):([^:]+):(.+)$", re.MULTILINE)

    def _parse_actions(self, raw: str) -> tuple[str, list[dict]]:
        actions = []
        for match in self.ACTION_RE.finditer(raw):
            action_type = match.group(1)
            label = match.group(2).strip()
            params_raw = match.group(3).strip()

            params = {}
            if action_type == "edit_prompt":
                if params_raw.startswith("append="):
                    params["append"] = params_raw[len("append="):]
            elif action_type == "delete_rag_doc":
                if params_raw.startswith("doc_id="):
                    params["doc_id"] = params_raw[len("doc_id="):]
            elif action_type == "update_rag_priority":
                for part in params_raw.split(","):
                    part = part.strip()
                    if part.startswith("doc_id="):
                        params["doc_id"] = part[len("doc_id="):]
                    elif part.startswith("priority="):
                        try:
                            params["priority"] = int(part[len("priority="):])
                        except ValueError:
                            pass

            actions.append({"type": action_type, "label": label, "params": params})

        # Remove ACTION lines from the answer text
        clean = self.ACTION_RE.sub("", raw).strip()
        return clean, actions

    def _validate_actions(self, actions: list[dict]) -> list[dict]:
        valid_doc_ids = {d["id"] for d in self.kb.list_documents()}
        validated = []
        for action in actions:
            if action["type"] in ("delete_rag_doc", "update_rag_priority"):
                if action["params"].get("doc_id") not in valid_doc_ids:
                    continue
            if action["type"] == "update_rag_priority":
                p = action["params"].get("priority")
                if p is None or not (1 <= p <= 5):
                    continue
            validated.append(action)
        return validated
