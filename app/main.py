"""Aplicación FastAPI + APScheduler."""

from __future__ import annotations

import hmac
import logging
import threading
from contextlib import asynccontextmanager

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import Depends, FastAPI, Header, HTTPException, Query, status

from app.config import get_settings
from app.sync_service import SyncService

settings = get_settings()
logging.basicConfig(
    level=settings.log_level.upper(),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("veraque")

service = SyncService(settings)
scheduler = BackgroundScheduler(timezone=settings.timezone)
JOB_ID = "sync_search_console"


def _scheduled_run() -> None:
    service.run(trigger="cron")


@asynccontextmanager
async def lifespan(_: FastAPI):
    if not settings.manual_only:
        trigger = CronTrigger.from_crontab(settings.cron_schedule, timezone=settings.timezone)
        scheduler.add_job(
            _scheduled_run, trigger, id=JOB_ID, max_instances=1, coalesce=True, misfire_grace_time=3600
        )
        scheduler.start()
        logger.info("Scheduler iniciado con cron '%s' (%s)", settings.cron_schedule, settings.timezone)
    else:
        logger.info("MANUAL_ONLY=true: el scheduler está desactivado")
    if settings.run_on_startup:
        threading.Thread(target=service.run, kwargs={"trigger": "startup"}, daemon=True).start()
    yield
    if scheduler.running:
        scheduler.shutdown(wait=False)


app = FastAPI(title="Veraque Index SEO", version="1.0.0", lifespan=lifespan)


def require_secret(
    x_api_key: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
) -> None:
    if not settings.api_secret:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "API_SECRET no está configurado.")
    token = x_api_key or ""
    if not token and authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    if not hmac.compare_digest(token.encode(), settings.api_secret.encode()):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token inválido.")


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/status")
def get_status() -> dict:
    job = scheduler.get_job(JOB_ID) if scheduler.running else None
    return {
        "scheduler": {
            "enabled": not settings.manual_only,
            "running": scheduler.running,
            "cron": settings.cron_schedule,
            "timezone": settings.timezone,
            "next_run": job.next_run_time.isoformat() if job and job.next_run_time else None,
        },
        "running_now": service.is_running,
        "current_run": service.current_run.to_dict() if service.current_run else None,
        "last_run": service.last_run.to_dict() if service.last_run else None,
    }


@app.get("/sheet/columns", dependencies=[Depends(require_secret)])
def sheet_columns() -> dict:
    try:
        return service.inspect_columns()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"{type(exc).__name__}: {exc}") from exc


@app.post("/run", dependencies=[Depends(require_secret)])
def run_now(wait: bool = Query(default=False, description="Esperar a que termine la ejecución")) -> dict:
    if service.is_running:
        raise HTTPException(status.HTTP_409_CONFLICT, "Ya hay una ejecución en curso.")
    if wait:
        return service.run(trigger="manual").to_dict()
    threading.Thread(target=service.run, kwargs={"trigger": "manual"}, daemon=True).start()
    return {"status": "started", "message": "Ejecución iniciada; consulta GET /status para ver el resultado."}
