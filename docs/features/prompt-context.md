# Feature: Prompt context (por sesión y por defecto)

**Estado: IMPLEMENTADO**

## Contexto

Texto extra que se inyecta en el system prompt antes de llamar al modelo. Sirve para dar contexto por sesión (ej: “este cliente es Juan, prefiere tuteo”) o reglas de demo (“hoy hay 10% en creatina”).

- **Por sesión**: Se guarda en memoria por sesión (mismo tiempo de vida que la sesión). En el chat se muestra un bloque colapsable “Contexto para Nico” editable; al enviar mensaje se usa ese contexto para esa sesión.
- **Por defecto**: En Admin se puede setear un “contexto por defecto” que se aplica a **sesiones nuevas** (también en memoria, se pierde al reiniciar).

## Archivos modificados

| Archivo | Cambios |
|---------|---------|
| `app/models.py` | `ChatSession.prompt_context`, `SendMessageRequest.prompt_context` opcional |
| `app/agent.py` | `chat(..., prompt_context="")`, inyección en system prompt; debug con system completo |
| `app/main.py` | `default_prompt_context`, GET/PUT `/api/config/prompt-context`, PUT `/api/sessions/{id}/prompt-context`, `/api/chat` actualiza y usa contexto |
| `app/static/admin.html` | Sección “Contexto por defecto para nuevas sesiones” en tab Personalidad |
| `app/static/index.html` | Bloque colapsable “Contexto para Nico”, textarea editable, Guardar, envío de contexto en cada mensaje |

## API

- `GET /api/config/prompt-context` → `{ "prompt_context": "..." }`
- `PUT /api/config/prompt-context` → body `{ "prompt_context": "..." }`
- `PUT /api/sessions/{session_id}/prompt-context` → body `{ "prompt_context": "..." }`
- `POST /api/chat` → body puede incluir `prompt_context`; si viene, se actualiza la sesión y se usa en la llamada al modelo.

## Debug viewer

El “System prompt completo” en el debug técnico muestra el contenido real enviado al modelo (base + `--- CONTEXTO ADICIONAL ---` + contexto de sesión).
