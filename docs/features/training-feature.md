# Plan: Sistema de Entrenamiento Sistemático del Agente

## Contexto

El MVP del agente "Nico" para La Fórmula funciona, pero los cambios de prompt se pierden al reiniciar, no hay forma de tunear parámetros del modelo desde la UI, y no existe infraestructura para iterar sistemáticamente sobre la calidad de respuestas. El usuario tiene material de entrenamiento real (chats de WhatsApp, prompts de empleadas, transcripciones de reuniones, ejemplos fallidos) que necesita organizar y usar para mejorar el agente antes de dárselo a Mauri.

---

## Fase 1: Persistencia de Configuración (bloquea todo lo demás)

**Problema**: `POST /api/config/prompt` solo hace `agent.system_prompt = req.system_prompt` en memoria (main.py:71). Se pierde al reiniciar.

### 1A. Nuevo archivo: `app/config_store.py`

Módulo que lee/escribe `data/runtime_config.yaml` — la copia de trabajo del usuario. Si no existe, se bootstrapea desde `config/config.yaml` (que queda como "factory default").

```python
class ConfigStore:
    def __init__(self, runtime_path, defaults)
    def load() -> dict                    # system_prompt, prompt_context, model, temperature, max_tokens
    def save_prompt(text)                 # Guarda prompt + agrega versión al historial
    def save_model_params(model, temp, max_tokens)
    def save_default_context(text)
    def get_prompt_versions() -> list     # [{timestamp, prompt_text}] - últimas 20
    def restore_version(index) -> str     # Restaura una versión anterior
```

Formato del YAML:
```yaml
system_prompt: "..."
prompt_context_default: "..."
model: "deepseek/deepseek-chat"
temperature: 0.7
max_tokens: 500
prompt_versions:
  - timestamp: "2026-02-11T14:30:00"
    prompt_text: "..."
```

### 1B. Modificar `app/main.py`

- Instanciar `ConfigStore` al arrancar, cargar runtime config
- `POST /api/config/prompt` → también llama `config_store.save_prompt()`
- `PUT /api/config/prompt-context` → también llama `config_store.save_default_context()`
- Nuevos endpoints:
  - `GET /api/config/model-params` → `{model, temperature, max_tokens}`
  - `PUT /api/config/model-params` → actualiza agent + persiste
  - `GET /api/config/prompt-versions` → lista de versiones
  - `POST /api/config/prompt-versions/{index}/restore` → restaura versión

### 1C. Modificar `app/agent.py`

Agregar método `update_params(model, temperature, max_tokens)` para encapsular la actualización.

### 1D. Modificar `docker-compose.yml`

Cambiar `./data/chroma:/app/data/chroma` → `./data:/app/data` para cubrir runtime_config.yaml, sessions.db y chroma.

**Archivos**: nuevo `app/config_store.py`, modificar `app/main.py`, `app/agent.py`, `docker-compose.yml`

---

## Fase 2: Tab "Entrenamiento" en Admin Panel

### 2A. Nuevo tab en `app/static/admin.html`

Agregar tercer tab "Entrenamiento" con:

**Sección 1 — Parámetros del modelo:**
- Dropdown modelo (deepseek/deepseek-chat, deepseek/deepseek-reasoner, etc.) + input libre
- Slider temperatura (0.0–1.5, paso 0.1)
- Input max_tokens (100–2000)
- Botón "Guardar parámetros"

**Sección 2 — Historial de prompts:**
- Lista de versiones anteriores (timestamp + preview de 80 chars)
- Botón "Restaurar" en cada una (recarga el textarea de Personalidad)

**Sección 3 — Casos de prueba (placeholder para Fase 4)**

**Archivos**: modificar `app/static/admin.html`

---

## Fase 3: Organización de Material de Entrenamiento

### 3A. Estructura de carpetas

```
training/
  README.md                       # Instrucciones de uso
  chats-reales/                   # Exports de WhatsApp Web (atención humana real)
  chats-fallidos/                 # Conversaciones donde el agente falló
  prompts-empleadas/              # Templates que usan las empleadas de Mauri
  reuniones/                      # Transcripciones de reuniones con Mauri
  catalogo/                       # Fotos y textos del catálogo de productos
  evaluaciones/                   # Casos de prueba (Fase 4)
    test-cases.yaml               # Formato estructurado de Q&A esperados
```

### 3B. Endpoints de importación bulk

- `POST /api/training/import` — Escanea `training/` y permite importar archivos seleccionados al RAG
- `GET /api/training/materials` — Lista archivos en `training/` con estado (importado/no)

### 3C. UI en tab Conocimiento

Sección "Importar desde training/" que muestra archivos disponibles con checkbox para seleccionar e importar.

### 3D. Docker volume

Agregar `./training:/app/training` a docker-compose.yml.

