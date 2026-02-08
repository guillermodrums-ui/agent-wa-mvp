# Bug 004: `saveSessionPromptContext()` no da feedback visual

**Estado: PENDIENTE**
**Severidad: Media**
**Archivo: `app/static/index.html` linea ~675**

## Descripcion

En el admin, `saveDefaultPromptContext()` muestra un toast al guardar. Pero en el chat, el boton "Guardar" del context panel (`saveSessionPromptContext()`) no muestra ningun feedback. El usuario no sabe si guardo o no.

## Codigo actual

```js
async function saveSessionPromptContext() {
  if (!currentSessionId) return;
  const text = getPromptContext();
  try {
    await api(`/api/sessions/${currentSessionId}/prompt-context`, {
      method: 'PUT',
      body: JSON.stringify({ prompt_context: text }),
    });
  } catch (e) {
    console.error('Error saving prompt context:', e);
  }
}
```

## Fix sugerido

Cambiar el texto del boton a "Guardado" por 1 segundo despues de guardar exitosamente:

```js
async function saveSessionPromptContext() {
  if (!currentSessionId) return;
  const btn = document.querySelector('.btn-save-ctx');
  const text = getPromptContext();
  try {
    await api(`/api/sessions/${currentSessionId}/prompt-context`, {
      method: 'PUT',
      body: JSON.stringify({ prompt_context: text }),
    });
    if (btn) {
      const original = btn.textContent;
      btn.textContent = 'Guardado';
      setTimeout(() => { btn.textContent = original; }, 1000);
    }
  } catch (e) {
    console.error('Error saving prompt context:', e);
  }
}
```
