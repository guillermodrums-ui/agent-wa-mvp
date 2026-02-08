# Bug 005: `<a>` sin `href` para debug-toggle

**Estado: PENDIENTE**
**Severidad: Baja**
**Archivo: `app/static/index.html` linea ~723**

## Descripcion

El link "ver detalles" usa `<a class="debug-toggle" onclick="...">` sin atributo `href`. Semanticamente deberia ser un `<span>` o `<button>`. Con `<a>` sin href algunos browsers no aplican cursor pointer por defecto (el CSS lo fuerza, pero es ruidoso para accesibilidad y screen readers).

## Codigo actual

```js
html += `<a class="debug-toggle" onclick="toggleDebugPanel(this)">ver detalles</a>`;
```

## Fix

```js
html += `<span class="debug-toggle" onclick="toggleDebugPanel(this)">ver detalles</span>`;
```
