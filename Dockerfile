# ==============================================================================
# Dockerfile para FastAPI (Compatible con Coolify y Docker Compose)
# ==============================================================================

FROM python:3.10-slim

# Evita que Python escriba archivos .pyc y fuerza salida en consola sin buffer
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /code

# Instalar dependencias del sistema necesarias para compilar o verificar salud
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copiar requirements e instalar dependencias de Python
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copiar el código fuente de la aplicación
COPY app/ ./app

# Exponer el puerto por el que escuchará FastAPI
EXPOSE 8000

# Healthcheck para Docker y orquestadores como Coolify
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Comando de ejecución con Uvicorn
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
