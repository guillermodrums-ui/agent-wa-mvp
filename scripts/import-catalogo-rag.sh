#!/bin/bash
# Script para importar los 14 archivos de catálogo al RAG y asignar prioridades.
# Ejecutar con el servidor corriendo en localhost:7070
#
# Uso: bash scripts/import-catalogo-rag.sh

BASE_URL="${1:-http://localhost:7070}"

echo "=== Importando catálogo al RAG ==="
echo "Servidor: $BASE_URL"
echo ""

# Paso 1: Importar todos los archivos de training/catalogo/
echo "--- Paso 1: Importar archivos ---"
RESPONSE=$(curl -s -X POST "$BASE_URL/api/training/import" \
  -H "Content-Type: application/json" \
  -d '{
    "paths": [
      "catalogo/inyectables.txt",
      "catalogo/orales.txt",
      "catalogo/blends-manipulados.txt",
      "catalogo/adelgazamiento.txt",
      "catalogo/proteinas-creatina.txt",
      "catalogo/salud-femenina.txt",
      "catalogo/salud-masculina.txt",
      "catalogo/salud-hormonal-tpc.txt",
      "catalogo/vitaminas-minerales.txt",
      "catalogo/foco-mental.txt",
      "catalogo/protectores-digestion.txt",
      "catalogo/dermatologia.txt",
      "catalogo/info-negocio.txt",
      "catalogo/saludo-y-catalogo-resumen.txt"
    ]
  }')
echo "Resultado importación: $RESPONSE"
echo ""

# Paso 2: Listar documentos para obtener IDs
echo "--- Paso 2: Obteniendo IDs de documentos ---"
DOCS=$(curl -s "$BASE_URL/api/knowledge/documents")
echo "Documentos encontrados: $(echo "$DOCS" | python3 -c 'import sys,json; print(len(json.load(sys.stdin)))' 2>/dev/null || echo 'error')"
echo ""

# Paso 3: Asignar prioridades por categoría
echo "--- Paso 3: Asignando prioridades ---"

# Prioridad 5: inyectables, orales, blends, adelgazamiento, proteinas, info-negocio, saludo
# Prioridad 4: salud-femenina, salud-masculina, salud-hormonal, vitaminas, foco-mental, protectores
# Prioridad 3: dermatologia

echo "$DOCS" | python3 -c "
import sys, json, requests

base = '$BASE_URL'
docs = json.load(sys.stdin)

priority_map = {
    'inyectables': 5,
    'orales': 5,
    'blends-manipulados': 5,
    'adelgazamiento': 5,
    'proteinas-creatina': 5,
    'info-negocio': 5,
    'saludo-y-catalogo-resumen': 5,
    'salud-femenina': 4,
    'salud-masculina': 4,
    'salud-hormonal-tpc': 4,
    'vitaminas-minerales': 4,
    'foco-mental': 4,
    'protectores-digestion': 4,
    'dermatologia': 3,
}

for doc in docs:
    fname = doc.get('filename', '')
    doc_id = doc.get('id', '')
    for key, priority in priority_map.items():
        if key in fname:
            category = key.replace('-', '_')
            r = requests.put(
                f'{base}/api/knowledge/documents/{doc_id}/metadata',
                json={'category': category, 'priority': priority}
            )
            print(f'  {fname}: priority={priority}, category={category} -> {r.status_code}')
            break
" 2>/dev/null || echo "(Necesitás 'pip install requests' para asignar prioridades automáticamente)"

echo ""

# Paso 4: Verificar con búsquedas de prueba
echo "--- Paso 4: Búsquedas de prueba ---"
for query in "creatina" "bajar de peso" "inyectables" "descuentos"; do
  echo ""
  echo "Buscando: '$query'"
  curl -s "$BASE_URL/api/knowledge/search?q=$query&n=2" | python3 -c "
import sys, json
try:
    results = json.load(sys.stdin)
    for r in results.get('results', results) if isinstance(results, dict) else results:
        source = r.get('metadata', {}).get('source', r.get('source', 'unknown'))
        score = r.get('score', r.get('distance', 'N/A'))
        text = (r.get('text', r.get('document', ''))[:80] + '...') if len(r.get('text', r.get('document', ''))) > 80 else r.get('text', r.get('document', ''))
        print(f'  [{source}] (score: {score}) {text}')
except: print('  (error parsing response)')
" 2>/dev/null
done

echo ""
echo "=== Importación completa ==="
echo "Verificá en el admin panel: $BASE_URL/admin.html -> tab Conocimiento"
