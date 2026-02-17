# Plan: Feature de Imágenes — Envío de imágenes pre-cargadas por el agente

## Contexto

Mauri envía imágenes de catálogo/productos a sus clientes por WhatsApp (ej: flyer con lista de inyectables y precios). Queremos que el agente Nico pueda hacer lo mismo: cuando un cliente pregunta por un producto, adjuntar automáticamente la imagen correspondiente del catálogo.

**Enfoque elegido**: El agente escribe `[IMAGEN: titulo]` en su respuesta. El backend parsea el marcador, resuelve la URL de la imagen, y la devuelve al frontend. DeepSeek no soporta vision, así que no hay procesamiento de imágenes entrantes.

---

## Archivos nuevos (2)

| Archivo | Propósito |
|---|---|
| `app/images.py` | Registry de imágenes: guardar/listar/buscar/borrar. Filesystem + JSON |
| `app/image_processor.py` | Parseo de marcadores `[IMAGEN: ...]`, resolución de URLs, limpieza de texto |

## Archivos modificados (4)

| Archivo | Cambios |
|---|---|
| `app/main.py` | Mount `/images`, 3 endpoints (upload/list/delete), modificar `POST /api/chat` para post-procesar marcadores |
| `app/static/index.html` | CSS para imágenes inline, modificar `addMessageBubble()` para renderizar imágenes, pasar `data.images` desde `sendMessage()` y `sendAudio()` |
| `app/static/admin.html` | Sección "Imágenes de productos" en tab Conocimiento (upload con titulo/descripción/tags + galería con delete) |
| `config/config.yaml` | Agregar instrucciones `### IMAGENES DE PRODUCTOS:` al system prompt |

## Sin cambios necesarios

`app/agent.py`, `app/knowledge.py`, `app/models.py`, `docker-compose.yml`, `requirements.txt`

---

## Fase 1: Backend — `app/images.py` (nuevo)

Módulo de registry de imágenes usando filesystem + JSON:

```
data/images/
  registry.json          # [{id, title, slug, description, tags, filename, created_at}]
  creatina-mono-abc123.jpg
  catalogo-inyectables-def456.png
  ...
```

Funciones:
- `add_image(file_bytes, original_filename, title, description, tags)` → guarda archivo + agrega a registry
- `list_images()` → lista completa
- `get_image_by_title(title)` → fuzzy match por slug (normaliza acentos, parcial match como fallback)
- `get_image_url(entry)` → `/images/{filename}`
- `delete_image(image_id)` → borra archivo + entry del registry
- `_slugify(text)` → normaliza ñ, acentos, espacios → slug filesystem-safe

## Fase 2: Backend — `app/image_processor.py` (nuevo)

Post-procesador de respuestas del agente:

```python
IMAGE_MARKER_RE = re.compile(r'\[IMAGEN:\s*([^\]]+)\]', re.IGNORECASE)

def process_reply(raw_reply: str) -> dict:
    # 1. Encuentra todos los [IMAGEN: ...] en el texto
    # 2. Para cada uno, busca la imagen via get_image_by_title()
    # 3. Limpia los marcadores del texto
    # 4. Retorna:
    #    {
    #      "text": "texto limpio sin marcadores",
    #      "images": [{"title": ..., "url": "/images/...", "filename": ...}],
    #      "unresolved_images": [...],  # marcadores que no matchearon
    #      "raw_reply": "texto original con marcadores"
    #    }
```

## Fase 3: Backend — Modificar `app/main.py`

### 3A. Mount estático para servir imágenes

Antes del mount de `/static`, agregar:
```python
os.makedirs("data/images", exist_ok=True)
app.mount("/images", StaticFiles(directory="data/images"), name="images")
```

**Importante**: este mount debe ir ANTES del mount de `/static` para que no sea capturado por el catch-all.

### 3B. Endpoints de imágenes

- `POST /api/images/upload` — Recibe `file` (UploadFile) + `title` + `description` + `tags` (Form). Guarda imagen con `images.add_image()`, indexa descripción en ChromaDB con `kb.add_text()` usando `doc_type="image"` y source `img:{title}`

  Texto indexado en RAG:
  ```
  IMAGEN DISPONIBLE: {title}
  Descripcion: {description}
  Tags: {tags}
  Para mostrar esta imagen en la respuesta, escribi: [IMAGEN: {title}]
  ```

- `GET /api/images` — Lista todas las imágenes registradas
- `DELETE /api/images/{image_id}` — Borra imagen del filesystem, del registry, y del ChromaDB (busca doc con `filename == "img:{title}"`)

