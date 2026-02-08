# Bug 003: `getattr` innecesario en `main.py`

**Estado: PENDIENTE**
**Severidad: Baja**
**Archivo: `app/main.py` linea ~169**

## Descripcion

`ChatSession` ya tiene `prompt_context: str = ""` como campo definido en `models.py`. Usar `getattr(session, "prompt_context", "")` es innecesariamente defensivo — el atributo siempre existe.

## Codigo actual

```python
prompt_context=getattr(session, "prompt_context", "") or "",
```

## Fix

```python
prompt_context=session.prompt_context or "",
```
