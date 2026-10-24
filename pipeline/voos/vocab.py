"""Vocabulário de status entre fontes (Nível 1 da camada ontológica).

`ontology/status_vocab.csv` mapeia (source, status_raw) → status_canon, event_class (classe do
modelo conceitual), status_kind (oficial/provisório) e confidence. Termos não mapeados são
acumulados em `unmapped()` para a verificação do build.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from functools import lru_cache

from .config import ONTOLOGY

VOCAB_PATH = ONTOLOGY / "status_vocab.csv"
_UNMAPPED: set[tuple[str, str]] = set()

CANON_ORDER = ["scheduled", "confirmed", "boarding", "departed", "landed", "operated",
               "delayed", "diverted", "cancelled", "schedule_withdrawn", "unknown"]
DISRUPTION = {"delayed", "diverted", "cancelled", "schedule_withdrawn"}


@dataclass(frozen=True)
class Status:
    status_canon: str
    event_class: str
    status_kind: str
    confidence: float
    definition: str = ""


@lru_cache(maxsize=1)
def load_vocab() -> dict[tuple[str, str], Status]:
    out: dict[tuple[str, str], Status] = {}
    with open(VOCAB_PATH, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            key = (row["source"].strip().lower(), row["status_raw"].strip().lower())
            out[key] = Status(row["status_canon"].strip(), row["event_class"].strip(),
                              row["status_kind"].strip(), float(row["confidence"]), row.get("definition", ""))
    return out


def canon(source: str, status_raw: str | None) -> Status:
    raw = (status_raw or "").strip()
    st = load_vocab().get((source.lower(), raw.lower()))
    if st is None:
        _UNMAPPED.add((source, raw))
        kind = "oficial" if source.lower() == "vra" else "provisório"
        return Status("unknown", "FlightLeg", kind, 0.0, "termo não mapeado")
    return st


def unmapped() -> list[tuple[str, str]]:
    return sorted(_UNMAPPED)


def vocab_rows() -> list[dict]:
    """Linhas do CSV como dicts (para o mart `status_vocab`)."""
    with open(VOCAB_PATH, newline="", encoding="utf-8") as f:
        return [dict(r) for r in csv.DictReader(f)]
