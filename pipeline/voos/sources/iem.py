"""IEM ASOS — arquivo de METAR/SPECI do Iowa Environmental Mesonet (download bruto em CSV).

Endpoint: https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py (GET). Parâmetros usados:
station=SBPA,SBSV,… (lista separada por vírgula), data=all, sts/ets em ISO UTC, tz=Etc/UTC,
format=onlycomma, missing=empty, trace=empty, report_type=3,4 (3 = METAR de rotina, 4 = SPECI), latlon=no.

Limites do servidor: 1 pedido/segundo por IP (429 se mais rápido, 503 sob carga) e no máximo
1000 estação-ano por pedido. O servidor NÃO envia ETag nem Last-Modified, então o cache aqui é por
idade, não por validador:

- `max_age_hours=None` → janela fechada (mês passado): se o arquivo existe, nunca é rebaixado;
- `max_age_hours=h`    → janela recente: rebaixa só se a cópia local tiver mais de `h` horas.

Arquivos: data/raw/iem/asos_<YYYYMMDDTHHMM>_<YYYYMMDDTHHMM>_<n>stations_<sha1[:8]>.csv

Um lock de arquivo (data/raw/iem/.lock) serializa os pedidos entre processos (os data loaders
do Observable podem rodar em paralelo) e garante o intervalo mínimo de 1,1 s entre pedidos.
"""
from __future__ import annotations

import fcntl
import hashlib
import time
import urllib.parse
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx

from ..config import IEM_ASOS_URL, RAW
from ..http import cached_download, log, source_stamp

IEM_DIR = RAW / "iem"
MIN_INTERVAL_S = 1.1          # limite do IEM: 1 pedido/segundo por IP
RETRY_STATUS = {429, 500, 502, 503, 504}
RETRY_WAITS_S = (5, 15, 45)   # backoff após 429/503
ASOS_PARAMS = {
    "data": "all",
    "tz": "Etc/UTC",
    "format": "onlycomma",
    "missing": "empty",
    "trace": "empty",
    "report_type": "3,4",
    "latlon": "no",
}


# --- helpers puros ------------------------------------------------------------------------------

def as_utc(dt: datetime) -> datetime:
    """Datetime ingênuo é tratado como UTC; com fuso é convertido para UTC."""
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def _stamp(dt: datetime) -> str:
    return f"{as_utc(dt):%Y%m%dT%H%M}"


def station_hash(stations: Sequence[str]) -> str:
    """8 primeiros hex do sha1 da lista de estações separada por vírgula (na ordem dada)."""
    return hashlib.sha1(",".join(stations).encode("ascii")).hexdigest()[:8]


def build_url(stations: Sequence[str], start_utc: datetime, end_utc: datetime) -> str:
    params = {
        "station": ",".join(stations),
        **ASOS_PARAMS,
        "sts": f"{as_utc(start_utc):%Y-%m-%dT%H:%MZ}",
        "ets": f"{as_utc(end_utc):%Y-%m-%dT%H:%MZ}",
    }
    return f"{IEM_ASOS_URL}?{urllib.parse.urlencode(params)}"


def cache_path(stations: Sequence[str], start_utc: datetime, end_utc: datetime) -> Path:
    return IEM_DIR / (
        f"asos_{_stamp(start_utc)}_{_stamp(end_utc)}_{len(stations)}stations_{station_hash(stations)}.csv"
    )


def month_windows(start_date: date, end_date: date) -> list[tuple[datetime, datetime]]:
    """Divide [start_date, end_date] (inclusive) em janelas [sts, ets) por mês-calendário UTC.

    A primeira janela começa em start_date 00:00Z e a última termina em end_date+1 00:00Z;
    as intermediárias cobrem meses inteiros. O IEM trata `ets` como exclusivo.
    """
    if end_date < start_date:
        return []
    utc = timezone.utc
    hard_start = datetime(start_date.year, start_date.month, start_date.day, tzinfo=utc)
    hard_end = datetime(end_date.year, end_date.month, end_date.day, tzinfo=utc) + timedelta(days=1)
    out: list[tuple[datetime, datetime]] = []
    cursor = datetime(start_date.year, start_date.month, 1, tzinfo=utc)
    while cursor < hard_end:
        nxt = datetime(cursor.year + (cursor.month == 12), cursor.month % 12 + 1, 1, tzinfo=utc)
        out.append((max(cursor, hard_start), min(nxt, hard_end)))
        cursor = nxt
    return out


