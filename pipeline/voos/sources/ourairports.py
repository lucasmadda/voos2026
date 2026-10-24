"""OurAirports — base mundial de aeroportos (domínio público).

Fonte: ``voos.config.OURAIRPORTS_CSV`` (~12,7 MB, UTF-8, vírgula, campos entre aspas). Colunas usadas:
ident, type, name, latitude_deg, longitude_deg, iso_country, iso_region ('BR-RS'), municipality (cidade
SERVIDA, ex.: SBGR → 'São Paulo'), scheduled_service ('yes'/'no'), icao_code, iata_code, local_code (no Brasil
= CIAD da ANAC, ex.: SBPA → 'RS0001').

Cache compartilhado com o mart ao vivo: ``data/raw/ourairports/airports.csv`` (máx. 7 dias sem HEAD).
"""
from __future__ import annotations

from pathlib import Path

import pyarrow as pa

from ..config import OURAIRPORTS_CSV, RAW
from ..http import cached_download, log
from ..io import duck

DEST = RAW / "ourairports" / "airports.csv"
MAX_AGE_HOURS = 168

#: ordem de preferência quando há mais de uma linha para o mesmo código
TYPE_RANK_SQL = (
    "case type when 'large_airport' then 0 when 'medium_airport' then 1 when 'small_airport' then 2 "
    "when 'seaplane_base' then 3 when 'heliport' then 4 when 'balloonport' then 5 when 'closed' then 9 else 6 end"
)


def download(force: bool = False) -> Path:
    return cached_download(OURAIRPORTS_CSV, DEST, force=force, max_age_hours=MAX_AGE_HOURS)


def parse(path: Path) -> pa.Table:
    """CSV OurAirports → Table (ident, icao, iata, name, lat, lon, country, region, municipality,
    scheduled_service, local_code, type) só com linhas úteis: serviço regular OU Brasil com código ICAO.

    `icao` = icao_code; quando vazio, usa `ident` se parecer um código ICAO (4 letras). Milhares de aeródromos
    brasileiros pequenos só têm o código no `ident`.
    """
    p = str(Path(path)).replace("'", "''")
    sql = f"""
        with raw as (
            select * from read_csv('{p}', all_varchar=true, header=true)
        ), x as (
            select
                ident,
                coalesce(nullif(trim(icao_code), ''),
                         case when regexp_matches(ident, '^[A-Z]{{4}}$') then ident end) as icao,
                nullif(trim(iata_code), '')                          as iata,
                nullif(trim(name), '')                               as name,
                try_cast(latitude_deg as double)                     as lat,
                try_cast(longitude_deg as double)                    as lon,
                nullif(trim(iso_country), '')                        as country,
                nullif(trim(iso_region), '')                         as region,
                nullif(trim(municipality), '')                       as municipality,
                coalesce(scheduled_service = 'yes', false)           as scheduled_service,
                nullif(trim(local_code), '')                         as local_code,
                nullif(trim(type), '')                               as type
            from raw
        )
        select * from x
        where scheduled_service or (country = 'BR' and icao is not null)
        order by country, icao nulls last, ident
    """
    con = duck()
    try:
        return con.sql(sql).to_arrow_table()
    finally:
        con.close()


def load(force: bool = False) -> pa.Table:
    """Baixa (se preciso) e devolve a tabela filtrada do OurAirports."""
    tbl = parse(download(force=force))
    log(f"ourairports: {tbl.num_rows} linhas (serviço regular ou BR com ICAO)")
    return tbl
