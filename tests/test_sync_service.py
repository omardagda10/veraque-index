from types import SimpleNamespace

from googleapiclient.errors import HttpError

from app.config import Settings
from app.sync_service import SyncService


class FakeSheets:
    worksheet_title = "URLs"

    def __init__(self, values):
        self.values = values
        self.cells = {}
        self.history = []
        self.ensured = None

    def get_all_values(self):
        return self.values

    def ensure_columns(self, max_col):
        self.ensured = max_col

    def write_cells(self, cells):
        for r, c, v in cells:
            self.cells[(r, c)] = v

    def append_history(self, rows):
        self.history.extend(rows)


class FakeGSC:
    def __init__(self, results):
        self.results = results
        self.inspected = []

    def resolve_site(self, url):
        return None if "sin-propiedad" in url else "sc-domain:ejemplo.com"

    def inspect(self, url, site_url):
        self.inspected.append(url)
        result = self.results[url]
        if isinstance(result, Exception):
            raise result
        return result


def make_settings(**kw):
    base = dict(
        SPREADSHEET_ID="x", SHEET_GID=1, TIMEZONE="UTC", REQUEST_DELAY_SECONDS=0,
        MAX_URLS_PER_RUN=200, GOOGLE_SERVICE_ACCOUNT_JSON="", API_SECRET="s",
    )
    base.update(kw)
    return Settings(_env_file=None, **base)


def idx(url, verdict, coverage, crawl="2024-01-01T10:00:00Z"):
    return {"indexStatusResult": {"verdict": verdict, "coverageState": coverage, "lastCrawlTime": crawl}}


HEADERS = ["URL", "Último rastreo", "Estatus en Google", "Estado", "Fecha de consulta"]


def test_run_updates_rows_skips_completed_and_writes_history():
    sheets = FakeSheets([
        HEADERS,
        ["https://ejemplo.com/a", "", "", "", ""],
        ["https://ejemplo.com/b", "", "", "Completada", ""],
        ["", "", "", "", ""],
        ["https://ejemplo.com/c", "", "", "Pendiente", ""],
        ["https://sin-propiedad.com/", "", "", "", ""],
        ["ftp://mal", "", "", "", ""],
    ])
    gsc = FakeGSC({
        "https://ejemplo.com/a": idx("a", "PASS", "Submitted and indexed"),
        "https://ejemplo.com/c": idx("c", "NEUTRAL", "Discovered - currently not indexed", None),
    })
    service = SyncService(make_settings(), lambda: sheets, lambda: gsc, sleep=lambda _: None)

    summary = service.run()

    assert summary.status == "ok", summary.message
    assert gsc.inspected == ["https://ejemplo.com/a", "https://ejemplo.com/c"]
    assert summary.total_urls == 5
    assert summary.skipped_completed == 1
    assert (summary.indexed, summary.not_indexed, summary.errors) == (1, 1, 2)

    assert sheets.cells[(2, 4)] == "Completada"
    assert sheets.cells[(2, 3)] == "Enviada e indexada"
    assert sheets.cells[(2, 2)] == "2024-01-01 10:00:00"
    assert (2, 5) in sheets.cells
    assert (3, 4) not in sheets.cells  # fila completada intacta
    assert sheets.cells[(5, 4)] == "Pendiente"
    assert sheets.cells[(5, 2)] == "Sin rastreo registrado"
    assert sheets.cells[(6, 4)] == "Error"
    assert sheets.cells[(7, 4)] == "Error"

    assert len(sheets.history) == 4
    assert sheets.history[0][1] == "https://ejemplo.com/a"
    assert sheets.history[0][7] == "Completada"


def test_creates_missing_headers():
    sheets = FakeSheets([["URL"], ["https://ejemplo.com/a"]])
    gsc = FakeGSC({"https://ejemplo.com/a": idx("a", "PASS", "Submitted and indexed")})
    SyncService(make_settings(), lambda: sheets, lambda: gsc, sleep=lambda _: None).run()
    assert sheets.ensured == 5
    assert sheets.cells[(1, 4)] == "Estado del proceso"
    assert sheets.cells[(2, 4)] == "Completada"


def test_respects_max_urls_per_run_and_history_toggle():
    rows = [HEADERS] + [[f"https://ejemplo.com/{i}", "", "", "", ""] for i in range(5)]
    sheets = FakeSheets(rows)
    gsc = FakeGSC({f"https://ejemplo.com/{i}": idx(i, "FAIL", "URL is unknown to Google") for i in range(5)})
    service = SyncService(
        make_settings(MAX_URLS_PER_RUN=2, ENABLE_HISTORY=False), lambda: sheets, lambda: gsc, sleep=lambda _: None
    )
    summary = service.run()
    assert summary.processed == 2
    assert summary.left_for_next_run == 3
    assert sheets.history == []


def test_quota_error_stops_run_and_saves_progress():
    quota = HttpError(SimpleNamespace(status=429, reason="Too Many Requests"), b'{"error": {"message": "Quota exceeded"}}')
    sheets = FakeSheets([
        HEADERS,
        ["https://ejemplo.com/a", "", "", "", ""],
        ["https://ejemplo.com/b", "", "", "", ""],
        ["https://ejemplo.com/c", "", "", "", ""],
    ])
    gsc = FakeGSC({
        "https://ejemplo.com/a": idx("a", "PASS", "Submitted and indexed"),
        "https://ejemplo.com/b": quota,
        "https://ejemplo.com/c": idx("c", "PASS", "Submitted and indexed"),
    })
    summary = SyncService(make_settings(), lambda: sheets, lambda: gsc, sleep=lambda _: None).run()
    assert summary.status == "partial"
    assert summary.processed == 1
    assert summary.left_for_next_run == 2
    assert sheets.cells[(2, 4)] == "Completada"
    assert "https://ejemplo.com/c" not in gsc.inspected


def test_busy_when_already_running():
    service = SyncService(make_settings(), lambda: FakeSheets([HEADERS]), lambda: FakeGSC({}))
    service._lock.acquire()
    try:
        assert service.run().status == "busy"
    finally:
        service._lock.release()