def looks_like_asos_csv(path: Path) -> bool:
    """Primeira linha não-comentário deve ser o cabeçalho 'station,valid,…' (rejeita HTML/erros)."""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                if line.startswith("#"):
                    continue
                return line.lower().startswith("station,valid")
    except OSError:
        return False
    return False


# --- rede ---------------------------------------------------------------------------------------

@contextmanager
def _iem_lock() -> Iterator[None]:
    IEM_DIR.mkdir(parents=True, exist_ok=True)
    with open(IEM_DIR / ".lock", "a+") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def _throttle() -> None:
    """Garante ≥ MIN_INTERVAL_S desde o último pedido ao IEM feito por qualquer processo."""
    marker = IEM_DIR / ".last_request"
    try:
        last = float(marker.read_text().strip())
    except (OSError, ValueError):
        last = 0.0
    wait = MIN_INTERVAL_S - (time.time() - last)
    if wait > 0:
        time.sleep(wait)
    marker.write_text(f"{time.time():.3f}")


def _local_age_hours(url: str, dest: Path) -> float:
    stamp = source_stamp(url).get("fetched_at")
    if stamp:
        fetched = datetime.fromisoformat(stamp)
    else:
        fetched = datetime.fromtimestamp(dest.stat().st_mtime, tz=timezone.utc)
    return (datetime.now(timezone.utc) - fetched).total_seconds() / 3600


def _download(url: str, dest: Path, force: bool) -> Path:
    """GET com throttle e retentativas em 429/5xx; valida que o corpo é o CSV esperado."""
    last_err: Exception | None = None
    for attempt in range(len(RETRY_WAITS_S) + 1):
        _throttle()
        try:
            path = cached_download(url, dest, force=force)
        except (httpx.HTTPStatusError, httpx.TransportError) as e:
            retryable = isinstance(e, httpx.TransportError) or e.response.status_code in RETRY_STATUS
            if not retryable or attempt == len(RETRY_WAITS_S):
                raise
            last_err = e
            log(f"IEM: {e!r}; esperando {RETRY_WAITS_S[attempt]}s antes de tentar de novo")
            time.sleep(RETRY_WAITS_S[attempt])
            force = True
            continue
        if looks_like_asos_csv(path):
            return path
        head = path.read_text(encoding="utf-8", errors="replace")[:160].replace("\n", " ")
        path.unlink(missing_ok=True)
        last_err = RuntimeError(f"resposta do IEM não é CSV ASOS: {head!r}")
        if attempt == len(RETRY_WAITS_S):
            break
        log(f"{last_err}; nova tentativa em {RETRY_WAITS_S[attempt]}s")
        time.sleep(RETRY_WAITS_S[attempt])
        force = True
    raise RuntimeError(f"IEM: falha ao baixar {url}: {last_err}")


def fetch_asos(stations: Sequence[str], start_utc: datetime, end_utc: datetime,
               max_age_hours: float | None = None) -> Path:
    """Baixa (ou reaproveita do cache) o CSV ASOS de `stations` na janela [start_utc, end_utc).

    `max_age_hours=None`: janela fechada — cópia local existente é definitiva (nunca rebaixa).
    `max_age_hours=0.5`: janela recente — rebaixa quando a cópia local tiver > 30 min.
    """
    if not stations:
        raise ValueError("fetch_asos: lista de estações vazia")
    start_utc, end_utc = as_utc(start_utc), as_utc(end_utc)
    if end_utc <= start_utc:
        raise ValueError(f"fetch_asos: janela vazia {start_utc:%Y-%m-%dT%H:%MZ} → {end_utc:%Y-%m-%dT%H:%MZ}")
    url = build_url(stations, start_utc, end_utc)
    dest = cache_path(stations, start_utc, end_utc)
    with _iem_lock():
        if dest.exists() and looks_like_asos_csv(dest):
            if max_age_hours is None:
                return dest
            age = _local_age_hours(url, dest)
            if age < max_age_hours:
                return dest
            log(f"IEM {dest.name}: cópia local com {age:.1f} h (> {max_age_hours} h); rebaixando")
            return _download(url, dest, force=True)
        log(f"IEM {len(stations)} estações {start_utc:%Y-%m-%dT%H:%MZ} → {end_utc:%Y-%m-%dT%H:%MZ}")
        return _download(url, dest, force=False)
