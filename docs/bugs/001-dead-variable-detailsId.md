# Bug 001: Variable muerta `detailsId` en `buildDebugHtml()`

**Estado: PENDIENTE**
**Severidad: Baja**
**Archivo: `app/static/index.html` linea ~796**

## Descripcion

En `buildDebugHtml()` se declara `const detailsId = 'details-' + Date.now();` pero nunca se usa en el HTML generado. Solo `technicalId` se usa para el toggle de "Debug tecnico".

## Codigo actual

```js
const detailsId = 'details-' + Date.now();  // nunca se usa
const technicalId = 'technical-' + Date.now();
```

## Fix

Borrar la linea `const detailsId = ...`.
