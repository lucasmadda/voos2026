"""Dimensões de referência: aeroportos (``dim_airport``) e UF/região.

``dim_airport`` = união de
  (a) todos os aeródromos públicos da ANAC (``source='anac'``), enriquecidos com iata/scheduled_service/type do
      OurAirports (join por ICAO; fallback ``local_code = CIAD``);
  (b) aeroportos fora do Brasil com serviço regular no OurAirports (``source='ourairports'``), para resolver os
      destinos internacionais dos painéis (LIS, LIM, EZE, SCL, PTY, MIA, MVD, ASU, MAD, CDG…).

Depois aplica ``data/ref/airports_override.csv`` (icao, field, value), deduplica por ICAO (ANAC vence) e ordena
por país e ICAO. Toda data/hora é string; nenhuma coluna Arrow timestamp.
"""
from __future__ import annotations

import csv
import unicodedata
from functools import lru_cache

import pyarrow as pa

from ..config import AIRPORT_TZ, AIRPORT_TZ_DEFAULT, FOCUS_ORIGIN, HUB_AIRPORTS, NE_AIRPORTS, REF
from ..http import log
from ..io import duck
from ..sources import anac_aerodromos, ourairports
from ..sources.ourairports import TYPE_RANK_SQL

SCHEMA = pa.schema(
    [
        ("icao", pa.string()),
        ("iata", pa.string()),
        ("name", pa.string()),
        ("country", pa.string()),
        ("municipio", pa.string()),
        ("municipio_servido", pa.string()),
        ("uf", pa.string()),
        ("uf_nome", pa.string()),
        ("regiao", pa.string()),
        ("regiao_nome", pa.string()),
        ("lat", pa.float64()),
        ("lon", pa.float64()),
        ("tz", pa.string()),
        ("ciad", pa.string()),
        ("scheduled_service", pa.bool_()),
        ("is_focus_origin", pa.bool_()),
        ("is_ne", pa.bool_()),
        ("is_hub", pa.bool_()),
        ("source", pa.string()),
    ]
)

#: nomes alternativos aceitos na coluna `field` de airports_override.csv
OVERRIDE_FIELD_ALIASES = {"municipio_fisico": "municipio", "fuso": "tz", "timezone": "tz", "nome": "name"}


# --- UF / região -------------------------------------------------------------
def _norm(s: str) -> str:
    """Chave de comparação: sem acentos, casefold, espaços colapsados ('Sao paulo' == 'São Paulo')."""
    nfkd = unicodedata.normalize("NFKD", s)
    return " ".join("".join(c for c in nfkd if not unicodedata.combining(c)).casefold().split())


