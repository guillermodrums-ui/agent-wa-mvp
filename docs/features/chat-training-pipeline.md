# Pipeline de Entrenamiento con Chats Reales de WhatsApp

## Contexto
Mauri y sus empleadas atienden clientes por WhatsApp manualmente. Queremos exportar esos chats reales, analizarlos y usar los patrones para:
- Mejorar el system prompt de Nico con ejemplos reales de tono, ventas y manejo de objeciones
- Indexar conversaciones reales en el RAG como ejemplos de referencia
- Generar test cases automáticos basados en preguntas reales de clientes

## Cómo exportar chats desde WhatsApp
1. Abrir el chat en WhatsApp (Web o app)
2. Menú (⋮) → "Exportar chat" → "Sin multimedia"
3. Guardar el `.txt` en `training/chats-reales/` (ventas exitosas) o `training/chats-fallidos/` (ventas perdidas)
4. Priorizar: ventas cerradas > asesoramiento > objeciones > fallidos

## Archivos Nuevos

### 1. `app/chat_parser.py` (~200 líneas)
Parser puro de Python (sin LLM) para exports de WhatsApp:
- Detecta formatos: `[fecha] Sender: msg` y `fecha - Sender: msg`
- Maneja mensajes multi-línea
- Filtra mensajes de sistema (cifrado, notificaciones de grupo)
- Agrupa en turnos (mensajes consecutivos del mismo sender)
- Empareja en exchanges (pregunta cliente + respuesta agente)
- Calcula métricas básicas (cantidad de mensajes, duración, etc.)

### 2. `app/chat_analyzer.py` (~250 líneas)
Analizador con LLM (sigue el patrón de `introspector.py`):
- `analyze_chats()` — extrae patrones: saludos, frases de venta, manejo de objeciones, técnicas de cierre, expresiones típicas, FAQs
- `generate_prompt_suggestions()` — genera prompt mejorado incorporando patrones reales
- `generate_test_cases()` — genera test cases en formato YAML existente
- Usa batches de exchanges para no exceder contexto del LLM

## Archivos Modificados

### 3. `app/knowledge.py` — `add_chat_export()` (líneas 67-112)
Reemplazar agrupación de 6 líneas por chunking basado en exchanges:
- Cada chunk = "Cliente: ... \n Agente: ..."
- Metadata enriquecida: `segment_type`, priority 4 (más alta que default)
- Prefijo "Ejemplo de conversación real:" para contexto RAG claro

### 4. `app/main.py` — 5 endpoints nuevos (después de línea 506)
- `POST /api/training/parse-chats` — parsea y preview (sin LLM, rápido)
- `POST /api/training/analyze` — análisis con LLM (~15 seg)
- `POST /api/training/generate-prompt` — genera prompt mejorado
- `POST /api/training/generate-test-cases` — genera test cases
- `POST /api/training/import-chats` — importa al RAG con chunking inteligente

### 5. `app/static/admin.html` — Sección nueva en tab Entrenamiento
Pipeline wizard paso a paso:
1. Seleccionar archivos + nombres de agentes → **Parsear**
2. Ver preview de exchanges detectados → **Analizar patrones**
3. Ver reporte de análisis → 3 acciones:
   - **Generar prompt** (muestra sugerencia, usuario aprueba)
   - **Generar test cases** (preview, usuario confirma)
   - **Importar a RAG** (indexa con chunking inteligente)

## Orden de Implementación

1. `app/chat_parser.py` (sin dependencias, base de todo)
2. `app/knowledge.py` (mejorar `add_chat_export()`, usa parser)
3. `app/chat_analyzer.py` (usa parser, patrón de introspector)
4. `app/main.py` (endpoints, usa todo lo anterior)
5. `app/static/admin.html` (UI del pipeline)

## Verificación
- Poner un `.txt` exportado en `training/chats-reales/`
- Admin > Entrenamiento > Parsear → verificar que detecta exchanges
- Analizar → verificar patrones extraídos
- Generar prompt → comparar con el actual
- Generar test cases → correr con evaluador existente
- Importar a RAG → buscar frases del chat en la base de conocimiento
