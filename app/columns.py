"""Detección de columnas de la hoja a partir de los encabezados (lógica pura, sin red)."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

# Campos que el servicio necesita, en orden de prioridad de detección.
FIELDS = ("url", "last_crawl", "google_status", "process_status", "last_check")

# Encabezado que se crea si la columna no existe en la hoja.
DEFAULT_HEADERS: dict[str, str] = {
    "url": "URL",
    "last_crawl": "Último rastreo de Google",
    "google_status": "Estatus en Google",
    "process_status": "Estado del proceso",
    "last_check": "Fecha de consulta",
}

# Alias aceptados (se comparan normalizados: minúsculas, sin acentos ni signos).
ALIASES: dict[str, tuple[str, ...]] = {
    "url": (
        "url", "urls", "link", "links", "enlace", "enlaces", "pagina", "paginas",
        "url pagina", "url de la pagina", "direccion", "direccion url",
    ),
    "last_crawl": (
        "ultimo rastreo", "ultimo rastreo de google", "ultima visita", "ultima visita de google",
        "fecha de rastreo", "fecha rastreo", "fecha ultimo rastreo", "rastreo", "last crawl",
        "last crawl time", "last crawled", "visita de google",
    ),
    "google_status": (
        "estatus en google", "estatus google", "estatus de google", "estado en google",
        "estado google", "estado de google", "status google", "google status", "cobertura",
        "estado de indexacion", "estatus de indexacion", "indexacion", "coverage",
    ),
    "process_status": (
        "estado del proceso", "estado proceso", "estatus del proceso", "estatus proceso",
        "estado", "estatus", "status", "proceso", "estado revision",
    ),
    "last_check": (
        "fecha de consulta", "fecha consulta", "fecha de revision", "fecha revision",
        "ultima revision", "ultima consulta", "fecha de peticion", "fecha peticion",
        "fecha y hora de consulta", "fecha de verificacion", "last check", "checked at",
    ),
}

_LETTERS_RE = re.compile(r"^[A-Za-z]{1,3}$")


def normalize_header(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^a-z0-9]+", " ", text.lower())
    return " ".join(text.split())


def letter_to_index(letters: str) -> int:
    """'A' -> 1, 'Z' -> 26, 'AA' -> 27 (índice de columna 1-based)."""
    idx = 0
    for ch in letters.upper():
        idx = idx * 26 + (ord(ch) - ord("A") + 1)
    return idx


@dataclass
class ColumnMap:
    """Índices 1-based de cada campo y encabezados que hay que crear."""

    indexes: dict[str, int] = field(default_factory=dict)
    headers_to_create: dict[int, str] = field(default_factory=dict)
    detected_by: dict[str, str] = field(default_factory=dict)

    def __getitem__(self, key: str) -> int:
        return self.indexes[key]


class ColumnDetectionError(ValueError):
    pass


def resolve_columns(headers: list[str], overrides: dict[str, str] | None = None) -> ColumnMap:
    """Determina en qué columna está cada campo.

    Prioridad: 1) variable COL_* (letra o nombre exacto), 2) alias conocidos,
    3) para la URL, cualquier encabezado que contenga "url". Las columnas de salida
    que no existan se añaden al final de la fila de encabezados.
    """
    overrides = overrides or {}
    normalized = [normalize_header(h) for h in headers]
    result = ColumnMap()
    used: set[int] = set()

    def assign(fld: str, idx: int, how: str) -> None:
        result.indexes[fld] = idx
        result.detected_by[fld] = how
        used.add(idx)

    # 1) Overrides explícitos
    for fld in FIELDS:
        raw = (overrides.get(fld) or "").strip()
        if not raw:
            continue
        norm = normalize_header(raw)
        if norm in normalized and normalized.index(norm) + 1 not in used:
            assign(fld, normalized.index(norm) + 1, f"COL override (encabezado '{raw}')")
        elif _LETTERS_RE.match(raw):
            assign(fld, letter_to_index(raw), f"COL override (columna {raw.upper()})")
        else:
            raise ColumnDetectionError(
                f"La columna configurada para '{fld}' ('{raw}') no existe en los encabezados."
            )

    # 2) Alias exactos
    for fld in FIELDS:
        if fld in result.indexes:
            continue
        for alias in ALIASES[fld]:
            matches = [i + 1 for i, h in enumerate(normalized) if h == alias and i + 1 not in used]
            if matches:
                assign(fld, matches[0], f"encabezado '{headers[matches[0] - 1]}'")
                break

    # 3) Fallback para la URL
    if "url" not in result.indexes:
        for i, h in enumerate(normalized):
            if i + 1 not in used and ("url" in h.split() or h.startswith("url")):
                assign("url", i + 1, f"encabezado '{headers[i]}' (contiene 'url')")
                break

    if "url" not in result.indexes:
        raise ColumnDetectionError(
            "No se encontró la columna de URLs. Nómbrala 'URL' o define COL_URL en las variables de entorno."
        )

    # 4) Columnas de salida faltantes: se crean al final
    next_col = max([len(headers), *used]) + 1
    for fld in FIELDS:
        if fld in result.indexes:
            continue
        result.indexes[fld] = next_col
        result.headers_to_create[next_col] = DEFAULT_HEADERS[fld]
        result.detected_by[fld] = f"creada como '{DEFAULT_HEADERS[fld]}'"
        next_col += 1

    # 5) Columnas asignadas por letra que no tienen encabezado: se les pone uno
    for fld in FIELDS:
        idx = result.indexes[fld]
        if idx not in result.headers_to_create and (idx > len(headers) or not headers[idx - 1].strip()):
            result.headers_to_create[idx] = DEFAULT_HEADERS[fld]

    return result
