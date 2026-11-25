FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8000

WORKDIR /app

COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY app ./app

# --- Etapa de pruebas: si algún test falla, el build (y el deploy en Dokploy) se detiene ---
FROM base AS test
COPY tests ./tests
RUN python -m pytest -q && touch /tmp/tests-passed

# --- Imagen final ---
FROM base AS runtime
COPY --from=test /tmp/tests-passed /tmp/tests-passed

RUN useradd --create-home --uid 1000 appuser
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import os,urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\",\"8000\")}/health', timeout=4)" || exit 1

# Un solo worker: el scheduler vive dentro del proceso y no debe duplicarse.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --workers 1"]
