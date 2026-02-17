# Plan: Feedback & Introspección — Ensayo y error para mejorar al agente

**Estado: IMPLEMENTADO**

## Contexto

Mauri necesita un flujo de ensayo y error: prueba el chat, ve una respuesta que no le gusta, y quiere entender **por qué** el agente respondió así y **cómo cambiarlo**. Hoy el debug panel ya muestra datos técnicos (RAG chunks, system prompt, tokens), pero no hay forma de **preguntar sobre** una respuesta ni recibir sugerencias ejecutables.

**Lo que ya existe y se reutiliza:**
- `agent.chat()` ya retorna debug completo: `system_prompt`, `messages_sent`, `rag.chunks` con scores, `token_usage`
- `evaluator.py` ya tiene el patrón de "preguntarle al LLM sobre su propia respuesta" (`_llm_judge()`)
- Frontend ya renderiza debug panel con "ver detalles" por cada mensaje
- Endpoints existentes para editar prompt, borrar docs RAG, y cambiar prioridades

**Enfoque:** Agregar un botón "Analizar respuesta" en cada mensaje del agente que abre un panel de Q&A donde el admin puede preguntarle al LLM por qué respondió así. El LLM cita fuentes concretas (chunks RAG, secciones del prompt) y sugiere acciones ejecutables con un click (editar prompt, borrar doc, cambiar prioridad).

---

## Archivos

| Archivo | Tipo | Cambios |
|---|---|---|
| `app/introspector.py` | **Nuevo** | Motor de introspección: meta-prompt, llamada LLM, parseo de ACTIONs |
| `app/main.py` | Modificar | +1 endpoint `POST /api/introspect`, instanciar Introspector |
| `app/static/index.html` | Modificar | Botón "Analizar", panel de introspección inline, storage de debug data en JS, ejecución de acciones |

---

## Fase 1: Backend — `app/introspector.py` (nuevo)

Clase `Introspector` que sigue el mismo patrón que `evaluator.py`:

```python
class Introspector:
    def __init__(self, agent, knowledge_base):
        self.agent = agent
        self.kb = knowledge_base

    async def ask(self, debug_snapshot: dict, history: list[dict], question: str) -> dict:
        meta_prompt = self._build_meta_prompt(debug_snapshot)
        messages = [{"role": "system", "content": meta_prompt}]
        messages.extend(history)  # turnos previos de introspección
        messages.append({"role": "user", "content": question})

        raw = await self._call_llm(messages)
        answer, actions = self._parse_actions(raw)
        actions = self._validate_actions(actions)

        return {"answer": answer, "actions": actions}
```

### Meta-prompt (pieza clave)

El meta-prompt recibe todo el contexto de la respuesta analizada y fuerza al LLM a:
1. **Citar evidencia concreta** — nunca "probablemente", siempre "viene del chunk de catalogo.pdf (similarity: 0.87)"
2. **Referenciar secciones del prompt** — copiar las líneas exactas
3. **Sugerir acciones ejecutables** con formato parseable

```
Sos un analista de calidad para el agente "Nico". Explica POR QUE respondio asi, citando evidencia.

### RESPUESTA ANALIZADA
Mensaje del usuario: {user_message}
Respuesta del agente: {agent_reply}
Modelo: {model} | Temp: {temperature} | Tokens: {completion_tokens}

### SYSTEM PROMPT QUE RECIBIO:
{system_prompt}

### CHUNKS RAG RECUPERADOS:
Chunk 1 (de '{source}', similarity: {score}, priority: {priority}):
"{text}"
...

### DOCUMENTOS RAG DISPONIBLES (para acciones):
- doc_id="abc123" -> "catalogo.pdf" (priority: 3, 12 chunks)
...

### HISTORIAL ({n} mensajes previos):
{ultimos 5 turnos}

### REGLAS:
1. SIEMPRE cita evidencia concreta. Nunca "probablemente".
2. Cuando cites un chunk RAG: "Viene del chunk de '{source}' (similarity: {score}): '{texto}'"
3. Cuando cites el prompt: copia las lineas exactas entre comillas
4. Cuando sugieras mejoras, usa formato ACTION al final:
   ACTION:edit_prompt:append={texto}:Agregar regla '{descripcion}'
   ACTION:delete_rag_doc:doc_id={id}:Eliminar '{nombre}'
   ACTION:update_rag_priority:doc_id={id},priority={n}:Cambiar prioridad de '{nombre}'
5. Habla en argentino/uruguayo casual.
6. Se conciso: causa raiz en 2-3 oraciones, despues acciones.
```

### Parseo de ACTIONs

```python
ACTION_RE = re.compile(r'^ACTION:(\w+):(.*?):(.*?)$', re.MULTILINE)
```

Extrae actions del texto, valida que los `doc_id` existan en `kb.list_documents()`, y retorna:
```python
{"answer": "texto limpio", "actions": [{"type": "edit_prompt", "label": "...", "params": {...}}]}
```

### Llamada LLM

Copia el patrón exacto de `evaluator.py` líneas 153-174: POST async a OpenRouter con `temperature=0.3` (más determinístico para análisis).

---

## Fase 2: Backend — Modificar `app/main.py`

~20 líneas:

```python
from app.introspector import Introspector

introspector = Introspector(agent=agent, knowledge_base=kb)

class IntrospectRequest(BaseModel):
    debug_snapshot: dict
    introspection_history: list[dict] = []
    question: str

@app.post("/api/introspect")
async def introspect(req: IntrospectRequest):
    result = await introspector.ask(req.debug_snapshot, req.introspection_history, req.question)
    return result
```

---

## Fase 3: Frontend — Modificar `app/static/index.html`

### 3A. Storage de debug data en JS

```javascript
const messageDebugStore = new Map();    // msgId -> debugData
const introspectionSessions = new Map(); // msgId -> [{role, content}]
let msgCounter = 0;
```

En `addMessageBubble()`: asignar `data-msg-id`, guardar debug en el Map.

### 3B. Botón "Analizar respuesta"

Al lado de "ver detalles", agregar link "Analizar respuesta" que abre el panel:

```
[Mensaje del agente]
14:30
ver detalles | Analizar respuesta    <-- nuevo botón
[debug panel - existente]
[introspection panel - nuevo]
```

### 3C. Panel de introspección (inline, debajo del debug panel)

```
┌─ Analizar respuesta ──────────────────────┐
│                                            │
│  Preguntas rapidas:                        │
│  [Por que respondiste asi?]                │
│  [Que chunks RAG usaste?]                  │
│  [Como mejoro esta respuesta?]             │
│                                            │
│  [area de chat scrolleable]                │
│  Admin: por que dijiste que tenias creatina│
│  Analista: Viene del chunk de catalogo.pdf │
│  (similarity: 0.87): "Creatina Mono..."   │
│                                            │
│  ── Acciones sugeridas ──                  │
│  [Eliminar catalogo-viejo.pdf] [Agregar    │
│   regla al prompt]                         │
│                                            │
│  [input] [Preguntar]                       │
└────────────────────────────────────────────┘
```

### 3D. JS: Funciones principales (~150 líneas)

- **`openIntrospectionPanel(msgId)`** — Crea el panel DOM con chips de preguntas rápidas e input
- **`sendIntrospectionQuestion(msgId, question)`** — POST a `/api/introspect` con debug snapshot + history + question. Renderiza respuesta + action buttons
- **`applyAction(action)`** — Mapea tipo de acción a endpoint existente:
  - `edit_prompt` → GET `/api/config/prompt` → append texto → POST `/api/config/prompt`
  - `delete_rag_doc` → DELETE `/api/knowledge/documents/{doc_id}`
  - `update_rag_priority` → PUT `/api/knowledge/documents/{doc_id}/metadata`
- Toast de confirmación después de aplicar

### 3E. CSS (~60 líneas)

Estilos para `.introspection-panel`, `.introspection-chat`, `.introspection-msg`, `.action-btn`, `.quick-chip`, `.flag-btn`

---

## Flujo completo (ejemplo)

1. Admin envía "che, tienen creatina?" en el simulador
2. Nico responde "Si! Tenemos creatina monohidratada de 300g..."
3. Admin piensa "no debería haber dicho eso, no tenemos stock"
4. Hace click en **"Analizar respuesta"**
5. Se abre el panel. Hace click en chip **"Por que respondiste asi?"**
6. Frontend envía POST `/api/introspect` con el debug completo + pregunta
7. LLM analiza: "Dijiste que tenias creatina porque el chunk de 'catalogo.pdf' (similarity: 0.89) dice: 'Creatina Monohidratada 300g - $15.000'. El system prompt no tiene ninguna regla que verifique stock actual."
8. Al final incluye: `ACTION:edit_prompt:append=\n- NUNCA confirmes stock sin verificar con Mauri primero:Agregar regla de verificación de stock`
9. Frontend renderiza la explicación + botón **[Agregar regla de verificación de stock]**
10. Admin hace click → se agrega la línea al prompt automáticamente → toast "Regla agregada al prompt"
11. Admin puede seguir preguntando: "y si quiero que derive a Mauri cuando preguntan por stock?"
12. LLM sugiere otra ACTION con texto específico para el prompt

---

## Decisiones técnicas

| Decisión | Elección | Por qué |
|---|---|---|
| Layout del panel | Inline (debajo del mensaje) | Funciona en desktop y mobile sin cambios. Si se migra a Cordova, el inline ya scrollea naturalmente en pantallas chicas. Convertible a bottom-sheet en el futuro |
| Storage de debug data | JS Map en frontend | Es transitorio, ya se retorna al frontend, evita otro storage en backend |
| Historia de introspección | Frontend, se envía con cada request | Stateless en backend, típicamente <10 turnos |
| Ejecución de acciones | Endpoints existentes directo desde frontend | Ya existen los 3 endpoints, no duplicar lógica |
| Temperatura del introspector | 0.3 (baja) | Análisis factual, no creativo |
| Modelo | Mismo que el agente | Introspecciona sobre su propio comportamiento |

## Verificación

1. Enviar mensaje al agente → verificar que aparece botón "Analizar respuesta"
2. Click en "Analizar" → verificar que se abre el panel con chips de preguntas rápidas
3. Preguntar "por qué respondiste así?" → verificar que cita chunks RAG específicos con scores
4. Preguntar "cómo mejoro esto?" → verificar que sugiere ACTIONs con botones ejecutables
5. Click en botón de acción "Agregar regla al prompt" → verificar que se modifica el prompt real
6. Click en "Eliminar documento" → verificar que desaparece del RAG
7. Verificar multi-turno: segunda pregunta mantiene contexto de la primera
