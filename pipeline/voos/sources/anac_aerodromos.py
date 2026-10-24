"""ANAC — lista de aeródromos públicos (dados abertos).

Fonte: ``voos.config.ANAC_AERODROMOS_CSV`` (~100 KB, atualizada ~mensalmente). Formato:

- codificação cp1252/latin-1, delimitador ``;``;
- linha 1 = ``Atualizado em: YYYY-MM-DD`` (vira a coluna ``updated_at``); cabeçalho na linha 2;
- ``LATGEOPOINT``/``LONGEOPOINT`` em graus decimais (ponto); ``Latitude``/``Longitude`` em GMS (ignoradas);
- ``Altitude`` com vírgula decimal; ``UF``/``UF Servido`` com o nome completo do estado;
- ``Município`` em CAIXA ALTA (convertido para Title Case em português); ``Município Servido`` já em Title Case.

Cache: ``data/raw/anac/AerodromosPublicos.csv`` via ``voos.http.cached_download`` (máx. 7 dias sem HEAD).
"""
from __future__ import annotations

import csv
import io
import re
from pathlib import Path

import pyarrow as pa

from ..config import ANAC_AERODROMOS_CSV, RAW
from ..http import cached_download, log

DEST = RAW / "anac" / "AerodromosPublicos.csv"
MAX_AGE_HOURS = 168

#: palavras que ficam em minúsculas no Title Case português (exceto na primeira posição)
SMALL_WORDS = frozenset({"de", "da", "do", "das", "dos", "e", "del"})

SCHEMA = pa.schema(
    [
        ("icao", pa.string()),
        ("ciad", pa.string()),
        ("name", pa.string()),
        ("municipio", pa.string()),
        ("uf_nome", pa.string()),
        ("municipio_servido", pa.string()),
        ("uf_servido_nome", pa.string()),
        ("lat", pa.float64()),
        ("lon", pa.float64()),
        ("altitude_m", pa.float64()),
        ("situacao", pa.string()),
        ("validade_registro", pa.string()),
        ("updated_at", pa.string()),
    ]
)

_ISO_DATE_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
_BR_DATE_RE = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{4})")


# --- helpers puros -----------------------------------------------------------
def _cap(part: str) -> str:
    """Capitaliza a primeira letra de `part` (já em minúsculas), respeitando apóstrofos e parênteses.

    'oeste' → 'Oeste'; "d'oeste" → "d'Oeste" (Santa Bárbara d'Oeste); '(sede)' → '(Sede)'.
    """
    if "'" in part:
        head, _, tail = part.partition("'")
        head = head if len(head) == 1 else _cap(head)
        return f"{head}'{_cap(tail)}"
    for j, ch in enumerate(part):
        if ch.isalpha():
            return part[:j] + ch.upper() + part[j + 1 :]
    return part


def title_case_pt(s: str | None) -> str | None:
    """Title Case com regras do português: 'SÃO GONÇALO DO AMARANTE' → 'São Gonçalo do Amarante'.

    Preposições/conjunções (de, da, do, das, dos, e) ficam minúsculas fora da primeira posição; partes
    separadas por hífen são capitalizadas ('GUAJARÁ-MIRIM' → 'Guajará-Mirim'). Vazio/None → None.
    """
    if s is None:
        return None
    words = s.split()
    if not words:
        return None
    out: list[str] = []
    for i, w in enumerate(words):
        lw = w.lower()
        if i > 0 and lw in SMALL_WORDS:
            out.append(lw)
        else:
            out.append("-".join(_cap(p) for p in lw.split("-")))
    return " ".join(out)


def parse_decimal(s: str | None) -> float | None:
    """Número em texto → float. Vírgula decimal ('894,0' → 894.0, '1.234,5' → 1234.5) ou ponto ('-29.994722')."""
    if s is None:
        return None
    t = s.strip().replace(" ", "")
    if not t:
        return None
    if "," in t:
        t = t.replace(".", "").replace(",", ".")
    try:
        return float(t)
    except ValueError:
        return None


def parse_date_br(s: str | None) -> str | None:
    """'26/12/2027' → '2027-12-26'; também aceita ISO; vazio/inválido → None."""
    if not s:
        return None
    m = _BR_DATE_RE.search(s)
    if m:
        d, mo, y = m.groups()
        return f"{y}-{int(mo):02d}-{int(d):02d}"
    m = _ISO_DATE_RE.search(s)
    if m:
        return m.group(0)
    return None


def _clean(v: str | None) -> str | None:
    if v is None:
        return None
    v = " ".join(v.split())
    return v or None


def updated_at_from_header(line: str) -> str | None:
    """'Atualizado em: 2026-10-15' → '2026-10-15' (aceita também dd/mm/yyyy)."""
    return parse_date_br(line)


# --- download / parse ----------------------------------------------------------
def download(force: bool = False) -> Path:
    return cached_download(ANAC_AERODROMOS_CSV, DEST, force=force, max_age_hours=MAX_AGE_HOURS)


def decode(raw: bytes) -> str:
    try:
        return raw.decode("cp1252")
    except UnicodeDecodeError:
        return raw.decode("latin-1")


def parse_text(text: str) -> pa.Table:
    """Texto já decodificado do CSV da ANAC → Table com colunas snake_case (ver SCHEMA)."""
    lines = text.lstrip("﻿").splitlines()
    if not lines:
        return SCHEMA.empty_table()
    updated_at = updated_at_from_header(lines[0])
    body = lines[1:] if updated_at or not lines[0].startswith("Código") else lines
    reader = csv.DictReader(io.StringIO("\n".join(body)), delimiter=";")
    rows: list[dict] = []
    for r in reader:
        icao = _clean(r.get("Código OACI"))
        if not icao:
            continue
        rows.append(
            {
                "icao": icao.upper(),
                "ciad": _clean(r.get("CIAD")),
                "name": _clean(r.get("Nome")),
                "municipio": title_case_pt(_clean(r.get("Município"))),
                "uf_nome": _clean(r.get("UF")),
                "municipio_servido": title_case_pt(_clean(r.get("Município Servido"))),
                "uf_servido_nome": _clean(r.get("UF Servido")),
                "lat": parse_decimal(r.get("LATGEOPOINT")),
                "lon": parse_decimal(r.get("LONGEOPOINT")),
                "altitude_m": parse_decimal(r.get("Altitude")),
                "situacao": _clean(r.get("Situação")),
                "validade_registro": parse_date_br(r.get("Validade do Registro")),
                "updated_at": updated_at,
            }
        )
    return pa.Table.from_pylist(rows, schema=SCHEMA)


def parse(path: Path) -> pa.Table:
    return parse_text(decode(Path(path).read_bytes()))


def load(force: bool = False) -> pa.Table:
    """Baixa (se preciso) e devolve a tabela de aeródromos públicos."""
    tbl = parse(download(force=force))
    log(f"anac aeródromos públicos: {tbl.num_rows} linhas (atualizado em {tbl['updated_at'][0].as_py() if tbl.num_rows else '?'})")
    return tbl