### 3C. Modificar `POST /api/chat`

Después de obtener `reply` del `agent.chat()`:
1. Llamar `process_reply(reply)`
2. Guardar texto limpio (sin marcadores) en session history
3. Retornar response extendido:

```json
{
  "reply": "texto limpio",
  "images": [{"title": "...", "url": "/images/..."}],
  "timestamp": "14:30",
  "debug": {...}
}
```

Backward compatible: `reply` sigue siendo string de texto, `images` es campo nuevo.

## Fase 4: System Prompt — Modificar `config/config.yaml`

Agregar al final del system_prompt:

```
### IMAGENES DE PRODUCTOS:
- Tenes acceso a imagenes de productos del catalogo
- Cuando el contexto RAG te trae un resultado con "IMAGEN DISPONIBLE:", podes incluir esa imagen en tu respuesta
- Para adjuntar una imagen, escribi EXACTAMENTE: [IMAGEN: titulo-de-la-imagen]
- El titulo debe coincidir con el que aparece en "IMAGEN DISPONIBLE:" del contexto RAG
- Solo podes usar imagenes que aparecen en el contexto. NO inventes titulos de imagenes
- Usa imagenes cuando el cliente pregunta por un producto y tenes la imagen disponible
- Ejemplo: "Mira, te muestro lo que tenemos! [IMAGEN: Catalogo Inyectables] Ahi tenes todos los precios actualizados."
```

## Fase 5: Frontend — Modificar `app/static/index.html`

### 5A. CSS

```css
.message .msg-image {
  max-width: 100%;
  border-radius: 6px;
  margin: 6px 0;
  cursor: pointer;
}
```

### 5B. Modificar `addMessageBubble()` (línea 713)

Agregar parámetro `images` y renderizar después del texto:

```javascript
function addMessageBubble(role, content, time, debugData, images) {
  // ... existing code ...
  let html = `${escapeHtml(content)}`;

  if (images && images.length > 0) {
    images.forEach(img => {
      html += `<img class="msg-image" src="${img.url}" alt="${escapeHtml(img.title)}" onclick="window.open('${img.url}','_blank')">`;
    });
  }

  html += `<div class="time">${now}</div>`;
  // ... rest of debug code ...
}
```

### 5C. Modificar callers

En `sendMessage()` (línea 704) y `sendAudio()` (línea 776):
```javascript
addMessageBubble('assistant', data.reply, data.timestamp, data.debug, data.images);
```

## Fase 6: Admin UI — Modificar `app/static/admin.html`

Agregar sección "Imágenes de productos" en el tab Conocimiento (antes de "Documentos indexados"):

- Formulario: file input (accept="image/*") + título + descripción (textarea) + tags
- Galería: grid de cards con thumbnail, título, descripción truncada, botón eliminar
- JS: `uploadImage()`, `loadImages()`, `deleteImage()`
- CSS: `.img-card` con thumbnail, info, acciones

Agregar `loadImages()` al bloque INIT.

---

## Flujo completo (ejemplo)

1. Admin sube imagen "Catálogo Inyectables" con descripción "Lista de precios de inyectables: Propionato, Enantato, Cipionato..."
2. Se guarda en `data/images/catalogo-inyectables-abc123.png`
3. Se indexa en ChromaDB: "IMAGEN DISPONIBLE: Catálogo Inyectables..."
4. Cliente pregunta: "Che, qué inyectables tienen?"
5. RAG devuelve chunk con "IMAGEN DISPONIBLE: Catálogo Inyectables" + instrucción del marcador
6. Agente responde: "Buenas! Te paso el catálogo actualizado [IMAGEN: Catálogo Inyectables] Ahí tenés todos los inyectables con precios."
7. Backend parsea `[IMAGEN: Catálogo Inyectables]` → resuelve a `/images/catalogo-inyectables-abc123.png`
8. API retorna `{reply: "Buenas! Te paso el catálogo...", images: [{title: "...", url: "/images/..."}]}`
9. Chat UI muestra texto + imagen inline en el bubble

## Verificación

1. Subir imagen desde admin > Conocimiento > "Imágenes de productos" → verificar que aparece en la galería y en la lista de documentos RAG
2. Preguntar al agente sobre ese producto → verificar que el RAG trae el chunk con "IMAGEN DISPONIBLE"
3. Verificar que el agente incluye `[IMAGEN: ...]` en su respuesta
4. Verificar que el chat UI muestra la imagen inline después del texto
5. Eliminar imagen desde admin → verificar que desaparece de galería, RAG, y filesystem
6. Verificar que un marcador con título inexistente se ignora silenciosamente
