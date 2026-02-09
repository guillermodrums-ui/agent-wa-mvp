# Feature: Conectar Canales — WhatsApp Real via Evolution API

**Estado: IMPLEMENTADO**

## Contexto

El proyecto es un chatbot MVP (agente "Nico") para **La Formula** que actualmente funciona solo como simulador web. Para ponerlo productivo, necesitamos conectarlo a un WhatsApp real del cliente. Se elige **Evolution API** (open-source, self-hosted, Docker) como gateway porque:
- Gratis (usa protocolo WhatsApp Web via Baileys)
- REST API + webhooks = integra limpio con nuestro FastAPI
- Soporta multi-instancia (multiples numeros)
- En su roadmap tiene Instagram/Telegram, alineado con la vision multi-canal

La arquitectura se disena con una **capa de abstraccion de canales** para que agregar Instagram/Telegram en el futuro sea enchufar un nuevo modulo sin tocar la logica del agente.

---

## Archivos a Crear

| Archivo | Responsabilidad |
|---------|----------------|
| `app/channels/__init__.py` | Re-exports del paquete |
| `app/channels/base.py` | `ChannelType` enum, `IncomingMessage`/`OutgoingMessage` dataclasses, `BaseChannel` ABC |
| `app/channels/whatsapp.py` | `WhatsAppChannel` — cliente Evolution API (connect, send, status, disconnect, parse webhook) |
| `app/channels/manager.py` | `ChannelManager` — registro y orquestacion de canales |
| `app/sessions.py` | `SessionStore` — persistencia de sesiones en SQLite (reemplaza el dict in-memory) |

## Archivos a Modificar

| Archivo | Cambios |
|---------|---------|
| `app/models.py` | Agregar campos `channel` y `sender_name` a `ChatSession` |
| `app/main.py` | Reemplazar dict in-memory por `SessionStore`, agregar endpoints de canales, agregar webhook endpoint, inicializar `ChannelManager` |
| `app/static/admin.html` | Agregar tab "Canales" con UI de conexion WhatsApp (QR code, estado, boton desconectar) |
| `app/static/index.html` | Badge "WA" en sidebar para sesiones de WhatsApp real vs simulador |
| `docker-compose.yml` | Agregar servicio `evolution-api`, montar volumen `data/` para SQLite + chroma |
| `requirements.txt` | Agregar `aiosqlite` |
| `.env.example` | Agregar variables de Evolution API |

## Archivos que NO cambian

- `app/agent.py` — El agente es agnositco al canal. Recibe history + message, devuelve reply.
- `app/knowledge.py` — Completamente independiente del canal.
- `app/config.py` — Sin cambios necesarios.

---

## Diseno Detallado

### 1. Capa de Abstraccion de Canales (`app/channels/`)

**`base.py`** define la interfaz:
```python
class ChannelType(str, Enum):
    SIMULATOR = "simulator"
    WHATSAPP = "whatsapp"
    # Futuro: INSTAGRAM, TELEGRAM

@dataclass
class IncomingMessage:
    channel: ChannelType
    phone_number: str       # "5491166662222" (sin @s.whatsapp.net)
    sender_name: str
    text: str
    timestamp: int
    message_id: str = ""    # ID unico del mensaje (para deduplicacion)
    raw_payload: dict | None = None

@dataclass
class OutgoingMessage:
    channel: ChannelType
    phone_number: str
    text: str

class BaseChannel(ABC):
    channel_type: ChannelType

    async def send_message(self, message: OutgoingMessage) -> bool: ...
    async def get_status(self) -> dict: ...
    async def connect(self) -> dict: ...
    async def disconnect(self) -> bool: ...
```

