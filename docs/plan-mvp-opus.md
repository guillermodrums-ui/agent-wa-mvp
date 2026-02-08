# MVP: Agente IA WhatsApp - Simulador Local para Mauri

## Contexto
Mauri es el primer cliente. Necesitamos un MVP funcional que demuestre cómo un agente IA atendería clientes vía WhatsApp. El MVP corre 100% local con Docker, usa OpenRouter + DeepSeek (barato), y tiene una UI tipo chat donde se pueden crear conversaciones nuevas simulando distintos clientes.

**No se integra con WhatsApp real todavía** - es un simulador local para demostrar y testear el agente antes de conectarlo.

## Arquitectura

```
┌─────────────────────┐     ┌──────────────────────┐     ┌─────────────────┐
│   Chat UI (HTML)    │────▶│  FastAPI Backend      │────▶│  OpenRouter API  │
│   Puerto 8000       │     │  Puerto 8000          │     │  (DeepSeek)      │
│                     │◀────│  - Sessions mgmt      │◀────│                  │
│  - Multi-chat       │     │  - Chat history        │     └─────────────────┘
│  - New chat button  │     │  - System prompt       │
│  - WhatsApp style   │     │  - Config por cliente  │
└─────────────────────┘     └──────────────────────┘
         Todo dentro de un solo container Docker
```

## Estructura de archivos a crear

```
Agente IA WA/
├── docker-compose.yml
├── Dockerfile
├── .env.example
├── .gitignore
├── requirements.txt
├── app/
│   ├── main.py              # FastAPI app + rutas
│   ├── agent.py             # Lógica del agente IA (OpenRouter)
│   ├── models.py            # Pydantic models
│   ├── config.py            # Settings y system prompt
│   └── static/
│       └── index.html        # Chat UI (single file, todo inline)
└── Clientes/
    └── Mauri/
        ├── config.yaml       # Configuración específica de Mauri
        └── catalogo.txt      # Catálogo de productos (texto plano)
```

## Plan de implementación

### 1. Configuración del proyecto
**Archivos:** `requirements.txt`, `.env.example`, `.gitignore`, `Dockerfile`, `docker-compose.yml`

- **requirements.txt**: fastapi, uvicorn, httpx, pyyaml, pydantic-settings, python-dotenv
- **.env.example**: `OPENROUTER_API_KEY=your_key_here`
- **Dockerfile**: Python 3.11-slim, instalar deps, copiar app, exponer 8000
- **docker-compose.yml**: un servicio `agent`, monta `.env`, expone puerto 8000

### 2. Backend FastAPI (`app/`)

**`app/config.py`**
- Cargar OPENROUTER_API_KEY desde env
- Cargar config de cliente desde YAML (nombre negocio, system prompt, etc)

**`app/models.py`**
- `ChatMessage(role, content, timestamp)`
- `ChatSession(id, phone_number, messages[], created_at)`
- `SendMessageRequest(session_id, message)`
- `NewSessionRequest(phone_number?)` - opcional, puede autogenerar

**`app/agent.py`**
- Clase `WhatsAppAgent`:
  - `__init__(config)` - carga system prompt
  - `async chat(session_id, message, history) -> str` - llama a OpenRouter
  - Usa httpx para llamar a `https://openrouter.ai/api/v1/chat/completions`
  - Modelo: `deepseek/deepseek-chat` (muy barato, ~$0.14/M tokens)
  - System prompt personalizable por cliente

**`app/main.py`**
- Almacenamiento en memoria: `dict[str, ChatSession]`
- Endpoints:
  - `GET /` → sirve `static/index.html`
  - `POST /api/sessions` → crea nueva sesión (nuevo "cliente WhatsApp")
  - `GET /api/sessions` → lista sesiones activas
  - `GET /api/sessions/{id}` → historial de una sesión
  - `DELETE /api/sessions/{id}` → eliminar sesión
  - `POST /api/chat` → enviar mensaje y recibir respuesta del agente
  - `GET /api/config` → info del negocio (nombre, etc) para mostrar en UI

