from functools import lru_cache
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuración del servicio cargada desde variables de entorno."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        env_ignore_empty=True,
    )

    # Google Sheets
    spreadsheet_id: str = Field(
        default="1pD4X3k0rldORiLDWUWBFSsKtLoKOACGg4hP8sl6cE-0",
        alias="SPREADSHEET_ID",
    )
    sheet_gid: int | None = Field(default=1037785648, alias="SHEET_GID")
    sheet_name: str = Field(default="", alias="SHEET_NAME")
    # Fila donde están los encabezados (1 = primera fila)
    header_row: int = Field(default=1, ge=1, alias="HEADER_ROW")

    enable_history: bool = Field(default=True, alias="ENABLE_HISTORY")
    history_sheet_name: str = Field(default="Historial", alias="HISTORY_SHEET_NAME")

    # Mapeo opcional de columnas por nombre exacto o letra (A, B, C...)
    col_url: str = Field(default="", alias="COL_URL")
    col_last_crawl: str = Field(default="", alias="COL_LAST_CRAWL")
    col_google_status: str = Field(default="", alias="COL_GOOGLE_STATUS")
    col_process_status: str = Field(default="", alias="COL_PROCESS_STATUS")
    col_last_check: str = Field(default="", alias="COL_LAST_CHECK")

    # Google Search Console
    search_console_site_url: str = Field(default="auto", alias="SEARCH_CONSOLE_SITE_URL")
    search_console_language_code: str = Field(default="es-419", alias="SEARCH_CONSOLE_LANGUAGE_CODE")

    # Credenciales Service Account
    google_service_account_json: str = Field(default="", alias="GOOGLE_SERVICE_ACCOUNT_JSON")
    google_service_account_file: str = Field(default="", alias="GOOGLE_SERVICE_ACCOUNT_FILE")

    # Scheduler y ejecución
    cron_schedule: str = Field(default="0 */6 * * *", alias="CRON_SCHEDULE")
    timezone: str = Field(default="America/Mexico_City", alias="TIMEZONE")
    manual_only: bool = Field(default=False, alias="MANUAL_ONLY")
    run_on_startup: bool = Field(default=False, alias="RUN_ON_STARTUP")
    max_urls_per_run: int = Field(default=200, alias="MAX_URLS_PER_RUN")
    request_delay_seconds: float = Field(default=0.35, alias="REQUEST_DELAY_SECONDS")

    # Etiquetas de estado en español
    completed_status_value: str = Field(default="Completada", alias="COMPLETED_STATUS_VALUE")
    pending_status_value: str = Field(default="Pendiente", alias="PENDING_STATUS_VALUE")
    error_status_value: str = Field(default="Error", alias="ERROR_STATUS_VALUE")

    # Servidor HTTP
    api_secret: str = Field(default="", alias="API_SECRET")
    port: int = Field(default=8000, alias="PORT")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")


@lru_cache
def get_settings() -> Settings:
    """Devuelve una instancia cacheada de Settings."""
    return Settings()
