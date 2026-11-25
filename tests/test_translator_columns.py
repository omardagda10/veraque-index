import pytest

from app import translator
from app.columns import ColumnDetectionError, letter_to_index, resolve_columns
from app.google_clients import match_site_for_url


# --- translator -------------------------------------------------------------

def test_google_status_text_translates_verdict_and_coverage():
    assert translator.google_status_text("PASS", "Submitted and indexed") == "Enviada e indexada"
    assert (
        translator.google_status_text("NEUTRAL", "Crawled - currently not indexed")
        == "Rastreada: actualmente sin indexar"
    )
    assert translator.google_status_text("NEUTRAL", "URL is unknown to Google") == "Google no reconoce esta URL"


def test_unknown_or_already_spanish_coverage_passes_through():
    assert translator.translate_coverage("Rastreada: actualmente sin indexar") == "Rastreada: actualmente sin indexar"
    assert translator.google_status_text("FAIL", None) == "No indexada"


def test_is_indexed():
    assert translator.is_indexed("PASS")
    assert not translator.is_indexed("NEUTRAL")
    assert not translator.is_indexed(None)


def test_format_crawl_time_converts_timezone():
    assert translator.format_crawl_time("2024-05-10T18:30:00Z", "America/Mexico_City") == "2024-05-10 12:30:00"
    assert translator.format_crawl_time("2024-05-10T18:30:00.123456789Z", "UTC") == "2024-05-10 18:30:00"
    assert translator.format_crawl_time(None, "UTC") == "Sin rastreo registrado"


# --- columns ----------------------------------------------------------------

def test_detects_columns_by_alias_ignoring_accents():
    cmap = resolve_columns(["URL", "Último rastreo", "Estatus Google", "Estado", "Fecha de consulta"])
    assert cmap.indexes == {"url": 1, "last_crawl": 2, "google_status": 3, "process_status": 4, "last_check": 5}
    assert cmap.headers_to_create == {}


def test_creates_missing_output_columns_at_end():
    cmap = resolve_columns(["Cliente", "URL"])
    assert cmap["url"] == 2
    assert cmap.headers_to_create == {
        3: "Último rastreo de Google",
        4: "Estatus en Google",
        5: "Estado del proceso",
        6: "Fecha de consulta",
    }


def test_estado_google_not_confused_with_process_status():
    cmap = resolve_columns(["Link", "Estado Google", "Estado"])
    assert cmap["google_status"] == 2
    assert cmap["process_status"] == 3


def test_overrides_by_letter_and_name():
    cmap = resolve_columns(["A", "Dirección web", "x"], {"url": "Dirección web", "process_status": "E"})
    assert cmap["url"] == 2
    assert cmap["process_status"] == 5
    assert cmap.headers_to_create[5] == "Estado del proceso"


def test_url_fallback_and_missing_url():
    assert resolve_columns(["Url del artículo"])["url"] == 1
    with pytest.raises(ColumnDetectionError):
        resolve_columns(["Nombre", "Notas"])


def test_letter_to_index():
    assert letter_to_index("A") == 1
    assert letter_to_index("z") == 26
    assert letter_to_index("AA") == 27


# --- site matching -----------------------------------------------------------

def test_match_site_prefers_most_specific_prefix_then_domain():
    sites = ["sc-domain:ejemplo.com", "https://www.ejemplo.com/", "https://www.ejemplo.com/blog/"]
    assert match_site_for_url("https://www.ejemplo.com/blog/post", sites) == "https://www.ejemplo.com/blog/"
    assert match_site_for_url("https://tienda.ejemplo.com/x", sites) == "sc-domain:ejemplo.com"
    assert match_site_for_url("https://otro.com/", sites) is None
    assert match_site_for_url("https://noejemplo.com/", ["sc-domain:ejemplo.com"]) is None


def test_real_veraque_sheet_headers():
    headers = ["URL", "Last crawled", "Estatus Google", "Ultima Solicitud de Envío",
               "Comentarios Newemage", "Comentarios Veraque"]
    cmap = resolve_columns(headers)
    assert cmap["url"] == 1
    assert cmap["last_crawl"] == 2
    assert cmap["google_status"] == 3
    # "Ultima Solicitud de Envío" (D) y comentarios (E, F) no se tocan
    assert cmap.headers_to_create == {7: "Estado del proceso", 8: "Fecha de consulta"}
