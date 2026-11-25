"""Traducción al español de los resultados de la URL Inspection API y formato de fechas."""

from __future__ import annotations

import unicodedata
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S"

VERDICT_ES: dict[str, str] = {
    "PASS": "Indexada",
    "PARTIAL": "Indexada con advertencias",
    "FAIL": "No indexada",
    "NEUTRAL": "Excluida / No indexada",
    "VERDICT_UNSPECIFIED": "Sin veredicto",
}

# coverageState llega como texto legible (en inglés, o ya localizado si Google
# respeta languageCode). Se normaliza a minúsculas sin acentos para buscarlo.
COVERAGE_ES: dict[str, str] = {
    "submitted and indexed": "Enviada e indexada",
    "indexed, not submitted in sitemap": "Indexada, no enviada en sitemap",
    "indexed, though blocked by robots.txt": "Indexada, aunque bloqueada por robots.txt",
    "crawled - currently not indexed": "Rastreada: actualmente sin indexar",
    "discovered - currently not indexed": "Descubierta: actualmente sin indexar",
    "url is unknown to google": "Google no reconoce esta URL",
    "page with redirect": "Página con redirección",
    "excluded by 'noindex' tag": "Excluida por la etiqueta 'noindex'",
    "submitted url marked 'noindex'": "URL enviada marcada como 'noindex'",
    "blocked by robots.txt": "Bloqueada por robots.txt",
    "submitted url blocked by robots.txt": "URL enviada bloqueada por robots.txt",
    "not found (404)": "No encontrada (404)",
    "submitted url not found (404)": "URL enviada no encontrada (404)",
    "soft 404": "Soft 404",
    "submitted url seems to be a soft 404": "URL enviada parece un soft 404",
    "server error (5xx)": "Error del servidor (5xx)",
    "redirect error": "Error de redirección",
    "blocked due to unauthorized request (401)": "Bloqueada por solicitud no autorizada (401)",
    "blocked due to access forbidden (403)": "Bloqueada por acceso prohibido (403)",
    "blocked due to other 4xx issue": "Bloqueada por otro problema 4xx",
    "duplicate without user-selected canonical": "Duplicada sin canónica seleccionada por el usuario",
    "duplicate, google chose different canonical than user": "Duplicada: Google eligió una canónica diferente",
    "alternate page with proper canonical tag": "Página alternativa con etiqueta canónica adecuada",
    "blocked by page removal tool": "Bloqueada por la herramienta de retirada de URLs",
}


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.replace("–", "-").replace("—", "-")
    return " ".join(text.lower().split())


def translate_verdict(verdict: str | None) -> str:
    if not verdict:
        return VERDICT_ES["VERDICT_UNSPECIFIED"]
    return VERDICT_ES.get(verdict.upper(), verdict)


def translate_coverage(coverage_state: str | None) -> str:
    """Traduce coverageState; si no se conoce (o ya viene en español) se devuelve tal cual."""
    if not coverage_state:
        return ""
    return COVERAGE_ES.get(_normalize(coverage_state), coverage_state)


def google_status_text(verdict: str | None, coverage_state: str | None) -> str:
    """Texto para la columna de estatus, igual al de Search Console (p. ej. 'Enviada e indexada').

    Si Google no devuelve coverageState se usa el veredicto traducido.
    """
    return translate_coverage(coverage_state) or translate_verdict(verdict)


def is_indexed(verdict: str | None) -> bool:
    """La URL se considera indexada cuando Google devuelve verdict PASS."""
    return (verdict or "").upper() == "PASS"


def format_crawl_time(last_crawl_time: str | None, tz_name: str) -> str:
    """Convierte lastCrawlTime (RFC 3339, UTC) a la zona horaria configurada."""
    if not last_crawl_time:
        return "Sin rastreo registrado"
    try:
        value = last_crawl_time.replace("Z", "+00:00")
        # Python < 3.11 no acepta más de 6 decimales; se recortan por seguridad.
        if "." in value:
            main, rest = value.split(".", 1)
            digits = "".join(ch for ch in rest if ch.isdigit())
            offset = rest[len(digits):]
            value = f"{main}.{digits[:6]}{offset}"
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(ZoneInfo(tz_name)).strftime(DATETIME_FORMAT)
    except (ValueError, KeyError):
        return last_crawl_time


def now_text(tz_name: str) -> str:
    return datetime.now(ZoneInfo(tz_name)).strftime(DATETIME_FORMAT)