### 3. Chat UI (`app/static/index.html`)

Single HTML file con CSS y JS inline. Estilo WhatsApp.

**Layout:**
```
┌──────────────┬─────────────────────────────────┐
│  Sidebar     │   Chat Area                     │
│              │                                 │
│ [+ Nuevo]    │  ┌─ Header: "Cliente +54..."──┐ │
│              │  │                             │ │
│ Chat 1 ●     │  │  Mensajes...               │ │
│ Chat 2       │  │  (burbujas estilo WA)      │ │
│ Chat 3       │  │                             │ │
│              │  │  [____input____] [Enviar]   │ │
│              │  └─────────────────────────────┘ │
└──────────────┴─────────────────────────────────┘
```

**Features:**
- Sidebar con lista de chats y botón "Nuevo Chat"
- Cada chat tiene un número de teléfono simulado (+54 9 XXX...)
- Burbujas verdes (usuario) y blancas (agente) estilo WhatsApp
- Indicador "escribiendo..." mientras el agente responde
- Auto-scroll al último mensaje
- Responsive (funciona en mobile)

### 4. Config de Mauri (`Clientes/Mauri/config.yaml`)

Mauri es **personal trainer** y vende suplementos deportivos (creatina, testosterona, whey protein, fármacos). El agente se llama **Nico**.

```yaml
business:
  name: "La Fórmula"
  owner: "Mauri"
  description: "Personal trainer y venta de suplementos deportivos"
  products:
    - "Creatina"
    - "Testosterona"
    - "Whey Protein"
    - "Suplementos deportivos"
    - "Planes de entrenamiento personalizados"

agent:
  name: "Nico"
  system_prompt: |
    Sos Nico, el asistente virtual de La Fórmula por WhatsApp.
    Mauri es personal trainer y vende suplementos deportivos.

    PRODUCTOS QUE MANEJAMOS:
    - Creatina
    - Testosterona
    - Whey Protein
    - Suplementos deportivos varios
    - Planes de entrenamiento personalizados

    REGLAS:
    - Respondé siempre en español argentino (vos, tenés, etc)
    - Sé amable, cercano y conciso (es WhatsApp, mensajes cortos)
    - Si preguntan precios exactos, decí que le pasás con Mauri para confirmar
    - No inventes precios ni stock
    - Si preguntan por planes de entrenamiento, mencioná que Mauri arma planes personalizados
    - Podés recomendar productos según los objetivos del cliente
    - Si preguntan algo que no sabés, decí "le consulto a Mauri y te respondo"
    - Usá emojis con moderación (1-2 por mensaje máximo)

    CATÁLOGO:
    - Tenés acceso al catálogo de productos (se inyecta abajo)
    - Si el cliente pregunta algo que está en el catálogo, respondé Y ofrecé mandarlo
    - No te frustres si preguntan cosas obvias del catálogo, respondé igual con buena onda

    DESCUENTOS:
    - Cliente nuevo: 10% de descuento en primera compra
    - Compra de 3 o más productos: 15% de descuento
    - Estos descuentos los podés mencionar proactivamente

    PREGUNTAS FRECUENTES DE USO:
    - Muchos clientes preguntan cómo tomar creatina, proteína, etc.
    - Dá recomendaciones generales de uso/dosificación
    - Siempre aclará que consulten con su médico para temas hormonales
    - Sugerí productos complementarios si tiene sentido

    EJEMPLO DE TONO:
    "Hola! Soy Nico, asistente de La Fórmula 💪 En qué te puedo ayudar?"

  model: "deepseek/deepseek-chat"
  temperature: 0.7
  max_tokens: 500
```

### 5. Docker

**Dockerfile:**
```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
```

**docker-compose.yml:**
```yaml
services:
  agent:
    build: .
    ports:
      - "8000:8000"
    env_file:
      - .env
    volumes:
      - ./app:/app/app           # Hot reload
      - ./Clientes:/app/Clientes # Config de clientes
```

## Verificación / Testing