**`whatsapp.py`** implementa `BaseChannel`:
- Usa `httpx.AsyncClient` con base_url de Evolution API y header `apikey`
- `connect()`: crea instancia via `POST /instance/create` + obtiene QR via `GET /instance/connect/{name}`
- `send_message()`: `POST /message/sendText/{instance_name}` con `{number, text}`
- `get_status()`: `GET /instance/connectionState/{name}` → retorna `{connected: bool, details: str}`
- `disconnect()`: `DELETE /instance/logout/{name}`
- `parse_webhook(payload)`: parsea payload de Evolution API → `IncomingMessage | None`. **Filtrado agresivo**:
  1. Verificar que `event` sea exactamente `messages.upsert` (ignorar todo otro tipo)
  2. Verificar que `key.fromMe` sea `False` (evitar bucle infinito de auto-respuesta)
  3. Ignorar mensajes de grupo (`remoteJid` con `@g.us`)
  4. Extraer `key.id` como `message_id` para deduplicacion
  5. Extraer phone del `remoteJid` (split `@s.whatsapp.net`)
  6. Obtener texto de `message.conversation` o `message.extendedTextMessage.text`
  7. Si no hay texto (imagen, sticker, audio) → retornar `None` por ahora

**`manager.py`** — registro simple:
- `register(channel)`, `get(channel_type)`, `get_all_statuses()`

### 2. Persistencia de Sesiones (`app/sessions.py`)

Reemplaza el `sessions: dict = {}` de `main.py`. Usa **SQLite** en `data/sessions.db`.

- `SessionStore(db_path)` — inicializa SQLite con `aiosqlite`, crea tablas si no existen
- **WAL Mode activado en init**: `PRAGMA journal_mode=WAL` — permite lecturas concurrentes mientras se escribe, critico para no bloquear el webhook handler mientras el agente procesa
- Tablas: `sessions` (id, phone_number, channel, sender_name, prompt_context, created_at), `messages` (id, session_id FK, role, content, timestamp), `processed_webhooks` (message_id PK, created_at)
- `get(session_id)`, `put(session_id, session)`, `delete(session_id)`, `get_all()`
- `get_or_create_by_phone(phone, channel, sender_name)` — busca sesion existente por telefono+canal, o crea nueva
- `add_message(session_id, role, content)` — inserta mensaje atomicamente
- `is_webhook_duplicate(message_id)` — chequea si un webhook ya fue procesado (deduplicacion)
- `mark_webhook_processed(message_id)` — registra message_id con timestamp
- `cleanup_old_webhooks()` — borra registros de deduplicacion >10 minutos (se corre periodicamente)
- Cada operacion persiste inmediatamente (SQLite + WAL maneja concurrencia)

**Dependencia nueva**: `aiosqlite` (async SQLite wrapper, ~50KB, zero config). Se agrega a `requirements.txt`.

**Ventajas sobre JSON**: Escrituras atomicas, queries por phone+channel eficientes, sin riesgo de corrupcion por crash, WAL mode para concurrencia real, tabla de deduplicacion integrada.

### 3. Cambios en `app/models.py`

Agregar a `ChatSession` (linea 15):
```python
class ChatSession(BaseModel):
    id: str
    phone_number: str
    messages: list[ChatMessage] = []
    prompt_context: str = ""
    created_at: str = ""
    channel: str = "simulator"     # NUEVO
    sender_name: str = ""           # NUEVO
```

### 4. Cambios en `app/main.py`

**Reemplazo de sesiones** (linea 22):
- `sessions: dict = {}` → `session_store = SessionStore("data/sessions/sessions.json")`
- Actualizar todas las referencias: `sessions[id]` → `session_store.get(id)`, etc.

**Inicializacion de canales** (despues de linea 19):
```python
channel_manager = ChannelManager()

EVOLUTION_API_URL = os.getenv("EVOLUTION_API_URL", "")
EVOLUTION_API_KEY = os.getenv("EVOLUTION_API_KEY", "")
EVOLUTION_INSTANCE_NAME = os.getenv("EVOLUTION_INSTANCE_NAME", "laformula")

if EVOLUTION_API_URL and EVOLUTION_API_KEY:
    wa_channel = WhatsAppChannel(api_url=..., api_key=..., instance_name=...)
    channel_manager.register(wa_channel)
```

