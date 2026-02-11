FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Leer PORT de variable de entorno (para Railway, Render, etc.)
# Default a 7070 si no está definido
ENV PORT=7070

EXPOSE 7070

# Usar PORT dinámico para compatibilidad con plataformas cloud
# Remover --reload en producción (solo para desarrollo local)
CMD sh -c "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-7070} --log-level $(echo ${LOG_LEVEL:-info} | tr '[:upper:]' '[:lower:]')"