@lru_cache(maxsize=1)
def _ufs() -> dict[str, dict[str, str]]:
    """data/ref/ufs.csv indexado por nome normalizado E por sigla normalizada."""
    out: dict[str, dict[str, str]] = {}
    with open(REF / "ufs.csv", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            row = {k: (v or "").strip() for k, v in row.items()}
            out[_norm(row["uf_nome"])] = row
            out[_norm(row["uf"])] = row
    return out


def uf_row(name: str | None) -> dict[str, str] | None:
    """Linha de ufs.csv para um nome completo ('Rio Grande do Sul') ou sigla ('RS'); None se desconhecido."""
    if not name:
        return None
    return _ufs().get(_norm(name))


def uf_from_name(name: str | None) -> tuple[str | None, str | None, str | None]:
    """'Rio Grande do Sul' → ('RS', 'S', 'Sul'); aceita sigla; desconhecido → (None, None, None)."""
    row = uf_row(name)
    if row is None:
        return (None, None, None)
    return (row["uf"], row["regiao"], row["regiao_nome"])


# --- overrides ------------------------------------------------------------------
@lru_cache(maxsize=1)
def load_overrides() -> dict[str, dict[str, str]]:
    """data/ref/airports_override.csv → {icao: {coluna: valor}} (aliases de coluna já resolvidos)."""
    out: dict[str, dict[str, str]] = {}
    path = REF / "airports_override.csv"
    if not path.exists():
        return out
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            icao = (row.get("icao") or "").strip().upper()
            field = (row.get("field") or "").strip().lower()
            field = OVERRIDE_FIELD_ALIASES.get(field, field)
            if not icao or not field:
                continue
            if field not in SCHEMA.names:
                log(f"airports_override: coluna desconhecida {field!r} ({icao}); ignorada")
                continue
            out.setdefault(icao, {})[field] = (row.get("value") or "").strip()
    return out


def _coerce(field: str, value: str):
    """Converte o texto do override para o tipo da coluna no SCHEMA."""
    if value == "":
        return None
    t = SCHEMA.field(field).type
    if pa.types.is_boolean(t):
        return value.lower() in {"1", "true", "t", "yes", "sim", "y", "s"}
    if pa.types.is_floating(t):
        return anac_aerodromos.parse_decimal(value)
    return value


def apply_overrides(rec: dict, overrides: dict[str, str]) -> dict:
    """Aplica {coluna: valor-texto} a um registro já tipado (cópia)."""
    out = dict(rec)
    for field, value in overrides.items():
        out[field] = _coerce(field, value)
    return out


# --- dim_airport --------------------------------------------------------------------
_UNION_SQL = f"""
    with oa_br as (
        select *, row_number() over (partition by icao order by scheduled_service desc, {TYPE_RANK_SQL}, ident) rn
        from oa where country = 'BR' and icao is not null
    ), oa_br1 as (select * from oa_br where rn = 1),
    oa_lc as (
        select *, row_number() over (partition by local_code order by scheduled_service desc, {TYPE_RANK_SQL}, ident) rn
        from oa where country = 'BR' and local_code is not null
    ), oa_lc1 as (select * from oa_lc where rn = 1),
    br as (
        select
            a.icao,
            coalesce(o1.iata, o2.iata)                                          as iata,
            coalesce(a.name, o1.name, o2.name)                                  as name,
            'BR'                                                                as country,
            coalesce(a.municipio, a.municipio_servido)                          as municipio,
            coalesce(a.municipio_servido, o1.municipality, o2.municipality, a.municipio) as municipio_servido,
            coalesce(a.uf_nome, a.uf_servido_nome)                              as uf_nome,
            a.lat, a.lon,
            a.ciad,
            coalesce(o1.scheduled_service, o2.scheduled_service, false)         as scheduled_service,
            coalesce(o1.type, o2.type)                                          as type,
            'anac'                                                              as source
        from anac a
        left join oa_br1 o1 on o1.icao = a.icao
        left join oa_lc1 o2 on o1.icao is null and a.ciad is not null and o2.local_code = a.ciad
    ), intl as (
        select
            icao, iata, name, country,
            null::varchar as municipio,
            municipality  as municipio_servido,
            null::varchar as uf_nome,
            lat, lon,
            null::varchar as ciad,
            scheduled_service, type,
            'ourairports' as source
        from oa
        where country <> 'BR' and scheduled_service and icao is not null
    ), u as (
        select * from br union all select * from intl
    ), d as (
        select *, row_number() over (
            partition by icao
            order by case source when 'anac' then 0 else 1 end, scheduled_service desc, {TYPE_RANK_SQL}
        ) rn
        from u
    )
    select icao, iata, name, country, municipio, municipio_servido, uf_nome, lat, lon, ciad, scheduled_service, source
    from d where rn = 1
    order by country, icao
"""


def _finalize(rows: list[dict]) -> pa.Table:
    """Linhas da união (SQL) → registros completos: UF/região, fuso, flags, overrides; Table com SCHEMA."""
    overrides = load_overrides()
    ne, hubs = set(NE_AIRPORTS), set(HUB_AIRPORTS)
    out: list[dict] = []
    for r in rows:
        icao = r["icao"]
        is_br = r["country"] == "BR"
        uf = uf_row(r["uf_nome"]) if is_br else None
        if is_br and r["uf_nome"] and uf is None:
            log(f"dim_airport: UF desconhecida {r['uf_nome']!r} em {icao}")
        rec = {
            "icao": icao,
            "iata": r["iata"],
            "name": r["name"],
            "country": r["country"],
            "municipio": r["municipio"],
            "municipio_servido": r["municipio_servido"],
            "uf": uf["uf"] if uf else None,
            "uf_nome": uf["uf_nome"] if uf else None,
            "regiao": uf["regiao"] if uf else None,
            "regiao_nome": uf["regiao_nome"] if uf else None,
            "lat": r["lat"],
            "lon": r["lon"],
            "tz": AIRPORT_TZ.get(icao, AIRPORT_TZ_DEFAULT) if is_br else "UTC",
            "ciad": r["ciad"],
            "scheduled_service": bool(r["scheduled_service"]),
            "is_focus_origin": icao == FOCUS_ORIGIN,
            "is_ne": icao in ne,
            "is_hub": icao in hubs,
            "source": r["source"],
        }
        if icao in overrides:
            rec = apply_overrides(rec, overrides[icao])
        out.append(rec)
    out.sort(key=lambda x: (x["country"] or "", x["icao"]))
    return pa.Table.from_pylist(out, schema=SCHEMA)


def build_dim_airport(anac: pa.Table, oa: pa.Table) -> pa.Table:
    """Monta a dimensão a partir das duas tabelas-fonte já carregadas (puro; testável sem rede)."""
    con = duck()
    try:
        con.register("anac", anac)
        con.register("oa", oa)
        rows = con.sql(_UNION_SQL).to_arrow_table().to_pylist()
    finally:
        con.close()
    tbl = _finalize(rows)
    missing = [a for a in [FOCUS_ORIGIN, *NE_AIRPORTS, *HUB_AIRPORTS] if a not in set(tbl["icao"].to_pylist())]
    if missing:
        log(f"dim_airport: aeroportos do escopo ausentes: {missing}")
    return tbl


@lru_cache(maxsize=1)
def dim_airport() -> pa.Table:
    """Dimensão de aeroportos (ANAC + OurAirports + overrides). Cacheada no processo."""
    tbl = build_dim_airport(anac_aerodromos.load(), ourairports.load())
    n_br = sum(1 for c in tbl["country"].to_pylist() if c == "BR")
    log(f"dim_airport: {tbl.num_rows} aeroportos ({n_br} BR, {tbl.num_rows - n_br} exterior)")
    return tbl


@lru_cache(maxsize=1)
def iata_to_icao() -> dict[str, str]:
    """{iata: icao} a partir de dim_airport(); em caso de conflito, a linha da ANAC (BR) vence."""
    tbl = dim_airport()
    pairs = sorted(
        zip(tbl["iata"].to_pylist(), tbl["icao"].to_pylist(), tbl["source"].to_pylist()),
        key=lambda t: (0 if t[2] == "anac" else 1, t[1]),
    )
    out: dict[str, str] = {}
    for iata, icao, _src in pairs:
        if iata and iata not in out:
            out[iata] = icao
    return out
