# Handoff de Sesión — VERAQUE INDEX SEO

Documento de contexto técnico para continuar el desarrollo con otro modelo de lenguaje o desarrollador.

---

## 1. Objetivo del proyecto

Construir y desplegar en **Dokploy** un servicio automatizado que:
1. Lea las URLs pegadas por los usuarios en una hoja de cálculo de Google Sheets.
2. Consulte en **Google Search Console (URL Inspection API)**:
   - Cuándo visitó/rastreo Google la URL por última vez (`lastCrawlTime`).
   - Cuál es el estatus de Google (`coverageState` / `verdict`) y **lo escriba en español**.
3. **Regla de no re-revisión:** si la URL ya está indexada, la marque como `Completada` en la columna de estado y **no la vuelva a consultar** en futuras ejecuciones.
4. Guarde en otra columna la **fecha y hora en que se realizó la petición**.
5. **Histórico:** en cada ejecución agregue nuevas filas con fecha (`append`) en una pestaña de histórico (ej. `Historial`).

---

## 2. Datos y recursos confirmados por el usuario

- **Documento de Google Sheets (ya existía anteriormente):**
  - URL: `https://docs.google.com/spreadsheets/d/1pD4X3k0rldORiLDWUWBFSsKtLoKOACGg4hP8sl6cE-0/edit?gid=1037785648#gid=1037785648`
  - `SPREADSHEET_ID`: `1pD4X3k0rldORiLDWUWBFSsKtLoKOACGg4hP8sl6cE-0`
  - `SHEET_GID`: `1037785648`
- **Google Service Account:**
  - `mantenimientos-newe@mantenimientos-501619.iam.gserviceaccount.com`
- **Plataforma de despliegue:**
  - **Dokploy** (basado en Docker / Dockerfile / Docker Compose).

---

## 3. Arquitectura acordada

Servicio **Python 3.12 + FastAPI + APScheduler** en contenedor Docker:
- **Scheduler interno (`APScheduler`)** con cron configurable (`CRON_SCHEDULE`, por defecto `0 */6 * * *`) dentro del mismo contenedor.
- **API HTTP (`FastAPI` + `Uvicorn`)**:
  - `GET /health`: healthcheck para Dokploy.
  - `GET /status`: estado del scheduler y resumen de la última ejecución.
  - `GET /sheet/columns` (protegido con `API_SECRET`): inspección de pestaña y columnas detectadas.
  - `POST /run` (protegido con `API_SECRET`): ejecución manual bajo demanda.
- **Integración con Google APIs (`google-api-python-client` + `gspread`):**
  - Autenticación vía variable de entorno `GOOGLE_SERVICE_ACCOUNT_JSON` (JSON plano o Base64) o archivo `GOOGLE_SERVICE_ACCOUNT_FILE`.
  - Selección de propiedad de Search Console configurable (`SEARCH_CONSOLE_SITE_URL=auto` para detectar automáticamente la propiedad coincidente vía `sites().list()`, o una propiedad fija).
  - Respeto de cuota de URL Inspection API (2,000 consultas/día/propiedad) mediante `MAX_URLS_PER_RUN` y `REQUEST_DELAY_SECONDS`.

---

## 4. Estado actual del workspace

Ruta del proyecto: `c:\Users\DELL XPS\Documents\VERAQUE INDEX SEO`

### Archivos ya creados
- `requirements.txt` — dependencias (`fastapi`, `uvicorn[standard]`, `pydantic-settings`, `google-api-python-client`, `google-auth`, `gspread`, `APScheduler`, `pytest`).
- `.env.example` — plantilla de variables de entorno con `SPREADSHEET_ID` y `SHEET_GID` preconfigurados.
- `.gitignore` y `.dockerignore` — excluyen `.env`, archivos `*.json` de secretos, `secrets/`, cachés y tests en imagen.
- `app/__init__.py` — paquete principal.
- `app/config.py` — clase `Settings(BaseSettings)` con toda la configuración tipada.

