"""Clientes de Google: credenciales, Search Console (URL Inspection) y Google Sheets."""

from __future__ import annotations

import base64
import binascii
import json
import logging
from urllib.parse import urlparse

import gspread
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from gspread.utils import rowcol_to_a1

from app.config import Settings

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/webmasters.readonly",
    "https://www.googleapis.com/auth/spreadsheets",
]

HISTORY_HEADERS = [
    "Fecha de ejecución",
    "URL",
    "Propiedad Search Console",
    "Estatus en Google",
    "Veredicto (API)",
    "Cobertura (API)",
    "Último rastreo de Google",
    "Estado del proceso",
    "Detalle / Error",
]


class CredentialsError(RuntimeError):
    pass


def load_credentials(settings: Settings) -> Credentials:
    """Carga la Service Account desde GOOGLE_SERVICE_ACCOUNT_JSON (plano o Base64) o desde archivo."""
    raw = settings.google_service_account_json.strip()
    if raw:
        info = _parse_service_account_json(raw)
        return Credentials.from_service_account_info(info, scopes=SCOPES)
    if settings.google_service_account_file:
        return Credentials.from_service_account_file(settings.google_service_account_file, scopes=SCOPES)
    raise CredentialsError(
        "Faltan credenciales: define GOOGLE_SERVICE_ACCOUNT_JSON o GOOGLE_SERVICE_ACCOUNT_FILE."
    )


def _parse_service_account_json(raw: str) -> dict:
    if raw.startswith("{"):
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise CredentialsError(f"GOOGLE_SERVICE_ACCOUNT_JSON no es un JSON válido: {exc}") from exc
    try:
        decoded = base64.b64decode(raw, validate=False).decode("utf-8")
        return json.loads(decoded)
    except (binascii.Error, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CredentialsError(
            "GOOGLE_SERVICE_ACCOUNT_JSON no es JSON plano ni Base64 de un JSON válido."
        ) from exc


# ---------------------------------------------------------------------------
# Search Console
# ---------------------------------------------------------------------------


def match_site_for_url(url: str, site_urls: list[str]) -> str | None:
    """Elige la propiedad de Search Console que corresponde a una URL.

    Prefiere la propiedad de prefijo de URL más específica; si no hay, la propiedad
    de dominio (sc-domain:) más específica.
    """
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    url_lower = url.lower()

    prefix_matches = [
        s for s in site_urls
        if not s.startswith("sc-domain:") and url_lower.startswith(s.lower())
    ]
    if prefix_matches:
        return max(prefix_matches, key=len)

    domain_matches = []
    for s in site_urls:
        if s.startswith("sc-domain:"):
            domain = s[len("sc-domain:"):].lower()
            if host == domain or host.endswith("." + domain):
                domain_matches.append(s)
    if domain_matches:
        return max(domain_matches, key=len)
    return None


class SearchConsoleClient:
    def __init__(self, credentials: Credentials, settings: Settings):
        self._settings = settings
        self._service = build("searchconsole", "v1", credentials=credentials, cache_discovery=False)
        self._sites: list[str] | None = None

    def list_sites(self) -> list[str]:
        """Propiedades verificadas a las que la Service Account tiene acceso."""
        if self._sites is None:
            response = self._service.sites().list().execute()
            self._sites = [
                entry["siteUrl"]
                for entry in response.get("siteEntry", [])
                if entry.get("permissionLevel") != "siteUnverifiedUser"
            ]
            logger.info("Propiedades de Search Console disponibles: %s", self._sites)
        return self._sites

    def resolve_site(self, url: str) -> str | None:
        configured = self._settings.search_console_site_url.strip()
        if configured and configured.lower() != "auto":
            return configured
        return match_site_for_url(url, self.list_sites())

    def inspect(self, url: str, site_url: str) -> dict:
        body = {
            "inspectionUrl": url,
            "siteUrl": site_url,
            "languageCode": self._settings.search_console_language_code,
        }
        response = self._service.urlInspection().index().inspect(body=body).execute()
        return response.get("inspectionResult", {})


# ---------------------------------------------------------------------------
# Google Sheets
# ---------------------------------------------------------------------------


class SheetsClient:
    def __init__(self, credentials: Credentials, settings: Settings):
        self._settings = settings
        self._gc = gspread.authorize(credentials)
        self._spreadsheet = self._gc.open_by_key(settings.spreadsheet_id)
        self._worksheet: gspread.Worksheet | None = None

    @property
    def worksheet(self) -> gspread.Worksheet:
        if self._worksheet is None:
            if self._settings.sheet_name:
                self._worksheet = self._spreadsheet.worksheet(self._settings.sheet_name)
            elif self._settings.sheet_gid is not None:
                self._worksheet = self._spreadsheet.get_worksheet_by_id(self._settings.sheet_gid)
            else:
                self._worksheet = self._spreadsheet.sheet1
        return self._worksheet

    @property
    def worksheet_title(self) -> str:
        return self.worksheet.title

    def get_all_values(self) -> list[list[str]]:
        return self.worksheet.get_all_values()

    def ensure_columns(self, max_col: int) -> None:
        ws = self.worksheet
        if ws.col_count < max_col:
            ws.add_cols(max_col - ws.col_count)

    def write_cells(self, cells: list[tuple[int, int, str]]) -> None:
        """Escribe celdas (fila, columna, valor) en una sola llamada batch."""
        if not cells:
            return
        data = [{"range": rowcol_to_a1(r, c), "values": [[v]]} for r, c, v in cells]
        self.worksheet.batch_update(data, value_input_option="USER_ENTERED")

    def append_history(self, rows: list[list[str]]) -> None:
        if not rows:
            return
        ws = self._get_or_create_history_sheet()
        ws.append_rows(rows, value_input_option="USER_ENTERED", insert_data_option="INSERT_ROWS")

    def _get_or_create_history_sheet(self) -> gspread.Worksheet:
        name = self._settings.history_sheet_name
        try:
            ws = self._spreadsheet.worksheet(name)
        except gspread.WorksheetNotFound:
            logger.info("Creando pestaña de histórico '%s'", name)
            ws = self._spreadsheet.add_worksheet(title=name, rows=1000, cols=len(HISTORY_HEADERS))
            ws.update([HISTORY_HEADERS], "A1", value_input_option="USER_ENTERED")
            ws.freeze(rows=1)
            return ws
        if not ws.row_values(1):
            ws.update([HISTORY_HEADERS], "A1", value_input_option="USER_ENTERED")
        return ws
