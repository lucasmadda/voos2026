"""Chave canônica de voo e crosswalks de companhias.

flight_key = {carrier_icao}-{número com 4 dígitos}-{origem ICAO}-{partida prevista ORIGINAL em UTC, YYYYMMDDTHHMMZ}
Ex.: VRA 'GLO;1979;SBPA;24/10/2026 10:30', SIROS 'GLO 1979 SBPA 13:30Z' e Fraport 'G31979 2026-10-24 10:30:00'
→ todos 'GLO-1979-SBPA-20261024T1330Z'. Remarcações não mudam a chave.
"""
from __future__ import annotations

import csv
import re
from datetime import datetime
from functools import lru_cache

from .config import REF

_NUM_RE = re.compile(r"^\s*([A-Z]?)\s*0*(\d{1,4})\s*$")
_FRAPORT_RE = re.compile(r"^\s*([A-Z0-9]{2})\s*0*(\d{1,4})\s*$")


def normalize_number(raw: str | int | None) -> tuple[str, str]:
    """'0904' → ('904',''); 'Z9628' → ('9628','Z'); 1979 → ('1979',''). Inválido → ('', raw)."""
    if raw is None:
        return "", ""
    s = str(raw).strip().upper()
    m = _NUM_RE.match(s)
    if not m:
        return "", s
    prefix, num = m.group(1), m.group(2)
    return str(int(num)), prefix


def flight_key(carrier_icao: str, number: str | int, origin_icao: str, sched_dep_utc: datetime) -> str:
    num, _prefix = normalize_number(number)
    if not num:
        raise ValueError(f"número de voo inválido: {number!r}")
    return f"{carrier_icao.upper()}-{int(num):04d}-{origin_icao.upper()}-{sched_dep_utc:%Y%m%dT%H%MZ}"


@lru_cache(maxsize=1)
def load_carriers() -> dict:
    """Lê data/ref/carriers.csv → {'by_iata': {...}, 'by_icao': {...}}."""
    by_iata, by_icao = {}, {}
    with open(REF / "carriers.csv", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            row = {k: (v or "").strip() for k, v in row.items()}
            if row["iata"]:
                by_iata[row["iata"]] = row
            by_icao.setdefault(row["icao"], row)
    return {"by_iata": by_iata, "by_icao": by_icao}


def carrier_icao_from_iata(iata: str) -> str | None:
    return load_carriers()["by_iata"].get(iata.upper(), {}).get("icao")


def carrier_group(icao: str) -> str:
    return load_carriers()["by_icao"].get(icao.upper(), {}).get("group", "outras")


def split_fraport_flight(code: str) -> tuple[str, str]:
    """'G31979' → ('G3', '1979'); '2Z1234' → ('2Z', '1234'). Inválido → ('', code)."""
    m = _FRAPORT_RE.match(code or "")
    if not m:
        return "", (code or "").strip()
    return m.group(1), str(int(m.group(2)))