1. `cp .env.example .env` → poner API key de OpenRouter
2. `docker compose up --build`
3. Abrir `http://localhost:8000`
4. Click "Nuevo Chat" → se crea sesión con número random
5. Escribir "Hola, qué servicios ofrecen?" → el agente responde
6. Click "Nuevo Chat" → contexto limpio, otro "cliente"
7. Verificar que cada chat mantiene su propio historial

## Features extra para la realidad de Mauri

### A. Catálogo PDF como contexto
- Mauri tiene un PDF con su catálogo de productos
- Se coloca en `Clientes/Mauri/catalogo.txt` (texto extraído del PDF)
- El agente lo carga como parte del contexto y puede responder preguntas del catálogo
- Cuando un cliente pregunta algo que está en el catálogo, Nico responde Y le dice "te paso el catálogo completo"
- Esto se inyecta en el system prompt automáticamente

### B. Reglas de descuento en el prompt
- Cliente nuevo → descuento de bienvenida
- Compra 3+ productos → descuento por volumen
- Estas reglas van en el config.yaml y se inyectan en el system prompt

### C. Manejo de preguntas repetitivas
- El system prompt instruye a Nico para:
  - Responder preguntas de dosificación/uso proactivamente
  - Referenciar el catálogo cuando la info está ahí
  - Ser paciente con preguntas frecuentes (es el mayor valor del bot)
  - Sugerir productos complementarios

### D. Audio (simulado en MVP)
- En el MVP: botón "Simular Audio" que envía texto marcado como [AUDIO]
- Esto prepara la arquitectura para cuando se integre Whisper/speech-to-text
- El agente trata mensajes [AUDIO] igual que texto (en producción Whisper los transcribe)

---

# FASE 2: Knowledge Base con RAG

## Contexto
Mauri necesita que su agente Nico conozca más que solo el catálogo hardcodeado. En la realidad, Mauri tiene PDFs de catálogo, audios de clientes, historiales de chat de WhatsApp, y notas sueltas. Queremos un panel donde Mauri suba estos archivos y el agente los use como base de conocimiento.

**Problema actual:** Todo el catálogo se mete en el system prompt (context stuffing). Funciona para poco contenido, pero no escala cuando hay PDFs de 20 páginas, 50 conversaciones históricas, etc.

**Solución:** RAG - Retrieval Augmented Generation. Indexar los documentos en una base vectorial, y al recibir cada mensaje, buscar solo los fragmentos relevantes para inyectarlos en el contexto.

## Arquitectura RAG

```
┌─────────────────────┐
│  Panel Admin (UI)   │  Mauri sube archivos acá
│  /admin             │
│                     │
│  [Upload PDF]       │
│  [Upload Audio txt] │
│  [Pegar Chat WA]    │
│  [Agregar notas]    │
└────────┬────────────┘
         │ POST /api/knowledge/upload
         ▼
┌─────────────────────────────────────────────┐
│  Procesamiento (app/knowledge.py)            │
│                                              │
│  PDF ──▶ PyMuPDF ──▶ texto ──┐              │
│  Audio txt ──────────────────┤              │
│  Chat WA export ──▶ parse ───┤  chunking    │
│  Notas libres ───────────────┘  (500 chars) │
│                                    │         │
│                          embed + store       │
│                                    ▼         │
│                            ┌────────────┐    │
│                            │  ChromaDB   │    │
│                            │  (local)    │    │
│                            │  persist/   │    │
│                            └────────────┘    │
└─────────────────────────────────────────────┘

┌─────────────────────────────────────────────┐
│  Chat Flow (modificado)                      │
│                                              │
│  1. Usuario envía mensaje                    │
│  2. Buscar top-5 chunks relevantes en Chroma │
│  3. Inyectar chunks en contexto del LLM      │
│  4. System prompt + chunks + historial       │
│  5. LLM responde con conocimiento enriquecido│
└─────────────────────────────────────────────┘
```

## Tecnologías elegidas

