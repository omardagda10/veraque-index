# Veraque Index SEO

Servicio que lee URLs de una hoja de Google Sheets, consulta la **URL Inspection API** de Google Search Console y escribe en la hoja, en español:

| Columna (se detecta por encabezado o se crea) | Contenido |
|---|---|
| `URL` | La URL pegada por el usuario (entrada) |
| `Último rastreo de Google` | `lastCrawlTime` convertido a `TIMEZONE` |
| `Estatus en Google` | Estatus de Google en español, igual que en Search Console (ej. `Enviada e indexada`) |
| `Estado del proceso` | `Completada` (indexada, no se vuelve a consultar), `Pendiente` o `Error` |
| `Fecha de consulta` | Fecha y hora de la petición |

Cada ejecución agrega filas a la pestaña **`Historial`** (se crea sola si no existe).

## Cómo detecta las columnas

1. Si defines `COL_URL`, `COL_LAST_CRAWL`, `COL_GOOGLE_STATUS`, `COL_PROCESS_STATUS` o `COL_LAST_CHECK` (nombre exacto del encabezado o letra: `A`, `B`, …) se usa eso.
2. Si no, busca encabezados conocidos (sin importar acentos ni mayúsculas): `URL`, `Link`, `Enlace` · `Último rastreo`, `Última visita` · `Estatus Google`, `Estado Google`, `Cobertura` · `Estado`, `Estatus`, `Estado del proceso` · `Fecha de consulta`, `Última revisión`, `Fecha de petición`.
3. Las columnas de salida que no existan se **crean al final** de la fila de encabezados (`HEADER_ROW`, por defecto 1).

Antes de la primera ejecución revisa lo que se detectó con `GET /sheet/columns`.

## Requisitos en Google (checklist)

- [ ] En el proyecto GCP `mantenimientos-501619` están habilitadas **Google Search Console API** y **Google Sheets API**.
- [ ] La hoja está compartida con `mantenimientos-newe@mantenimientos-501619.iam.gserviceaccount.com` como **Editor**.
- [ ] En **Search Console → Configuración → Usuarios y permisos** de cada propiedad, esa misma cuenta está agregada (permiso *Completo* o *Restringido*).
- [ ] Tienes la llave JSON de la Service Account.

## Despliegue en Dokploy

1. Sube este proyecto a un repositorio Git (GitHub/GitLab/Gitea).
2. En Dokploy: **Create Service → Application**, conecta el repo y elige **Build Type: Dockerfile** (o usa *Compose* con `docker-compose.yml`).
3. En **Environment** pega las variables de `.env.example`. Como mínimo:
   - `GOOGLE_SERVICE_ACCOUNT_JSON`: el contenido del JSON en una línea, o en Base64
     (PowerShell: `[Convert]::ToBase64String([IO.File]::ReadAllBytes("llave.json"))`).
   - `API_SECRET`: un token largo y aleatorio.
   - `TIMEZONE`, `CRON_SCHEDULE` según necesites.
4. En **Domains** asigna un dominio apuntando al puerto `8000` (necesario solo para usar `/run` y `/status` desde fuera).
5. **Deploy**. Dokploy usa el `HEALTHCHECK` del Dockerfile (`GET /health`).
6. Verifica:
   ```bash
   curl https://TU-DOMINIO/health
   curl -H "X-API-Key: $API_SECRET" https://TU-DOMINIO/sheet/columns
   curl -X POST -H "X-API-Key: $API_SECRET" "https://TU-DOMINIO/run?wait=true"
   curl https://TU-DOMINIO/status
   ```

> Mantén **una sola réplica**: el scheduler vive dentro del contenedor y varias réplicas duplicarían las consultas.

## Endpoints

| Método | Ruta | Auth | Descripción |
|---|---|---|---|
| GET | `/health` | — | Healthcheck |
| GET | `/status` | — | Estado del scheduler, próxima ejecución y resumen de la última |
| GET | `/sheet/columns` | `X-API-Key` o `Authorization: Bearer` | Pestaña, encabezados y columnas detectadas (no modifica nada) |
| POST | `/run?wait=false` | `X-API-Key` o `Authorization: Bearer` | Ejecuta ahora (en segundo plano, o espera con `wait=true`) |

## Cuota

La URL Inspection API permite **2,000 consultas/día y 600/min por propiedad**. `MAX_URLS_PER_RUN` (200) × 4 ejecuciones diarias (`0 */6 * * *`) = 800/día como máximo. Si Google responde con error de cuota la ejecución se detiene, guarda el avance y termina con estado `partial`; las URLs restantes se procesan en la siguiente.

Las URLs con estado `Pendiente` o `Error` se vuelven a consultar en cada ejecución; solo las `Completada` se omiten. Para forzar una nueva revisión de una URL indexada, borra su celda de *Estado del proceso*.

## Desarrollo local

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env    # y completa las credenciales
pytest
uvicorn app.main:app --reload
```