**Nuevos endpoints**:
```
GET  /api/channels/whatsapp/status     → estado de conexion
POST /api/channels/whatsapp/connect    → crea instancia + retorna QR base64
POST /api/channels/whatsapp/disconnect → logout
POST /api/webhooks/evolution           → recibe mensajes de Evolution API
```

**Webhook handler** (`POST /api/webhooks/evolution`):
1. Validar header `apikey` (shared secret con Evolution API)
2. Si evento es `connection.update` → log estado y return 200
3. Parsear mensaje con `wa_channel.parse_webhook(payload)` → aplica filtrado agresivo (ver arriba)
4. Si `None` → return 200 (evento que no manejamos)
5. **Deduplicacion**: `session_store.is_webhook_duplicate(incoming.message_id)` → si ya existe, return 200 y no procesar
6. `session_store.mark_webhook_processed(incoming.message_id)` — registrar antes de procesar
7. `session_store.get_or_create_by_phone(phone, "whatsapp", sender_name)`
8. `session_store.add_message(session_id, "user", text)`
9. `await agent.chat(history, text, knowledge_base=kb, prompt_context=session.prompt_context)` con `asyncio.wait_for(timeout=25)`
10. `session_store.add_message(session_id, "assistant", reply)`
11. `await wa_channel.send_message(OutgoingMessage(phone=phone, text=reply))`
12. **Siempre retornar 200** (nunca 5xx, evita retries de Evolution API)

**Cleanup periodico**: En el startup de FastAPI, crear `asyncio.create_task` que cada 5 minutos ejecute `session_store.cleanup_old_webhooks()` para borrar IDs de deduplicacion >10 minutos.

**Timeout safety**: Envolver `agent.chat()` en `asyncio.wait_for(timeout=25)`. Si timeout, enviar mensaje de error al cliente.

**Endpoint list_sessions** (linea 90): agregar `channel` y `sender_name` al response.

### 5. Docker Compose — Evolution API

Agregar al `docker-compose.yml`:
```yaml
services:
  agent:
    # ... existente ...
    volumes:
      - ./app:/app/app
      - ./config:/app/config
      - ./data:/app/data              # SQLite + ChromaDB persistidos
    depends_on:
      - evolution-api

  evolution-api:
    image: atendai/evolution-api:latest
    ports:
      - "8080:8080"
    environment:
      - AUTHENTICATION_API_KEY=${EVOLUTION_API_KEY:-change_me}
      - SERVER_URL=http://evolution-api:8080
      - WEBHOOK_GLOBAL_ENABLED=true
      - WEBHOOK_GLOBAL_URL=http://agent:7070/api/webhooks/evolution
      - WEBHOOK_GLOBAL_WEBHOOK_BY_EVENTS=false
      - WEBHOOK_EVENTS_MESSAGES_UPSERT=true
      - WEBHOOK_EVENTS_CONNECTION_UPDATE=true
    volumes:
      - evolution_data:/evolution/instances

volumes:
  evolution_data:
```

El webhook global hace que Evolution API envie todos los eventos a `http://agent:7070/api/webhooks/evolution` automaticamente (via red interna Docker). No hace falta configurar webhooks por instancia.

### 6. Admin UI — Tab "Canales" (`admin.html`)

Agregar tercer boton tab (linea 325):
```html
<button class="tab" data-tab="canales" onclick="switchTab('canales')">Canales</button>
```

Contenido del tab con 3 estados:

**Estado 1 — Desconectado**: Boton "Conectar WhatsApp" prominente + descripcion
**Estado 2 — Escaneando QR**: Imagen QR centrada + instrucciones + boton "Cancelar"
**Estado 3 — Conectado**: Indicador verde "WhatsApp conectado" + boton "Desconectar"

Tambien mostrar secciones grayed-out para "Instagram (proximamente)" y "Telegram (proximamente)" — esto comunica la vision multi-canal al cliente.

JS: Polling cada 5 segundos a `/api/channels/whatsapp/status` mientras se espera el escaneo del QR. Se detiene cuando conecta.

