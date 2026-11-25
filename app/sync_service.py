"""Orquestación: lee la hoja, consulta Search Console y escribe resultados + histórico."""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Protocol

from googleapiclient.errors import HttpError

from app import translator
from app.columns import ColumnMap, resolve_columns
from app.config import Settings

logger = logging.getLogger(__name__)

FLUSH_EVERY = 25  # filas procesadas entre escrituras a Sheets (para no perder avance)


class SheetsLike(Protocol):
    worksheet_title: str

    def get_all_values(self) -> list[list[str]]: ...
    def ensure_columns(self, max_col: int) -> None: ...
    def write_cells(self, cells: list[tuple[int, int, str]]) -> None: ...
    def append_history(self, rows: list[list[str]]) -> None: ...


class SearchConsoleLike(Protocol):
    def resolve_site(self, url: str) -> str | None: ...
    def inspect(self, url: str, site_url: str) -> dict: ...


@dataclass
class RunSummary:
    trigger: str
    started_at: str
    finished_at: str | None = None
    status: str = "running"  # running | ok | partial | error | busy
    message: str = ""
    worksheet: str = ""
    total_urls: int = 0
    skipped_completed: int = 0
    processed: int = 0
    indexed: int = 0
    not_indexed: int = 0
    errors: int = 0
    left_for_next_run: int = 0
    columns: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class QuotaExceeded(RuntimeError):
    pass


def _cell(row: list[str], col: int) -> str:
    return row[col - 1].strip() if len(row) >= col else ""


def _http_error_message(exc: HttpError) -> tuple[str, bool]:
    """Devuelve (mensaje en español, es_error_de_cuota)."""
    status = getattr(exc.resp, "status", None)
    try:
        detail = exc._get_reason() or ""  # noqa: SLF001
    except Exception:  # pragma: no cover - solo para mensajes
        detail = str(exc)
    if status == 429 or "quota" in detail.lower() or "rate limit" in detail.lower():
        return f"Cuota de Search Console agotada (HTTP {status}): {detail}", True
    if status == 403:
        return f"Sin permiso en Search Console para esta propiedad (HTTP 403): {detail}", False
    if status == 400:
        return f"Solicitud inválida (HTTP 400), la URL quizá no pertenece a la propiedad: {detail}", False
    return f"Error de Google API (HTTP {status}): {detail}", False


