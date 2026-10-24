"""Fusos horários. Regra do projeto: tudo armazenado em UTC; "dia" da análise é o dia local do aeroporto.

- VRA (ANAC): datas ingênuas em horário de Brasília (UTC−3) para TODOS os aeroportos → +3 h.
- SIROS: UTC.
- Fraport: datas ingênuas no horário local do aeroporto; `scheduled_time`/`estimated_time` só HH:MM
  (rollover de meia-noite resolvido contra o horário previsto original).
- IEM/REDEMET: UTC.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from .config import AIRPORT_TZ, AIRPORT_TZ_DEFAULT

UTC = timezone.utc
BRT = timezone(timedelta(hours=-3), "BRT")


def airport_tz(icao: str | None) -> ZoneInfo:
    return ZoneInfo(AIRPORT_TZ.get(icao or "", AIRPORT_TZ_DEFAULT))


def brasilia_naive_to_utc(dt: datetime) -> datetime:
    """VRA: 'dd/mm/yyyy HH:MM' em horário de Brasília → UTC."""
    return dt.replace(tzinfo=BRT).astimezone(UTC)


def local_naive_to_utc(dt: datetime, icao: str) -> datetime:
    return dt.replace(tzinfo=airport_tz(icao)).astimezone(UTC)


def utc_to_local(dt: datetime, icao: str) -> datetime:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(airport_tz(icao))


def local_day(dt_utc: datetime, icao: str) -> date:
    return utc_to_local(dt_utc, icao).date()


def hhmm_near(hhmm: str, base_local: datetime) -> datetime | None:
    """Resolve 'HH:MM' (sem data) para o datetime local mais próximo de `base_local` (±12 h).

    Fraport devolve `estimated_time` como HH:MM; um voo previsto às 23:50 e estimado para 00:40
    pertence ao dia seguinte. Devolve None para strings vazias ou inválidas.
    """
    if not hhmm or ":" not in hhmm:
        return None
    try:
        h, m = (int(x) for x in hhmm.split(":")[:2])
    except ValueError:
        return None
    cand = base_local.replace(hour=h, minute=m, second=0, microsecond=0)
    best = cand
    for delta in (-1, 1):
        alt = cand + timedelta(days=delta)
        if abs((alt - base_local).total_seconds()) < abs((best - base_local).total_seconds()):
            best = alt
    return best


def parse_vra_datetime(s: str | None) -> datetime | None:
    """'24/10/2026 10:30' (Brasília) → datetime UTC; vazio → None."""
    if not s or not s.strip():
        return None
    s = s.strip()
    for fmt in ("%d/%m/%Y %H:%M", "%d/%m/%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return brasilia_naive_to_utc(datetime.strptime(s, fmt))
        except ValueError:
            continue
    return None
