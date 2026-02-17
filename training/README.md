# Material de Entrenamiento

Organizar archivos en las subcarpetas segun el tipo:

| Carpeta | Contenido |
|---|---|
| `chats-reales/` | Exports de WhatsApp Web (atencion humana real de Mauri o empleadas) |
| `chats-fallidos/` | Conversaciones donde el agente respondio mal |
| `prompts-empleadas/` | Templates y guiones que usan las empleadas |
| `reuniones/` | Transcripciones de reuniones con Mauri |
| `catalogo/` | Fotos y textos del catalogo de productos |
| `evaluaciones/` | Casos de prueba en formato YAML (`test-cases.yaml`) |

## Formatos soportados para importar al RAG

- `.txt` — Texto plano (notas, transcripciones)
- `.pdf` — Documentos PDF
- `.chat.txt` — Exports de WhatsApp (se detecta por extension)

## Como importar

1. Colocar archivos en la carpeta correspondiente
2. Ir al panel de admin > Conocimiento > "Importar desde training/"
3. Seleccionar los archivos y hacer click en "Importar seleccionados"