class SyncService:
    def __init__(
        self,
        settings: Settings,
        sheets_factory: Callable[[], SheetsLike] | None = None,
        gsc_factory: Callable[[], SearchConsoleLike] | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.settings = settings
        self._sheets_factory = sheets_factory or self._default_sheets_factory
        self._gsc_factory = gsc_factory or self._default_gsc_factory
        self._sleep = sleep
        self._lock = threading.Lock()
        self.last_run: RunSummary | None = None
        self.current_run: RunSummary | None = None

    # -- fábricas por defecto (credenciales reales) -------------------------
    def _default_sheets_factory(self) -> SheetsLike:
        from app.google_clients import SheetsClient, load_credentials

        return SheetsClient(load_credentials(self.settings), self.settings)

    def _default_gsc_factory(self) -> SearchConsoleLike:
        from app.google_clients import SearchConsoleClient, load_credentials

        return SearchConsoleClient(load_credentials(self.settings), self.settings)

    # -- API pública --------------------------------------------------------
    @property
    def is_running(self) -> bool:
        return self._lock.locked()

    def column_overrides(self) -> dict[str, str]:
        s = self.settings
        return {
            "url": s.col_url,
            "last_crawl": s.col_last_crawl,
            "google_status": s.col_google_status,
            "process_status": s.col_process_status,
            "last_check": s.col_last_check,
        }

    def inspect_columns(self) -> dict[str, Any]:
        """Describe la pestaña y las columnas detectadas, sin modificar nada."""
        sheets = self._sheets_factory()
        values = sheets.get_all_values()
        header_row = self.settings.header_row
        headers = values[header_row - 1] if len(values) >= header_row else []
        result: dict[str, Any] = {
            "worksheet": sheets.worksheet_title,
            "header_row": header_row,
            "headers": headers,
            "data_rows": max(len(values) - header_row, 0),
        }
        try:
            cmap = resolve_columns(headers, self.column_overrides())
            result["columns"] = {
                fld: {"column": cmap[fld], "detected_by": cmap.detected_by[fld]}
                for fld in cmap.indexes
            }
            result["headers_to_create"] = cmap.headers_to_create
        except ValueError as exc:
            result["error"] = str(exc)
        return result

    def run(self, trigger: str = "manual") -> RunSummary:
        tz = self.settings.timezone
        if not self._lock.acquire(blocking=False):
            return RunSummary(
                trigger=trigger,
                started_at=translator.now_text(tz),
                finished_at=translator.now_text(tz),
                status="busy",
                message="Ya hay una ejecución en curso.",
            )
        summary = RunSummary(trigger=trigger, started_at=translator.now_text(tz))
        self.current_run = summary
        try:
            self._run(summary)
            if summary.status == "running":
                summary.status = "ok"
        except QuotaExceeded as exc:
            summary.status = "partial"
            summary.message = str(exc)
            logger.warning(str(exc))
        except Exception as exc:  # noqa: BLE001
            summary.status = "error"
            summary.message = f"{type(exc).__name__}: {exc}"
            logger.exception("La ejecución falló")
        finally:
            summary.finished_at = translator.now_text(tz)
            self.last_run = summary
            self.current_run = None
            self._lock.release()
            logger.info("Ejecución terminada: %s", summary.to_dict())
        return summary

    # -- lógica principal ---------------------------------------------------
    def _run(self, summary: RunSummary) -> None:
        s = self.settings
        tz = s.timezone
        completed_norm = s.completed_status_value.strip().casefold()

        sheets = self._sheets_factory()
        summary.worksheet = sheets.worksheet_title
        values = sheets.get_all_values()
        header_row = s.header_row
        headers = values[header_row - 1] if len(values) >= header_row else []

        cmap = resolve_columns(headers, self.column_overrides())
        summary.columns = dict(cmap.detected_by)
        if cmap.headers_to_create:
            sheets.ensure_columns(max(cmap.indexes.values()))
            sheets.write_cells([(header_row, c, h) for c, h in cmap.headers_to_create.items()])
            logger.info("Encabezados creados: %s", cmap.headers_to_create)

        pending_rows: list[tuple[int, str]] = []
        for offset, row in enumerate(values[header_row:], start=header_row + 1):
            url = _cell(row, cmap["url"])
            if not url:
                continue
            summary.total_urls += 1
            if _cell(row, cmap["process_status"]).casefold() == completed_norm:
                summary.skipped_completed += 1
                continue
            pending_rows.append((offset, url))

        to_process = pending_rows[: s.max_urls_per_run]
        summary.left_for_next_run = len(pending_rows) - len(to_process)
        if not to_process:
            summary.message = "No hay URLs pendientes."
            return

        gsc = self._gsc_factory()
        cells: list[tuple[int, int, str]] = []
        history: list[list[str]] = []
        run_time = summary.started_at

        try:
            for i, (row_num, url) in enumerate(to_process):
                if i > 0 and s.request_delay_seconds > 0:
                    self._sleep(s.request_delay_seconds)
                try:
                    self._process_row(gsc, cmap, row_num, url, summary, cells, history, run_time)
                except QuotaExceeded:
                    summary.left_for_next_run += len(to_process) - i
                    raise
                if (i + 1) % FLUSH_EVERY == 0:
                    self._flush(sheets, cells, history)
        finally:
            self._flush(sheets, cells, history)

        summary.message = (
            f"Procesadas {summary.processed} URLs: {summary.indexed} indexadas, "
            f"{summary.not_indexed} sin indexar, {summary.errors} con error."
        )

    def _process_row(
        self,
        gsc: SearchConsoleLike,
        cmap: ColumnMap,
        row_num: int,
        url: str,
        summary: RunSummary,
        cells: list[tuple[int, int, str]],
        history: list[list[str]],
        run_time: str,
    ) -> None:
        s = self.settings
        check_time = translator.now_text(s.timezone)
        site = ""
        verdict = coverage = ""
        last_crawl = google_status = ""
        detail = ""

        if not url.lower().startswith(("http://", "https://")):
            process_status = s.error_status_value
            google_status = "URL inválida (debe iniciar con http:// o https://)"
            detail = google_status
            summary.errors += 1
        else:
            try:
                site = gsc.resolve_site(url) or ""
                if not site:
                    raise LookupError(
                        "No hay una propiedad de Search Console accesible para esta URL "
                        "(agrega la Service Account como usuario de la propiedad)."
                    )
                result = gsc.inspect(url, site)
                index_status = result.get("indexStatusResult", {}) or {}
                verdict = index_status.get("verdict", "")
                coverage = index_status.get("coverageState", "")
                google_status = translator.google_status_text(verdict, coverage)
                last_crawl = translator.format_crawl_time(index_status.get("lastCrawlTime"), s.timezone)
                if translator.is_indexed(verdict):
                    process_status = s.completed_status_value
                    summary.indexed += 1
                else:
                    process_status = s.pending_status_value
                    summary.not_indexed += 1
            except HttpError as exc:
                message, is_quota = _http_error_message(exc)
                if is_quota:
                    raise QuotaExceeded(message) from exc
                process_status, google_status, detail = s.error_status_value, message, message
                summary.errors += 1
            except LookupError as exc:
                process_status, google_status, detail = s.error_status_value, str(exc), str(exc)
                summary.errors += 1
            except Exception as exc:  # noqa: BLE001
                message = f"Error inesperado: {type(exc).__name__}: {exc}"
                logger.exception("Error inspeccionando %s", url)
                process_status, google_status, detail = s.error_status_value, message, message
                summary.errors += 1

        summary.processed += 1
        if last_crawl:
            cells.append((row_num, cmap["last_crawl"], last_crawl))
        cells.extend(
            [
                (row_num, cmap["google_status"], google_status),
                (row_num, cmap["process_status"], process_status),
                (row_num, cmap["last_check"], check_time),
            ]
        )
        if s.enable_history:
            history.append(
                [run_time, url, site, google_status, verdict, coverage, last_crawl, process_status, detail]
            )

    def _flush(self, sheets: SheetsLike, cells: list, history: list) -> None:
        if cells:
            sheets.write_cells(list(cells))
            cells.clear()
        if history:
            sheets.append_history(list(history))
            history.clear()
