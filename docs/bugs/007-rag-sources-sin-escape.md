# Bug 007: RAG sources sin `escapeHtml()` en Level 1

**Estado: PENDIENTE**
**Severidad: Baja (edge case)**
**Archivo: `app/static/index.html` linea ~801**

## Descripcion

En `buildDebugHtml()`, los nombres de fuentes RAG se insertan sin escapar:

```js
rag.sources.join(', ')
```

Si un filename contuviera caracteres HTML (ej: `<script>.pdf`), se inyectaria como HTML. Improbable con filenames normales de PDF, pero `escapeHtml()` ya se usa en el resto del debug viewer y seria consistente aplicarlo aca tambien.

## Codigo actual

```js
html += `<span class="item"><strong>RAG:</strong> ${rag.chunk_count || 0} chunks${rag.sources && rag.sources.length ? ' · ' + rag.sources.join(', ') : ''}</span>`;
```

## Fix

```js
html += `<span class="item"><strong>RAG:</strong> ${rag.chunk_count || 0} chunks${rag.sources && rag.sources.length ? ' · ' + escapeHtml(rag.sources.join(', ')) : ''}</span>`;
```
