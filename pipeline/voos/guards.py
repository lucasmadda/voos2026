"""Guardrails derivados do modelo conceitual (ontology/modelo-conceitual.md, seção "Guardrails").

Cada guarda recebe uma pyarrow.Table e devolve uma lista de violações (strings vazias = ok).
`enforce()` loga as violações no stderr e, se `strict`, lança GuardError para quebrar o build.
Regras: ver numeração no modelo conceitual.
"""
from __future__ import annotations

import os
from collections.abc import Callable

import duckdb
import pyarrow as pa

from .http import log

STRICT_DEFAULT = os.environ.get("VOOS_GUARDS_STRICT", "1") != "0"
PROVENANCE_COLS = ("source", "fetched_at", "status_kind", "confidence")


class GuardError(RuntimeError):
    pass


def _q(table: pa.Table, sql: str) -> list[tuple]:
    con = duckdb.connect()
    con.register("t", table)
    return con.execute(sql).fetchall()


def guard_cancelled_has_no_actual(table: pa.Table, actual_col: str = "actual_dep_utc") -> list[str]:
    """Regra 1: etapa cancelada não tem partida real."""
    if actual_col not in table.column_names or "status_canon" not in table.column_names:
        return []
    (n,) = _q(table, f"select count(*) from t where status_canon='cancelled' and {actual_col} is not null")[0]
    return [f"regra 1: {n} etapa(s) canceladas com {actual_col} preenchida"] if n else []


def guard_regular_legs_only(table: pa.Table) -> list[str]:
    """Regra 2: marts de FlightLeg regular só contêm DI=0 e Tipo Linha N (quando as colunas existem)."""
    out = []
    if "codigo_di" in table.column_names:
        (n,) = _q(table, "select count(*) from t where codigo_di is distinct from '0'")[0]
        if n:
            out.append(f"regra 2: {n} linha(s) com Código DI ≠ 0 em mart de etapas regulares")
    if "tipo_linha" in table.column_names:
        (n,) = _q(table, "select count(*) from t where tipo_linha is distinct from 'N'")[0]
        if n:
            out.append(f"regra 2: {n} linha(s) com Tipo Linha ≠ N em mart de etapas regulares")
    return out


def guard_provenance(table: pa.Table) -> list[str]:
    """Regra 6: toda linha de voo carrega source, fetched_at, status_kind e confidence."""
    missing = [c for c in PROVENANCE_COLS if c not in table.column_names]
    if missing:
        return [f"regra 6: colunas de proveniência ausentes: {', '.join(missing)}"]
    (n,) = _q(table, "select count(*) from t where source is null or fetched_at is null or status_kind is null or confidence is null")[0]
    return [f"regra 6: {n} linha(s) sem proveniência completa"] if n else []


def guard_status_kind_values(table: pa.Table) -> list[str]:
    if "status_kind" not in table.column_names:
        return []
    bad = _q(table, "select distinct status_kind from t where status_kind not in ('oficial','provisório')")
    return [f"status_kind inválido: {[b[0] for b in bad]}"] if bad else []


def guard_no_unknown_status(table: pa.Table, max_share: float = 0.0) -> list[str]:
    """Termos não mapeados pelo vocabulário aparecem como status_canon='unknown'."""
    if "status_canon" not in table.column_names:
        return []
    (n, total) = _q(table, "select count(*) filter (where status_canon='unknown'), count(*) from t")[0]
    if total and n / total > max_share:
        raws = _q(table, "select distinct source, status_raw from t where status_canon='unknown' limit 20") if "status_raw" in table.column_names else []
        return [f"{n}/{total} linha(s) com status não mapeado: {raws}"]
    return []


def guard_journey_connection(table: pa.Table, min_minutes: int = 45) -> list[str]:
    """Regra 4: toda Journey tem conexão ≥ 45 min e etapas no mesmo dia local da origem."""
    need = {"connection_min", "same_local_day"}
    if not need.issubset(table.column_names):
        return []
    (n,) = _q(table, f"select count(*) from t where connection_min < {min_minutes} or not same_local_day")[0]
    return [f"regra 4: {n} viagem(ns) com conexão < {min_minutes} min ou em dias diferentes"] if n else []


LEG_GUARDS: tuple[Callable[[pa.Table], list[str]], ...] = (
    guard_cancelled_has_no_actual,
    guard_provenance,
    guard_status_kind_values,
    guard_no_unknown_status,
)


def enforce(table: pa.Table, guards=LEG_GUARDS, name: str = "mart", strict: bool | None = None) -> pa.Table:
    """Aplica as guardas; loga; lança GuardError se strict (padrão: VOOS_GUARDS_STRICT != '0')."""
    strict = STRICT_DEFAULT if strict is None else strict
    violations: list[str] = []
    for g in guards:
        violations.extend(g(table))
    if violations:
        for v in violations:
            log(f"GUARD [{name}] {v}")
        if strict:
            raise GuardError(f"{name}: {len(violations)} violação(ões) das guardas do modelo")
    else:
        log(f"guards ok [{name}] ({table.num_rows} linhas)")
    return table