### Actualización 2026-11-24 — implementación completa
Ya implementados: `app/translator.py`, `app/columns.py` (detección de columnas por alias / `COL_*`, crea las faltantes), `app/google_clients.py`, `app/sync_service.py`, `app/main.py`, `Dockerfile`, `docker-compose.yml`, `README.md`, `tests/`. Se añadieron `HEADER_ROW`, `tzdata` y `httpx`.
Pendiente: correr `pytest` (no hay Python local), primer despliegue en Dokploy y validar columnas reales con `GET /sheet/columns`.

### Lo que falta por implementar (lista original)
1. `app/translator.py`: traducción al español de `verdict` y `coverageState` de Search Console + conversión de `lastCrawlTime` a la zona horaria configurada.
2. `app/google_clients.py`: carga de credenciales Service Account, cliente de Search Console (`sites().list()` + `urlInspection().index().inspect()`) y cliente de Google Sheets (`gspread` por `gid=1037785648`, actualización de celdas y `append` en `Historial`).
3. `app/sync_service.py`: orquestación con lock para evitar ejecuciones concurrentes, omisión de filas `Completada`, actualización de pendientes y escritura en `Historial`.
4. `app/main.py`: aplicación FastAPI, lifespan con `APScheduler`, endpoints `/health`, `/status`, `/sheet/columns` y `/run`.
5. `Dockerfile`, `docker-compose.yml` y `README.md` (guía paso a paso para Dokploy y checklist de permisos).
6. `tests/` — pruebas unitarias con mocks de Google Search Console y Google Sheets.

---

## 5. Limitaciones / puntos aún no verificados

- **Estructura exacta de la hoja:** no se llegó a leer la pestaña `gid=1037785648` (el usuario instaló el plugin de Google Sheets en Antigravity, pero denegó el permiso para ejecutar el comando de inicialización del CLI `gsheets.cmd`). Por ello, **aún no se conocen los nombres literales de las columnas actuales** de esa hoja ni el nombre de la pestaña.
- **Entorno local Windows:** `python`, `node`, `git` y `docker` no están disponibles en el `PATH` del equipo local actual; las pruebas y compilación deberán ejecutarse en otro entorno o directamente al construir el contenedor en Dokploy.
- **Permisos externos pendientes de confirmar por el usuario:**
  - Que `mantenimientos-newe@mantenimientos-501619.iam.gserviceaccount.com` tenga permiso de **Editor** en el Google Sheet.
  - Que la misma Service Account esté agregada como usuario en **Google Search Console** para los dominios/propiedades correspondientes y que la API **Google Search Console API** y **Google Sheets API** estén habilitadas en el proyecto GCP `mantenimientos-501619`.
  - Nombres exactos de las columnas en la hoja `gid=1037785648` (o si se mapearán vía variables `COL_*` en `.env`).

---

## 6. Estructura real de la hoja (leída el 2026-11-24 vía conector de Google Sheets)

- Documento: `veraqueconsulting.com-URLS`. Pestañas: `veraqueconsulting` (gid 1037785648, ~270 URLs, incluye subdominios `database.` y `checklist.`) y `regulatoryintelligence` (gid 691300807, 1 URL).
- Encabezados (fila 1): `URL` | `Last crawled` | `Estatus Google` | `Ultima Solicitud de Envío` | `Comentarios Newemage` | `Comentarios Veraque`.
- Decisiones del usuario:
  - Por ahora solo se procesa `veraqueconsulting`; `regulatoryintelligence` se hará después para otro sitio.
  - `Last crawled` se escribe en hora de México legible (`YYYY-MM-DD HH:MM:SS`).
  - `Ultima Solicitud de Envío` es la fecha de solicitud manual de indexación: **no se toca**.
  - Se crean al final `G: Estado del proceso` y `H: Fecha de consulta`.
  - `Estatus Google` usa solo el texto de Search Console en español (ej. `Enviada e indexada`, `Google no reconoce esta URL`).