| Componente | Tecnología | Por qué |
|------------|-----------|---------|
| Vector DB | **ChromaDB** | Puro Python, corre in-process, persiste a disco, gratis, ideal para MVP |
| Embeddings | **Default de Chroma** (all-MiniLM-L6-v2 via onnxruntime) | Gratis, local, no necesita GPU, ~80MB |
| PDF extraction | **PyMuPDF (fitz)** | Rápido, liviano, extrae texto limpio |
| Chunking | **Manual** (split por párrafos, ~500 chars max) | Simple, sin deps extra |

## Archivos a crear/modificar

### Archivos NUEVOS:
```
app/
├── knowledge.py          # KnowledgeBase class: upload, chunk, embed, search
└── static/
    └── admin.html        # Panel de admin para subir archivos
```

### Archivos a MODIFICAR:
```
app/main.py              # Agregar rutas /admin y /api/knowledge/*
app/agent.py             # Modificar chat() para incluir RAG retrieval
app/models.py            # Agregar modelos para Knowledge
requirements.txt         # Agregar chromadb, PyMuPDF
docker-compose.yml       # Agregar volumen para persistencia ChromaDB
Dockerfile               # Sin cambios (pip install se encarga)
```

## Plan de implementación paso a paso

### Paso 1: `requirements.txt` - Agregar dependencias
```
chromadb==0.5.23
PyMuPDF==1.25.3
python-multipart==0.0.12    # Para file uploads en FastAPI
```

### Paso 2: `app/models.py` - Nuevos modelos
- `KnowledgeDocument(id, filename, doc_type, chunk_count, created_at)`
- `doc_type` enum: `"pdf"`, `"audio_transcript"`, `"chat_history"`, `"note"`

### Paso 3: `app/knowledge.py` - Clase KnowledgeBase

```python
class KnowledgeBase:
    def __init__(self, persist_dir: str):
        # Inicializa ChromaDB con persistencia en disco
        # Crea/abre collection "knowledge"

    def add_pdf(self, file_bytes, filename) -> KnowledgeDocument:
        # 1. PyMuPDF extrae texto del PDF
        # 2. Divide en chunks de ~500 chars por párrafo
        # 3. Agrega chunks a ChromaDB con metadata (source=filename, type=pdf)

    def add_text(self, text, filename, doc_type) -> KnowledgeDocument:
        # Para: audio transcripts, notas, chat history
        # 1. Divide en chunks
        # 2. Agrega a ChromaDB

    def add_chat_export(self, text, filename) -> KnowledgeDocument:
        # 1. Parsea formato export de WhatsApp (fecha - nombre: mensaje)
        # 2. Agrupa por bloques de conversación (5-10 mensajes)
        # 3. Agrega como chunks

    def search(self, query: str, n_results: int = 5) -> list[str]:
        # Busca chunks similares al query
        # Retorna lista de textos relevantes

    def list_documents(self) -> list[KnowledgeDocument]:
        # Lista todos los documentos indexados

    def delete_document(self, doc_id: str):
        # Elimina documento y sus chunks de ChromaDB
```

### Paso 4: `app/agent.py` - Integrar RAG en el chat

Modificar el método `chat()`:
```python
async def chat(self, history, user_message, knowledge_base=None):
    messages = [{"role": "system", "content": self.system_prompt}]

    # RAG: buscar contexto relevante
    if knowledge_base:
        chunks = knowledge_base.search(user_message, n_results=5)
        if chunks:
            context = "\n\n".join(chunks)
            messages.append({
                "role": "system",
                "content": f"CONTEXTO RELEVANTE DE LA BASE DE CONOCIMIENTO:\n{context}"
            })

    # Resto igual: agregar historial + mensaje actual
    for msg in history:
        messages.append({"role": msg.role, "content": msg.content})
    messages.append({"role": "user", "content": user_message})

    # Llamar a OpenRouter...
```

### Paso 5: `app/main.py` - Nuevos endpoints

