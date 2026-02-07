# Feature: Debug Viewer en cada respuesta del bot

**Estado: IMPLEMENTADO**

## Contexto

Para la demo con Mauri y para debugging propio, queremos agregar un visor expandible debajo de cada respuesta del bot que muestre la info "raw" enviada al modelo de IA. Dos niveles:

1. **Detalles** (para Mauri) — Modelo usado, chunks RAG encontrados, fuentes, tiempo de respuesta
2. **Debug tecnico** (para el dev) — System prompt completo, RAG chunks con scores de similitud, messages array completo, tokens, parametros del modelo

El visor esta colapsado por defecto — el chat se ve exactamente igual que antes hasta que se clickea "ver detalles".

---

## Archivos a Modificar

| Archivo | Cambios |
|---------|---------|
| `app/knowledge.py` | +metodo `search_with_debug()` que retorna chunks + metadata + distances (~20 lineas) |
| `app/agent.py` | Reescribir `chat()` para retornar dict con reply + debug info, agregar timing (~45 lineas) |
| `app/main.py` | Actualizar `/api/chat` para pasar debug info en la respuesta JSON (~5 lineas) |
| `app/static/index.html` | +CSS debug viewer (~70 lineas), +`buildDebugHtml()` y toggles (~100 lineas), actualizar `addMessageBubble()` |

---

## Paso 1: `app/knowledge.py` — Nuevo metodo `search_with_debug()`

Agregar despues del metodo `search()` existente (linea 150). No tocar `search()` — queda como backup.

```python
def search_with_debug(self, query: str, n_results: int = 5) -> dict:
    if self.collection.count() == 0:
        return {"chunks": [], "debug": []}

    n = min(n_results, self.collection.count())
    results = self.collection.query(
        query_texts=[query], n_results=n,
        include=["documents", "metadatas", "distances"],
    )

    chunks = results["documents"][0] if results["documents"] else []
    metadatas = results["metadatas"][0] if results.get("metadatas") else []
    distances = results["distances"][0] if results.get("distances") else []

    debug = []
    for i, chunk_text in enumerate(chunks):
        meta = metadatas[i] if i < len(metadatas) else {}
        dist = distances[i] if i < len(distances) else None
        debug.append({
            "text": chunk_text,
            "source": meta.get("source", "desconocido"),
            "type": meta.get("type", ""),
            "chunk_index": meta.get("chunk_index", 0),
            "distance": round(dist, 4) if dist is not None else None,
            "similarity": round(1 - dist, 4) if dist is not None else None,
        })

    return {"chunks": chunks, "debug": debug}
```

Notas:
- ChromaDB con `cosine` space: similarity = 1 - distance
- `include=["documents", "metadatas", "distances"]` pide los 3 arrays explicitamente

---

## Paso 2: `app/agent.py` — Reescribir `chat()` para retornar dict

Agregar `import time` al top. Cambiar el metodo `chat()` para que retorne un dict con reply + debug info.

Cambios clave:
- Llamar `knowledge_base.search_with_debug()` en vez de `search()`
- Medir tiempo con `time.monotonic()`
- Extraer `usage` del response de OpenRouter (tokens)
- Retornar dict:

```python
return {
    "reply": reply_text,
    "debug": {
        "model": self.model,
        "temperature": self.temperature,
        "max_tokens": self.max_tokens,
        "response_time_ms": round((t_end - t_start) * 1000),
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
        "system_prompt": self.system_prompt,
        "messages_sent": messages,
    },
}
```

---

## Paso 3: `app/main.py` — Actualizar endpoint `/api/chat`

Cambiar para destructurar el dict de `agent.chat()`:

```python
result = await agent.chat(session.messages[:-1], req.message, knowledge_base=kb)
reply = result["reply"]
debug_info = result.get("debug")
```

Agregar `debug` al response solo si existe (graceful degradation en errores).

---

## Paso 4: `app/static/index.html` — Frontend

### CSS
- `.debug-toggle` — link sutil (11px, opacity 0.6) debajo del mensaje
- `.debug-panel` — hidden por defecto, se muestra con clase `.open`
- `.debug-details` — flex wrap para los items de Level 1
- `.debug-raw pre` — fondo oscuro, monospace, max-height 300px con scroll
- `.debug-chunk` — card con borde verde izquierdo para cada chunk RAG

### JS — `buildDebugHtml(debug)`
Funcion pura que genera el HTML del visor. Dos secciones:

**Level 1 "Detalles"** (abierto por defecto cuando se expande):
- Modelo (nombre friendly derivado del slug)
- RAG chunks count + nombres de fuentes
- Historial: N mensajes previos
- Tiempo de respuesta

**Level 2 "Debug tecnico"** (colapsado por defecto):
- Tokens (in/out/total)
- Parametros (temperature, max_tokens)
- System prompt completo (en `<details>/<summary>`)
- RAG chunks con scores de similitud (en `<details>`)
- Messages array completo como JSON (en `<details>`)

### JS — Toggles
- `toggleDebugPanel(el)` — abre/cierra el panel entero
- `toggleDebugSection(id)` — abre/cierra Level 1 o Level 2

### Cambios a funciones existentes
- `addMessageBubble(role, content, time, debugData)` — 4to param opcional, solo para assistant
- `sendMessage()` — pasar `data.debug` a `addMessageBubble`
- `sendAudio()` — idem

Mensajes historicos (`renderMessages()`) NO tienen debug data — aceptable para MVP.

---

## Verificacion

1. `docker compose up --build`
2. Ir al chat, enviar un mensaje
3. La respuesta del bot se ve normal (igual que antes)
4. Debajo del timestamp aparece "ver detalles" (texto sutil)
5. Click → se expande Level 1 con modelo, RAG chunks, fuentes, tiempo
6. Click "Debug tecnico" → se expande Level 2 con tokens, params
7. Dentro de Level 2, abrir "System prompt completo" → muestra el prompt en pre
8. Abrir "RAG chunks con scores" → cards con texto + similarity score
9. Abrir "Messages array" → JSON completo enviado a OpenRouter
10. Cargar KB con un PDF primero para verificar que los chunks RAG aparecen con source correcto
11. Verificar que si el agent tira error, el chat sigue funcionando sin debug viewer
