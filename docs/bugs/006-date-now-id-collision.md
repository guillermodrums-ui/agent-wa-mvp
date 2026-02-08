# Bug 006: `Date.now()` puede colisionar para IDs

**Estado: PENDIENTE**
**Severidad: Baja (edge case)**
**Archivo: `app/static/index.html` lineas ~797, ~724**

## Descripcion

`buildDebugHtml()` usa `Date.now()` para generar IDs unicos (`technicalId`). Si dos mensajes se procesan en <1ms (poco probable en uso normal, pero posible), los IDs colisionan y `toggleDebugSection()` operaria sobre el elemento equivocado.

## Codigo actual

```js
const technicalId = 'technical-' + Date.now();
```

## Fix

Usar `Math.random()` que tiene menos riesgo de colision:
```js
const technicalId = 'tech-' + Math.random().toString(36).slice(2, 8);
```