```
GET  /admin                           → sirve admin.html
POST /api/knowledge/upload            → subir archivo (PDF, txt)
POST /api/knowledge/text              → agregar texto libre (nota, audio transcript)
POST /api/knowledge/chat-export       → subir export de WhatsApp
GET  /api/knowledge/documents         → listar documentos indexados
DELETE /api/knowledge/documents/{id}  → eliminar documento
```

Además, pasar `knowledge_base` al `agent.chat()` en el endpoint `/api/chat`.

### Paso 6: `app/static/admin.html` - Panel de admin

```
┌─────────────────────────────────────────────────────┐
│  🔧 Panel Admin - La Fórmula                     │
│  ← Volver al Chat                                   │
├─────────────────────────────────────────────────────┤
│                                                     │
│  📄 Subir PDF (catálogo, lista de precios)          │
│  [Seleccionar archivo] [Subir]                      │
│                                                     │
│  🎤 Agregar transcripción de audio                  │
│  [textarea: pegar texto del audio] [Guardar]        │
│                                                     │
│  💬 Importar chat de WhatsApp                       │
│  [textarea: pegar export del chat] [Importar]       │
│                                                     │
│  📝 Agregar nota libre                              │
│  [textarea: info adicional, FAQ, etc] [Guardar]     │
│                                                     │
├─────────────────────────────────────────────────────┤
│  📚 Base de Conocimiento (3 documentos)             │
│                                                     │
│  📄 catalogo_2024.pdf (45 chunks) [🗑️]             │
│  💬 chat_cliente_juan.txt (12 chunks) [🗑️]         │
│  📝 nota_descuentos.txt (3 chunks) [🗑️]            │
└─────────────────────────────────────────────────────┘
```

### Paso 7: `docker-compose.yml` - Persistencia

Agregar volumen para que ChromaDB persista entre reinicios:
```yaml
volumes:
  - ./app:/app/app
  - ./config:/app/config
  - ./data/chroma:/app/data/chroma    # NUEVO: persistencia vectorial
```

## Verificación / Testing

1. `docker compose up --build`
2. Abrir `http://localhost:7070/admin`
3. Subir un PDF → verificar que aparece en la lista con X chunks
4. Agregar una nota de texto → verificar chunks
5. Pegar un export de WhatsApp → verificar parseo
6. Volver al chat → escribir una pregunta sobre algo del PDF
7. Verificar que Nico responde usando info del documento subido
8. Reiniciar container → verificar que los documentos persisten

## Notas
- ChromaDB persiste en `./data/chroma/` (volumen Docker)
- El `catalogo.txt` original sigue funcionando como base del system prompt
- RAG agrega contexto EXTRA encima del system prompt
- Si no hay documentos en la knowledge base, funciona igual que antes
- Los chunks se guardan con metadata (source, type) para poder filtrar después

---

# TO-DOs / Mejoras Futuras

## Optimización: Mover catálogo de system prompt a RAG

**Problema actual:**
- El archivo `config/catalogo.txt` se carga en `app/config.py` y se inyecta completo en el system prompt
- Esto significa que el catálogo completo (67 líneas) se envía al LLM en **cada mensaje**, incluso cuando el usuario no pregunta por productos
- Consume tokens innecesarios y aumenta costos

**Solución propuesta:**
1. Indexar `catalogo.txt` automáticamente en ChromaDB al iniciar la app (en `app/config.py` o `app/knowledge.py`)
2. Remover la inyección del catálogo del system prompt base
3. Dejar que RAG inyecte solo los chunks relevantes cuando el usuario pregunte por productos
4. Mantener referencia genérica en el system prompt: "Tenés acceso al catálogo de productos a través de la base de conocimiento"

**Archivos a modificar:**
- `app/config.py`: Remover la concatenación del catálogo al system prompt
- `app/knowledge.py`: Agregar método `load_catalog_from_file()` que se ejecute al inicializar
- `app/main.py`: Llamar a la carga del catálogo al iniciar la app

**Beneficios:**
- Reduce tokens por mensaje (~200-300 tokens menos)
- Reduce costos de API
- Permite más espacio para historial de conversación
- El catálogo solo se usa cuando es relevante (mejor relevancia)
