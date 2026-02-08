# Feature: Editor de Prompt + Tabs en Admin

**Estado: COMPLETADA**

## Contexto

Para la demo con Mauri necesitamos que el admin (`/admin`) se sienta como un producto real, no un prototipo. Dos features clave:

1. **Editor de Prompt** — Mauri puede editar cómo habla Nico (tono, reglas, descuentos) desde el admin y los cambios aplican al instante
2. **Tabs** — Reorganizar el admin en pestañas (Personalidad | Conocimiento) para que se vea profesional

El editor de prompt es **en memoria** — no escribe a `config.yaml`. Los cambios se pierden al reiniciar el server (aceptable para MVP).

## Archivos Modificados

| Archivo | Cambios |
|---------|---------|
| `config/config.yaml` | Fix nombre: "La Fórmula" → "La Fórmula" en business.name |
| `app/main.py` | +2 endpoints: `GET/POST /api/config/prompt` con `UpdatePromptRequest` (Pydantic). Prompt se guarda en memoria via `agent.system_prompt` |
| `app/static/admin.html` | Reescrito completo: +editor de prompt, +tab system (Personalidad / Conocimiento), +CSS tabs, header cambiado a "Panel de Administracion" |
| `app/static/index.html` | Fix fallbacks hardcodeados: title, sidebar header, chat header → "La Fórmula" |

## Endpoints Nuevos

### `GET /api/config/prompt`
Retorna el system prompt actual del agente (en memoria).
```json
{ "system_prompt": "### IDENTIDAD Y TONO\n- Sos Nico..." }
```

### `POST /api/config/prompt`
Actualiza el prompt en memoria. No toca disco.
```json
// Request
{ "system_prompt": "...nuevo texto..." }
// Response
{ "ok": true }
```

## UI — Editor de Prompt

- Textarea monospace (min-height 300px) con el prompt actual
- Botón "Guardar cambios"
- Indicador: "Sin cambios" / "Cambios sin guardar" / "Guardado"
- Se carga con `loadPrompt()` al init

## UI — Tabs

Dos pestañas:
- **Personalidad**: Editor de prompt
- **Conocimiento**: Todo lo existente (PDF, audio, chat WA, notas, documentos)

## Verificación

1. Admin `/admin` → se ven 2 tabs
2. Tab Personalidad → textarea con prompt, editar, guardar → toast "Prompt actualizado"
3. Ir al chat → probar que el cambio se refleja en las respuestas
4. Tab Conocimiento → todas las funciones de KB siguen funcionando
5. Reiniciar server → prompt vuelve al original de config.yaml

## Notas de Implementacion

- El botón "Guardar cambios" está deshabilitado hasta que se detecta un cambio en el textarea (compara contra `originalPrompt`)
- El indicador de estado cambia a naranja ("Cambios sin guardar") cuando el texto difiere del original
- Los emojis en `TYPE_ICONS` se usan con unicode escapes (`\u{1F4C4}`) para evitar problemas de encoding
- El tab default al cargar es "Personalidad"
