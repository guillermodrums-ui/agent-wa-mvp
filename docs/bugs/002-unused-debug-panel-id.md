# Bug 002: ID sin uso en `debug-panel` div

**Estado: PENDIENTE**
**Severidad: Baja**
**Archivo: `app/static/index.html` linea ~724**

## Descripcion

En `addMessageBubble()` se genera un `id="debug-${Date.now()}"` en el div `.debug-panel`, pero `toggleDebugPanel()` navega con `el.nextElementSibling` (DOM traversal), no con `getElementById`. El ID nunca se consulta.

## Codigo actual

```js
html += `<div class="debug-panel" id="debug-${Date.now()}">${buildDebugHtml(debugData)}</div>`;
```

## Fix

Quitar el atributo `id`:
```js
html += `<div class="debug-panel">${buildDebugHtml(debugData)}</div>`;
```
