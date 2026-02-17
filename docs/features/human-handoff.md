# Plan: Human Handoff Feature

**Estado: IMPLEMENTADO**

## Context

El system prompt de Nico ya menciona "derivar a Mauri" en ciertos casos (farmacologia, reclamos, datos que no tiene), pero no existe ningun mecanismo real para hacerlo. Los mensajes siguen pasando por el LLM siempre. Esta feature implementa el circuito completo: clasificacion de intenciones, handoff configurable por intencion, pausa del bot, interfaz de operador, auto-reset por timeout, y retorno al bot.

---

## Modelo de estados

```
[bot] --intent con handoff:true--> [handoff_pending] --operador toma--> [human] --devolver--> [bot]
          ^                              ^                                  |
          |----timeout/nueva conv--------|--manual desde admin--------------|
```

- **bot**: Nico responde automaticamente (estado por defecto)
- **handoff_pending**: Bot pausado, esperando que el operador tome la conversacion
- **human**: Operador respondiendo activamente

---

## 1. Sistema de clasificacion de intenciones

Cada vez que el LLM responde, clasifica el mensaje del usuario con una etiqueta de intencion. Cada clasificacion tiene un toggle configurable `handoff: true/false` que determina si esa intencion escala automaticamente a un humano.

### Clasificaciones predefinidas

| ID | Label (visible en admin) | Handoff por defecto | Ejemplo de mensaje del cliente |
|---|---|---|---|
| `posible_comprador` | Posible comprador | false | "Quiero comprar creatina", "cuanto sale la whey?" |
| `consulta_producto` | Pregunta por producto | false | "Tienen BCAA?", "que proteina me recomendas?" |
| `problema_entrega` | Problema con entrega | **true** | "No me llego el pedido", "me mandaron otra cosa" |
| `reclamo` | Reclamo | **true** | "Estoy enojado", "quiero devolucion" |
| `farmacologia` | Farmacologia / Quimica | **true** | "Que ciclo me recomendas?", "puedo mezclar con..." |
| `hablar_dueno` | Quiere hablar con Mauri | **true** | "Pasame con Mauri", "quiero hablar con una persona" |
| `precio_stock` | Precio o stock no disponible | **true** | (el bot no tiene el dato y necesita consultar) |
| `consulta_entrenamiento` | Consulta de entrenamiento | false | "Como hago para ganar masa?", "rutina de pecho?" |
| `saludo` | Saludo / Inicio | false | "Hola", "buenas", "che que tal" |
| `otro` | Otro | false | Cualquier cosa que no entre en las anteriores |

El admin puede:
- **Cambiar el toggle handoff** de cualquier clasificacion (ej: activar handoff para "Posible comprador" si Mauri quiere cerrar ventas personalmente)
- **Agregar nuevas clasificaciones** desde el panel (se agregan al prompt automaticamente)
- **No puede eliminar** las predefinidas (solo togglear)

### Config (`config/config.yaml`) - nueva seccion:

```yaml
agent:
  # ... model, temperature, max_tokens, system_prompt ...

  handoff:
    timeout_minutes: 30
    reset_on_greeting: true

  intents:
    posible_comprador:
      label: "Posible comprador"
      handoff: false
    consulta_producto:
      label: "Pregunta por producto"
      handoff: false
    problema_entrega:
      label: "Problema con entrega"
      handoff: true
    reclamo:
      label: "Reclamo"
      handoff: true
    farmacologia:
      label: "Farmacologia / Quimica"
      handoff: true
    hablar_dueno:
      label: "Quiere hablar con Mauri"
      handoff: true
    precio_stock:
      label: "Precio o stock no disponible"
      handoff: true
    consulta_entrenamiento:
      label: "Consulta de entrenamiento"
      handoff: false
    saludo:
      label: "Saludo / Inicio"
      handoff: false
    otro:
      label: "Otro"
      handoff: false
```

### System prompt - instruccion de clasificacion:

Se agrega al system prompt (reemplaza la seccion actual de DERIVACION A MAURI):