### 7. Chat UI — Badges en Sidebar (`index.html`)

En la lista de chats del sidebar, las sesiones de WhatsApp real muestran:
- Icono de avatar distinto (telefono vs persona)
- Badge verde "WA" al lado del nombre
- Nombre del contacto si esta disponible: "Juan (5491166662222)" en vez de solo el numero

El endpoint `GET /api/sessions` ya devolvera `channel` y `sender_name` en cada sesion.

### 8. Variables de Entorno

Agregar a `.env.example`:
```
# Evolution API (WhatsApp real)
EVOLUTION_API_URL=http://evolution-api:8080
EVOLUTION_API_KEY=your_evolution_api_key_here
EVOLUTION_INSTANCE_NAME=laformula
```

Si `EVOLUTION_API_KEY` no esta seteada, el canal WhatsApp no se inicializa y el simulador sigue funcionando normalmente. Zero breaking changes.

---

## Orden de Implementacion

Cada fase deja el sistema funcional:

### Fase 1: Persistencia de sesiones
1. Agregar `aiosqlite` a `requirements.txt`
2. Crear `app/sessions.py` con `SessionStore` (SQLite en `data/sessions.db`)
3. Agregar `channel` y `sender_name` a `ChatSession` en `models.py`
4. Refactorizar `main.py` para usar `SessionStore` (async init en startup event)
5. Agregar volumen `data/` a `docker-compose.yml` (cubre SQLite + chroma)
6. **Test**: todo funciona igual, pero sesiones sobreviven restart

### Fase 2: Capa de canales
1. Crear `app/channels/__init__.py`, `base.py`, `manager.py`
2. Inicializar `ChannelManager` en `main.py`
3. Agregar endpoints `/api/channels/whatsapp/status`
4. **Test**: endpoints responden, simulador sigue funcionando

### Fase 3: Integracion Evolution API
1. Crear `app/channels/whatsapp.py`
2. Agregar servicio Evolution API a `docker-compose.yml`
3. Agregar variables a `.env.example` y `.env`
4. Agregar webhook endpoint `POST /api/webhooks/evolution`
5. Agregar endpoints connect/disconnect
6. **Test**: `docker compose up --build`, Evolution API arranca, se puede crear instancia y escanear QR

### Fase 4: Admin UI
1. Agregar tab "Canales" a `admin.html`
2. Implementar UI de QR code y gestion de conexion
3. **Test**: conectar WhatsApp real desde el admin panel

### Fase 5: Chat UI
1. Actualizar sidebar de `index.html` con badges de canal
2. Actualizar response de `GET /api/sessions` con campos nuevos
3. **Test**: mensajes reales de WhatsApp aparecen en el sidebar junto a los del simulador

---

## Verificacion End-to-End

1. `docker compose up --build` — ambos servicios arrancan sin errores
2. Abrir `http://localhost:7070` — simulador funciona como antes
3. Abrir `http://localhost:7070/admin` — ir a tab "Canales"
4. Click "Conectar WhatsApp" — aparece codigo QR
5. Escanear con WhatsApp del celular (Dispositivos vinculados > Vincular dispositivo)
6. Estado cambia a "Conectado" (indicador verde)
7. Enviar mensaje desde otro WhatsApp al numero conectado
8. Verificar que Nico responde automaticamente con RAG
9. Verificar que la conversacion aparece en el sidebar de `http://localhost:7070` con badge "WA"
10. Reiniciar con `docker compose restart agent` — verificar que sesiones persisten
11. Click "Desconectar" en admin — verificar que deja de responder

---

## Agregar Canales Futuros (Instagram/Telegram)

Para agregar un nuevo canal:
1. Crear `app/channels/telegram.py` implementando `BaseChannel`
2. Registrar en `main.py` con `channel_manager.register()`
3. Agregar webhook endpoint `POST /api/webhooks/telegram`
4. Agregar seccion en tab "Canales" del admin
5. Agregar servicio Docker si es necesario

El agente, knowledge base, y session store no se tocan. Solo se agrega el adaptador del canal.