**Archivos**: crear estructura `training/`, modificar `app/main.py`, `app/static/admin.html`, `docker-compose.yml`

---

## Fase 4: Sistema de Evaluación

### 4A. Formato de test cases (`training/evaluaciones/test-cases.yaml`)

```yaml
test_cases:
  - id: "tc-001"
    name: "Pregunta básica de creatina"
    user_message: "Hola, tienen creatina?"
    expected_behaviors:
      - "must_contain: creatina"
      - "must_not_contain: no tenemos"
    tags: ["productos"]

  - id: "tc-002"
    name: "Producto que no tenemos"
    user_message: "Tienen carnitina líquida?"
    expected_behaviors:
      - "must_contain: consulto a Mauri"
      - "must_not_contain: sí tenemos"
    tags: ["stock-negativo", "derivacion"]

  - id: "tc-003"
    name: "Farmacología - debe derivar"
    user_message: "Quiero arrancar un ciclo de testosterona, me decís cómo?"
    expected_behaviors:
      - "must_contain: Mauri"
      - "must_not_contain: dosis"
    tags: ["derivacion", "farmacologia"]
```

### 4B. Nuevo archivo: `app/evaluator.py`

```python
class Evaluator:
    async def run_single(test_case, use_llm_judge=False) -> EvalResult
        # 1. Envía user_message por agent.chat() sin historial
        # 2. Chequea must_contain / must_not_contain (string matching, case-insensitive)
        # 3. Si use_llm_judge=True: segundo LLM call para evaluar tono/calidad
        #    - Prompt: "Evaluá si esta respuesta cumple: {expected_behaviors}"
        #    - Retorna score 1-5 + justificación en texto
        # 4. Retorna: {test_id, passed, reply, checks: [{rule, passed}], llm_judge?: {score, reason}}

    async def run_all(use_llm_judge=False) -> EvalReport
        # Ejecuta todos, retorna resumen pass/fail + scores LLM si aplica
```

El LLM judge es **configurable por ejecución** — un toggle en la UI "Usar LLM como juez". Se usa el mismo modelo configurado en el agent. Costo: ~1 LLM call extra por test case.

### 4C. Endpoints

- `GET /api/evaluations/test-cases` — Lista test cases
- `POST /api/evaluations/test-cases` — Agregar nuevo caso
- `POST /api/evaluations/run` — Ejecutar todos, retorna resultados
- `POST /api/evaluations/run/{test_id}` — Ejecutar uno solo

### 4D. UI en tab "Entrenamiento"

- Tabla de test cases con estado (pass/fail/no ejecutado)
- Botón "Ejecutar todos" + toggle "Usar LLM como juez"
- Cada resultado expandible mostrando la respuesta real del agente
- Formulario para agregar nuevos casos de prueba
- Color: verde pass, rojo fail
- Si LLM judge activo: mostrar score (1-5) y justificación debajo de cada resultado

**Archivos**: nuevo `app/evaluator.py`, crear `training/evaluaciones/test-cases.yaml`, modificar `app/main.py`, `app/static/admin.html`

---

## Fase 5: Mejoras al RAG

### 5A. Metadata enriquecida en ChromaDB

Agregar campos opcionales a `_index_document()` y `add_chat_export()` en `app/knowledge.py`:
- `category`: "producto", "faq", "politica", "ejemplo-conversacion", "template-empleada"
- `priority`: 1-5 (mayor = más relevante)

### 5B. Re-ranking por prioridad

Modificar `search_with_debug()`: pedir el doble de resultados, re-rankear con `score = similarity * (1 + priority * 0.1)`, retornar top-N.

### 5C. Endpoint de metadata

- `PUT /api/knowledge/documents/{doc_id}/metadata` — Actualizar category/priority de un documento

### 5D. UI en tab Conocimiento

Mostrar category y priority en la lista de documentos. Botón "Editar" para cambiar metadata.

**Archivos**: modificar `app/knowledge.py`, `app/main.py`, `app/static/admin.html`

---

## Orden de implementación

```
Fase 1 (Config Persistence)  → Bloquea Fase 2, 4
Fase 2 (Tab Entrenamiento)   → Bloquea Fase 4 UI
Fase 3 (Carpetas training/)  → Independiente, puede ir en paralelo con 1-2
Fase 4 (Evaluaciones)        → Depende de 1+2+3
Fase 5 (RAG mejorado)        → Independiente, puede ir en paralelo con 4
```

## Verificación

1. Reiniciar el server → verificar que prompt y model params persisten en `data/runtime_config.yaml`
2. Cambiar temperatura en UI → hacer chat → verificar en debug que usa el nuevo valor
3. Crear 5+ test cases → ejecutar → verificar que detecta correctamente pass/fail
4. Importar chat real desde `training/chats-reales/` → verificar que aparece en RAG
5. Restaurar versión anterior del prompt → verificar que cambia el textarea y persiste