```
### CLASIFICACION DE INTENCION (OBLIGATORIO)
- En CADA respuesta que des, empeza con una etiqueta de intencion entre corchetes.
- Etiquetas disponibles: posible_comprador, consulta_producto, problema_entrega,
  reclamo, farmacologia, hablar_dueno, precio_stock, consulta_entrenamiento, saludo, otro
- Formato: [INTENT:nombre_intent] seguido de tu respuesta normal
- Ejemplos:
  [INTENT:consulta_producto] Buenas! Si, tenemos creatina monohidratada...
  [INTENT:problema_entrega] Uh, que bajon. Dejame que le consulto a Mauri para resolver...
  [INTENT:posible_comprador] Genial! La whey concentrada esta a $X. Te separo uno?
  [INTENT:saludo] Buenas! Aca Nico de La Formula. En que te puedo ayudar?
- SIEMPRE incluir la etiqueta. El sistema la usa para ruteo interno, el cliente no la ve.
- Si detectas que la consulta requiere a Mauri (reclamo, farmacologia, dato que no tenes),
  usa la etiqueta correspondiente Y en tu mensaje avisale al cliente que lo vas a derivar.
```

### Flujo en el backend:

```
1. LLM responde: "[INTENT:problema_entrega] Uh, que bajon. Dejame que le aviso a Mauri..."
2. Backend parsea el tag con regex: \[INTENT:(\w+)\]
3. Stripea el tag del reply visible al usuario
4. Guarda session.last_intent = "problema_entrega"
5. Busca el intent en config["agent"]["intents"]
6. Si intent.handoff == true:
   → session.mode = "handoff_pending"
   → session.handoff_reason = intent.label ("Problema con entrega")
   → session.handoff_at = now()
7. Si intent.handoff == false:
   → respuesta normal, sin cambio de modo
8. Si el tag no matchea ningun intent conocido:
   → log warning, tratar como "otro"
```

---

## 2. Auto-reset de handoff

### Timeout configurable

En cada mensaje entrante (`POST /api/chat` o webhook), **antes** de procesar:
- Si `session.mode` es `handoff_pending` o `human`
- Y el ultimo mensaje fue hace mas de `handoff.timeout_minutes`
- → Auto-reset a `bot`, agregar mensaje de sistema, procesar el mensaje normalmente

```python
def check_handoff_timeout(session, config):
    if session.mode not in ("handoff_pending", "human"):
        return False
    if not session.handoff_at:
        return False
    timeout = config.get("agent", {}).get("handoff", {}).get("timeout_minutes", 30)
    elapsed = (datetime.now() - datetime.fromisoformat(session.handoff_at)).total_seconds() / 60
    return elapsed >= timeout
```

### Reset por nueva conversacion

Si `handoff.reset_on_greeting` es true y el mensaje entrante matchea un patron de saludo (regex: `^(hola|buenas|buen dia|hey|que tal)`), resetear la sesion a bot.

---

## 3. Data Model (`app/models.py`)

**ChatMessage** - agregar campo `source`:
```python
source: str = ""  # "bot" | "human" | "system" | "" (user msgs)
```

**ChatSession** - agregar campos:
```python
mode: str = "bot"              # "bot" | "handoff_pending" | "human"
handoff_reason: str = ""       # razon del handoff (label del intent o "manual")
handoff_at: str = ""           # ISO timestamp de cuando se activo el handoff
last_intent: str = ""          # ultimo intent clasificado por el LLM
```

**Nuevos request models**:
```python
class HandoffRequest(BaseModel):
    mode: str  # "handoff_pending" | "human" | "bot"
    reason: str = ""

class OperatorReplyRequest(BaseModel):
    message: str
```

---

## 4. Backend - Modificar endpoints existentes (`app/main.py`)

### 4a. `POST /api/chat` (linea 148)

Nuevo flujo completo:

```
1. Recibir mensaje, buscar session
2. CHECK AUTO-RESET: si session en handoff y paso el timeout → reset a bot
3. CHECK GREETING RESET: si en handoff y mensaje es saludo → reset a bot
4. Si session.mode es handoff/human → guardar msg, retornar {reply:null, handoff:true}
5. Llamar agent.chat() como siempre
6. PARSEAR INTENT: regex [INTENT:xxx] en el reply
   - Stripear tag del reply
   - Guardar session.last_intent
   - Buscar intent en config → si handoff:true → session.mode = handoff_pending
7. Guardar assistant msg con source="bot"
8. Retornar {reply, mode, handoff, intent, timestamp, debug?}
```

### 4b. `GET /api/sessions` (linea 90)

- Agregar query param opcional `mode` para filtrar
- Incluir `mode`, `handoff_reason`, `handoff_at`, `last_intent` en cada session

### 4c. `GET /api/sessions/{id}` (linea 103)

- Ya retorna el session completo, solo necesita los campos nuevos del modelo

---

## 5. Backend - Nuevos endpoints (`app/main.py`)

### 5a. `POST /api/sessions/{session_id}/handoff`

Body: `HandoffRequest` (mode + reason)

Logica:
- Validar session existe
- Cambiar `session.mode` al modo pedido
- Si `handoff_pending`: setear reason y timestamp, agregar mensaje de sistema
- Si `bot`: limpiar reason/timestamp, agregar mensaje "[Sistema] Nico retomo la conversacion"
- Retornar session actualizada

### 5b. `POST /api/sessions/{session_id}/reply`

Body: `OperatorReplyRequest` (message)

Logica:
- Validar session existe y modo es `handoff_pending` o `human`
- Si modo es `handoff_pending`, auto-transicionar a `human`
- Crear `ChatMessage(role="assistant", content=message, source="human")`
- Appendear a session.messages
- Retornar mensaje con timestamp
- (Futuro: si es WhatsApp, enviar via Evolution API)

### 5c. `GET /api/handoffs/pending`

Retorna `{"count": N, "sessions": [{id, phone_number, handoff_reason, handoff_at, last_intent}]}`

### 5d. `GET /api/config/intents` y `PUT /api/config/intents`

- GET: retorna la lista de intents con sus labels y handoff:true/false
- PUT: actualiza el handoff:true/false de intents individuales (para que el admin pueda togglrear desde el UI sin tocar yaml)

Estos se guardan in-memory (como el prompt). En el futuro se pueden persistir.

---

## 6. Frontend - Simulador (`app/static/index.html`)

Cambios minimos:

- **`sendMessage()`**: Manejar response con `handoff: true` → mostrar burbuja de sistema + banner de "esperando operador"
- **`addSystemBubble(text)`**: Burbujas centradas grises para notificaciones de sistema
- **`showHandoffBanner(show)`**: Banner encima del input cuando session en handoff/human
- **`selectSession()`**: Checkear mode y actualizar UI
- **`renderChatList()`**: Dot de color al lado de sesiones (rojo=pending, amarillo=human)
- En handoff/human: usuario puede escribir, mensajes se guardan, sin respuesta del bot

---

## 7. Frontend - Admin (`app/static/admin.html`)

### 7a. Nuevo tab "Conversaciones" (4to tab)

**Panel izquierdo** - Lista de sesiones:
- Dot rojo + "Pendiente" para `handoff_pending`
- Dot amarillo + "Humano" para `human`
- Dot verde + "Bot" para `bot`
- Phone, ultimo mensaje, intent label, tiempo desde handoff

**Panel derecho** - Al seleccionar sesion:
- Header: phone, estado, intent tag
- Historial de mensajes con iconos por source (robot/persona)
- Input + boton enviar (habilitado en handoff_pending/human)
- Botones de accion:
  - `handoff_pending`: "Tomar conversacion" (→ human)
  - `human`: "Devolver al bot" (→ bot)
  - `bot`: "Derivar manualmente" (→ handoff_pending)

**Polling**:
- `GET /api/sessions` cada 5s cuando tab activo
- `GET /api/handoffs/pending` cada 10s siempre (para badge)
- Badge rojo en tab con cantidad pendientes
- Title del documento: `(N) Admin - La Formula`

