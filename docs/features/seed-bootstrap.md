# Plan: Bootstrap de datos seed (RAG + imágenes)

**Estado: POR HACER**

## Contexto

Cuando se levanta el agente por primera vez (deploy fresco) o después de un `reset.sh`, `data/` está vacío: no hay RAG, no hay imágenes registradas. El `runtime_config.yaml` ya se re-crea automáticamente desde `config/config.yaml` (patrón existente en `ConfigStore._ensure_runtime_file()`), pero el RAG y las imágenes requieren importación manual.

**Objetivo:** Que al detectar que la base de conocimiento está vacía (primer inicio o post-reset), los 14 docs de catálogo se importen al RAG y las 6 imágenes se registren automáticamente, sin intervención manual.

**Patrón:** Mismo que `config.yaml` → `runtime_config.yaml`: si `data/` está vacío → seedear desde archivos del repo.

---

## Cambios

### 1. Crear `config/seed-images/` con manifest

**Archivos nuevos:**
- `config/seed-images/manifest.yaml` — mapeo de archivos a títulos y metadata
- Copiar las 6 imágenes `.jpeg` desde `../documentos/` a `config/seed-images/`

**manifest.yaml:**
```yaml
images:
  - file: inyectables.jpeg
    title: "Catalogo Inyectables"
    description: "Catálogo completo de inyectables SemideusPharma con precios"
  - file: orales.jpeg
    title: "Catalogo Orales"
    description: "Catálogo completo de productos orales con precios"
  - file: exclusivos.jpeg
    title: "Productos Exclusivos"
    description: "Productos exclusivos La Fórmula Uruguay"
  - file: "perdida de peso.jpeg"
    title: "Perdida de Peso"
    description: "Productos para pérdida de peso"
  - file: "farmacos tpc.jpeg"
    title: "Farmacos y TPC"
    description: "Fármacos y productos para terapia post-ciclo"
  - file: "testosterona sin agujas.jpeg"
    title: "Testosterona Sin Agujas"
    description: "Opciones de testosterona sin agujas"
```

### 2. Crear manifiesto de prioridades para catálogo RAG

**Archivo nuevo:** `training/catalogo/manifest.yaml`

Mapea cada `.txt` a su prioridad y categoría, para que el bootstrap sepa qué importar y con qué metadata:

```yaml
documents:
  - file: inyectables.txt
    category: inyectables
    priority: 5
  - file: orales.txt
    category: orales
    priority: 5
  - file: blends-manipulados.txt
    category: blends
    priority: 5
  - file: adelgazamiento.txt
    category: adelgazamiento
    priority: 5
  - file: proteinas-creatina.txt
    category: suplementos
    priority: 5
  - file: salud-femenina.txt
    category: salud
    priority: 4
  - file: salud-masculina.txt
    category: salud
    priority: 4
  - file: salud-hormonal-tpc.txt
    category: salud
    priority: 4
  - file: vitaminas-minerales.txt
    category: salud
    priority: 4
  - file: foco-mental.txt
    category: salud
    priority: 4
  - file: protectores-digestion.txt
    category: salud
    priority: 4
  - file: dermatologia.txt
    category: salud
    priority: 3
  - file: info-negocio.txt
    category: negocio
    priority: 5
  - file: saludo-y-catalogo-resumen.txt
    category: negocio
    priority: 5
```

### 3. Agregar lógica de bootstrap en `app/main.py`

Después de inicializar `kb` y antes de montar la app, agregar:

```python
# Bootstrap: seed RAG if empty
if kb.collection.count() == 0:
    _seed_knowledge_base(kb)

# Bootstrap: seed images if empty
if not images.list_images():
    _seed_image_registry()
```

**Funciones helper** (en `main.py` o en un nuevo `app/bootstrap.py` si se prefiere separar):

**`_seed_knowledge_base(kb)`:**
1. Leer `training/catalogo/manifest.yaml`
2. Para cada entrada: leer el `.txt`, llamar `kb.add_text(text, filename, "training")`
3. Luego actualizar metadata con `kb.update_document_metadata(doc_id, category, priority)`
4. Log cuántos docs se importaron

**`_seed_image_registry()`:**
1. Leer `config/seed-images/manifest.yaml`
2. Para cada entrada: leer los bytes del `.jpeg`, llamar `images.add_image(bytes, filename, title, description, "catalogo")`
3. Log cuántas imágenes se registraron

### 4. Archivos a modificar/crear

| Archivo | Acción |
|---|---|
| `config/seed-images/manifest.yaml` | Crear |
| `config/seed-images/*.jpeg` (6 archivos) | Copiar desde `../documentos/` |
| `training/catalogo/manifest.yaml` | Crear |
| `app/main.py` | Agregar bootstrap después de init de `kb` e imágenes |

---

## Verificación

1. `bash reset.sh` → borra todo `data/`
2. `docker compose up --build` → al levantar, debería loguear "Seeded X documents" y "Seeded X images"
3. Admin panel → tab Conocimiento → 14 docs con prioridades correctas
4. Chat → "Hola" → debería funcionar con catálogo completo
5. Imágenes → verificar que `[IMAGEN: Catalogo Inyectables]` resuelve correctamente
