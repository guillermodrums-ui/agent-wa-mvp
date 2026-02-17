#!/bin/bash
# Reset completo: para containers, borra datos y levanta de cero
set -e

cd "$(dirname "$0")"

echo "Parando containers..."
docker compose down -v 2>/dev/null || true

echo "Borrando datos (ChromaDB, sessions, runtime config, imagenes)..."
rm -rf data/chroma
rm -f  data/sessions.db data/sessions.db-shm data/sessions.db-wal
rm -f  data/runtime_config.yaml
rm -rf data/images

echo "Recreando carpetas..."
mkdir -p data/chroma data/images

echo "Rebuildeando y levantando..."
docker compose up --build -d

echo ""
echo "Listo! Sistema reseteado. Abrí http://localhost:7070"