### 7b. Config de intents en tab "Personalidad"

Agregar una seccion al tab Personalidad existente, debajo de "Contexto adicional":

**"Clasificacion de intenciones"** - Tabla visual:

```
| Clasificacion              | Derivar a humano |
|----------------------------|------------------|
| Posible comprador          | [ ] off          |
| Pregunta por producto      | [ ] off          |
| Problema con entrega       | [x] ON           |
| Reclamo                    | [x] ON           |
| Farmacologia / Quimica     | [x] ON           |
| Quiere hablar con Mauri    | [x] ON           |
| Precio o stock no disp.    | [x] ON           |
| Consulta de entrenamiento  | [ ] off          |
| Saludo / Inicio            | [ ] off          |
| Otro                       | [ ] off          |
```

- Cada fila tiene un toggle switch (on/off) para handoff
- Toggle ON = fondo rojo suave, toggle OFF = fondo verde suave
- Al cambiar un toggle → `PUT /api/config/intents` automaticamente
- Boton "+ Agregar clasificacion" abre un mini form (ID + label) para crear nuevas

**"Configuracion de handoff"** - Debajo de la tabla:

- Input numerico: "Timeout de handoff (minutos)" → default 30
- Checkbox: "Resetear al detectar saludo nuevo" → default on
- Boton guardar → `PUT /api/config/handoff`

---

## Orden de implementacion

1. **Models** (`app/models.py`) - Agregar campos a ChatSession, ChatMessage, nuevos request models
2. **Config** (`config/config.yaml`) - Agregar seccion `intents` y `handoff` al yaml
3. **System prompt** (`config/config.yaml`) - Agregar instrucciones de INTENT tagging al prompt
4. **Main.py - `/api/chat`** - Auto-reset por timeout/saludo + parseo de intent + handoff condicional
5. **Main.py - `/api/sessions`** - Mode en responses + filtro
6. **Main.py - nuevos endpoints** - handoff, reply, pending, intents config
7. **index.html** - System bubbles, handoff banner, mode-aware UI
8. **admin.html - tab Conversaciones** - Panel de operador completo
9. **admin.html - tab Personalidad** - Config de intents (toggles handoff) + timeout

---

## Archivos a modificar

| Archivo | Cambio |
|---|---|
| `app/models.py` | Campos mode/handoff/intent en ChatSession, source en ChatMessage, request models |
| `app/main.py` | Logica /api/chat, 4 endpoints nuevos, modificar list_sessions |
| `app/config.py` | Cargar seccion intents y handoff de config |
| `config/config.yaml` | Seccion intents, handoff, instrucciones INTENT en prompt |
| `app/static/index.html` | System bubbles, handoff banner, mode dots |
| `app/static/admin.html` | Tab Conversaciones + config intents en Personalidad |

---

## Verificacion

1. **Test intent sin handoff**: Enviar "tienen creatina?" → LLM responde con `[INTENT:consulta_producto]` → intent se parsea y guarda, bot responde normal (handoff:false para ese intent)
2. **Test intent con handoff**: Enviar "tengo un problema con mi pedido" → `[INTENT:problema_envio]` → handoff:true → sesion pasa a handoff_pending → banner en simulador → aparece en admin
3. **Test toggle intent**: En admin, cambiar `consulta_producto` a handoff:true → repetir test 1 → ahora SI dispara handoff
4. **Test auto-reset por timeout**: Poner timeout en 1 min, disparar handoff, esperar >1 min, enviar mensaje → sesion auto-reset a bot, Nico responde
5. **Test reset por saludo**: Con sesion en handoff, enviar "Hola" → se resetea a bot
6. **Test operador responde**: Desde admin, tomar conversacion → escribir → aparece en simulador
7. **Test devolver al bot**: Desde admin, devolver → mensaje nuevo → Nico responde
8. **Test manual handoff**: Desde admin, derivar manualmente sesion en bot → se pausa
