"""Meteorologia (METAR/SPECI do IEM ASOS) → reportes classificados, agregados por hora UTC e por dia local.

Três tabelas (todas com datas como STRING, nunca timestamps Arrow):

- `parse_asos` / `metar_recent`: um reporte por linha, com visibilidade em metros, teto em pés e as
  flags operacionais imc / red / below_cat1 / convective / gusty + `severity` 0–3.
- `metar_hourly`: pior condição por aeroporto × hora UTC (min vis, min teto, max severidade, …).
- `weather_daily`: horas em IMC / vermelho / convecção por aeroporto × dia LOCAL (fuso do aeroporto).

Limiares (ICAO/DECEA, aproximados para operação comercial):
  imc        vis < 5000 m ou teto < 1500 ft      red     vis < 1500 m ou teto < 600 ft
  below_cat1 vis < 550 m  ou teto < 200 ft       gusty   rajada ≥ 25 kt
  convective TS/SQ/FC/GR/GS como código de tempo presente (inclui VC·/RE·, p.ex. VCTS, TSRA, RETS),
             nuvem CB (FEW030CB) ou chuva forte (+RA/+SHRA). TCU sozinho NÃO conta.
  severity   3 abaixo CAT I > 2 vermelho|convectivo|rajadas > 1 IMC > 0 VMC

Notas sobre a fonte: o IEM não devolve `report_type` nem com `data=report_type`; derivamos
3 (METAR de rotina) quando o minuto é :00 e 4 (SPECI) caso contrário (METAR brasileiro é horário).
`vsby` vem em milhas com 2 decimais (±8 m): convertemos para metros e arredondamos à resolução do
METAR (50 m abaixo de 800 m, 100 m acima) para recuperar o valor reportado (3000 m, não 2993).
METAR brasileiro não reporta precipitação acumulada (`p01i` vazio/0) — coluna ignorada.
"""
from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pyarrow as pa

from ..config import IEM_STATIONS
from ..http import log
from ..io import duck
from ..sources.iem import fetch_asos, month_windows
from ..tz import airport_tz

SEVERITY_LABELS = {0: "VMC", 1: "IMC", 2: "vermelho", 3: "abaixo CAT I"}
RECENT_MAX_AGE_HOURS = 0.5
#: meses encerrados há menos que isto ainda são rebaixados (o IEM pode receber reportes atrasados)
CLOSED_GRACE = timedelta(days=1)

REPORT_SCHEMA = pa.schema([
    ("icao", pa.string()),
    ("valid_utc", pa.string()),
    ("report_type", pa.int64()),
    ("vis_m", pa.float64()),
    ("ceiling_ft", pa.int64()),
    ("sky", pa.string()),
    ("wx", pa.string()),
    ("wind_dir", pa.int64()),
    ("wind_kt", pa.float64()),
    ("gust_kt", pa.float64()),
    ("temp_c", pa.float64()),
    ("dewp_c", pa.float64()),
    ("pressure_hpa", pa.float64()),
    ("metar_raw", pa.string()),
    ("imc", pa.bool_()),
    ("red", pa.bool_()),
    ("below_cat1", pa.bool_()),
    ("convective", pa.bool_()),
    ("gusty", pa.bool_()),
    ("severity", pa.int64()),
    ("severity_label", pa.string()),
])

HOURLY_SCHEMA = pa.schema([
    ("icao", pa.string()),
    ("hour_utc", pa.string()),
    ("min_vis_m", pa.float64()),
    ("min_ceiling_ft", pa.int64()),
    ("max_severity", pa.int64()),
    ("severity_label", pa.string()),
    ("any_convective", pa.bool_()),
    ("any_red", pa.bool_()),
    ("any_imc", pa.bool_()),
    ("max_gust_kt", pa.float64()),
    ("n_reports", pa.int64()),
    ("wx_all", pa.string()),
])

DAILY_SCHEMA = pa.schema([
    ("icao", pa.string()),
    ("date_local", pa.string()),
    ("hours_imc", pa.int64()),
    ("hours_red", pa.int64()),
    ("hours_convective", pa.int64()),
    ("min_vis_m", pa.float64()),
    ("min_ceiling_ft", pa.int64()),
    ("max_gust_kt", pa.float64()),
    ("max_severity", pa.int64()),
    ("n_hours", pa.int64()),
])

# Colunas do CSV do IEM que usamos (as demais são ignoradas; as ausentes viram NULL)
RAW_COLUMNS = [
    "station", "valid", "tmpf", "dwpf", "drct", "sknt", "alti", "vsby", "gust",
    "skyc1", "skyc2", "skyc3", "skyc4", "skyl1", "skyl2", "skyl3", "skyl4", "wxcodes", "metar",
]

# Grupo de tempo presente (só letras, pares de 2) contendo TS/GR/GS/SQ/FC alinhado em 2 letras:
# casa 'TS', 'TSRA', '+TSRA', 'VCTS', 'RETS', 'SHGR'; não casa 'SBGR', 'FEW040TCU', 'NOSIG', 'CAVOK'.
WX_CONVECTIVE_RE = r"(^|\s)[+-]?([A-Z]{2})*?(TS|GR|GS|SQ|FC)([A-Z]{2})*(\s|$)"
# Precipitação forte com chuva: '+RA', '+SHRA', '+TSRA', '+RASN'
WX_HEAVY_RAIN_RE = r"(^|\s)\+([A-Z]{2})*?RA([A-Z]{2})*(\s|$)"
# Camada de nuvem cumulonimbus: 'FEW030CB', 'SCT025CB', '///CB'
CB_LAYER_RE = r"(^|\s)(FEW|SCT|BKN|OVC|VV)?(\d{3}|///)CB(\s|$)"
# Prefixo do METAR bruto a descartar antes de procurar códigos: tipo, indicador da estação e hora
METAR_PREFIX_RE = r"^\s*(METAR\s+|SPECI\s+)?(COR\s+)?[A-Z][A-Z0-9]{3}\s+\d{6}Z\s*"

_LABEL_SQL = "CASE {v} WHEN 3 THEN 'abaixo CAT I' WHEN 2 THEN 'vermelho' WHEN 1 THEN 'IMC' ELSE 'VMC' END"


# --- reportes --------------------------------------------------------------------------------------

def _csv_columns(con, paths: list[str]) -> set[str]:
    rows = con.execute(
        "DESCRIBE SELECT * FROM read_csv(?, all_varchar=true, header=true, comment='#', "
        "null_padding=true, ignore_errors=true, union_by_name=true)", [paths]).fetchall()
    return {r[0] for r in rows}


def _parse_sql(paths: list[str], present: set[str]) -> str:
    cols = ", ".join(f"{c}" if c in present else f"NULL::VARCHAR AS {c}" for c in RAW_COLUMNS)
    layer = (
        "CASE WHEN nullif(trim(skyc{n}), '') IS NULL THEN NULL "
        "WHEN skyl{n}_f IS NULL THEN upper(trim(skyc{n})) "
        "ELSE upper(trim(skyc{n})) || lpad(CAST(round(skyl{n}_f / 100) AS INTEGER)::VARCHAR, 3, '0') END"
    )
    ceil_layer = "CASE WHEN upper(trim(skyc{n})) IN ('BKN', 'OVC', 'VV') THEN skyl{n}_f END"
    return f"""
    WITH raw AS (
        SELECT {cols}
        FROM read_csv($paths, all_varchar=true, header=true, comment='#', null_padding=true,
                      ignore_errors=true, union_by_name=true)
    ),
    typed AS (
        SELECT DISTINCT
            upper(trim(station)) AS icao,
            try_strptime(trim(valid), ['%Y-%m-%d %H:%M', '%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%MZ']) AS valid_ts,
            try_cast(nullif(trim(tmpf), '') AS DOUBLE) AS tmpf,
            try_cast(nullif(trim(dwpf), '') AS DOUBLE) AS dwpf,
            try_cast(nullif(trim(drct), '') AS DOUBLE) AS drct,
            try_cast(nullif(trim(sknt), '') AS DOUBLE) AS sknt,
            try_cast(nullif(trim(alti), '') AS DOUBLE) AS alti,
            try_cast(nullif(trim(vsby), '') AS DOUBLE) AS vsby,
            try_cast(nullif(trim(gust), '') AS DOUBLE) AS gust,
            skyc1, skyc2, skyc3, skyc4,
            try_cast(nullif(trim(skyl1), '') AS DOUBLE) AS skyl1_f,
            try_cast(nullif(trim(skyl2), '') AS DOUBLE) AS skyl2_f,
            try_cast(nullif(trim(skyl3), '') AS DOUBLE) AS skyl3_f,
            try_cast(nullif(trim(skyl4), '') AS DOUBLE) AS skyl4_f,
            coalesce(trim(wxcodes), '') AS wx,
            coalesce(trim(metar), '') AS metar_raw
        FROM raw
        WHERE station IS NOT NULL AND trim(station) <> '' AND lower(trim(station)) <> 'station'
    ),
    derived AS (
        SELECT
            icao,
            strftime(valid_ts, '%Y-%m-%dT%H:%M:%SZ') AS valid_utc,
            CASE WHEN metar_raw LIKE 'SPECI%' OR minute(valid_ts) <> 0 THEN 4 ELSE 3 END::BIGINT AS report_type,
            CASE
                WHEN vsby IS NULL THEN NULL
                WHEN vsby >= 6.2 THEN 10000.0
                WHEN vsby * 1609.344 < 800 THEN round(vsby * 1609.344 / 50.0) * 50.0
                ELSE round(vsby * 1609.344 / 100.0) * 100.0
            END AS vis_m,
            CAST(least({ceil_layer.format(n=1)}, {ceil_layer.format(n=2)},
                       {ceil_layer.format(n=3)}, {ceil_layer.format(n=4)}) AS BIGINT) AS ceiling_ft,
            coalesce(concat_ws(' ', {layer.format(n=1)}, {layer.format(n=2)},
                                    {layer.format(n=3)}, {layer.format(n=4)}), '') AS sky,
            wx,
            CAST(round(drct) AS BIGINT) AS wind_dir,
            sknt AS wind_kt,
            gust AS gust_kt,
            round((tmpf - 32) * 5 / 9, 1) AS temp_c,
            round((dwpf - 32) * 5 / 9, 1) AS dewp_c,
            round(alti * 33.8639, 1) AS pressure_hpa,
            metar_raw,
            regexp_replace(metar_raw, '{METAR_PREFIX_RE}', '') AS metar_body
        FROM typed
        WHERE valid_ts IS NOT NULL
    ),
    flagged AS (
        SELECT
            * EXCLUDE (metar_body),
            coalesce(vis_m < 5000, false) OR coalesce(ceiling_ft < 1500, false) AS imc,
            coalesce(vis_m < 1500, false) OR coalesce(ceiling_ft < 600, false) AS red,
            coalesce(vis_m < 550, false) OR coalesce(ceiling_ft < 200, false) AS below_cat1,
            regexp_matches(wx, '{WX_CONVECTIVE_RE}') OR regexp_matches(metar_body, '{WX_CONVECTIVE_RE}')
                OR regexp_matches(wx, '{WX_HEAVY_RAIN_RE}') OR regexp_matches(metar_body, '{WX_HEAVY_RAIN_RE}')
                OR regexp_matches(metar_body, '{CB_LAYER_RE}') AS convective,
            coalesce(gust_kt >= 25, false) AS gusty
        FROM derived
    ),
    scored AS (
        SELECT *,
            CASE WHEN below_cat1 THEN 3 WHEN red OR convective OR gusty THEN 2 WHEN imc THEN 1 ELSE 0 END::BIGINT
                AS severity
        FROM flagged
    )
    SELECT icao, valid_utc, report_type, vis_m, ceiling_ft, sky, wx, wind_dir, wind_kt, gust_kt,
           temp_c, dewp_c, pressure_hpa, metar_raw, imc, red, below_cat1, convective, gusty, severity,
           {_LABEL_SQL.format(v='severity')} AS severity_label
    FROM scored
    ORDER BY icao, valid_utc, report_type
    """


def parse_asos_many(csv_paths: Sequence[Path | str]) -> pa.Table:
    """Lê um ou mais CSVs do IEM e devolve os reportes classificados (sem duplicatas)."""
    paths = [str(p) for p in csv_paths if Path(p).exists() and Path(p).stat().st_size > 0]
    if not paths:
        return REPORT_SCHEMA.empty_table()
    con = duck()
    present = _csv_columns(con, paths)
    if "station" not in present or "valid" not in present:
        log(f"IEM: CSV sem colunas station/valid ({sorted(present)[:6]}…); devolvendo tabela vazia")
        return REPORT_SCHEMA.empty_table()
    table = con.execute(_parse_sql(paths, present), {"paths": paths}).arrow()
    return table.cast(REPORT_SCHEMA)


def parse_asos(csv_path: Path | str) -> pa.Table:
    """CSV do IEM (format=onlycomma, missing=empty) → Table de reportes com flags (ver REPORT_SCHEMA)."""
    return parse_asos_many([csv_path])


def _floor_hour(dt: datetime) -> datetime:
    return dt.replace(minute=0, second=0, microsecond=0)


def metar_recent(days: int = 8, now: datetime | None = None) -> pa.Table:
    """Todos os reportes das IEM_STATIONS de (agora − days, arredondado à hora) até a próxima hora cheia."""
    now = now or datetime.now(timezone.utc)
    start = _floor_hour(now - timedelta(days=days))
    end = _floor_hour(now) + timedelta(hours=1)
    path = fetch_asos(IEM_STATIONS, start, end, max_age_hours=RECENT_MAX_AGE_HOURS)
    table = parse_asos(path)
    log(f"metar_recent: {table.num_rows} reportes, {len(set(table.column('icao').to_pylist()))} estações "
        f"({start:%Y-%m-%dT%H:%MZ} → {end:%Y-%m-%dT%H:%MZ})")
    return table.append_column("source", pa.array(["iem"] * table.num_rows, pa.string()))


# --- agregações ------------------------------------------------------------------------------------

def hourly_from_reports(reports: pa.Table) -> pa.Table:
    """Reportes → pior condição por icao × hora UTC ('YYYY-MM-DDTHH:00:00Z')."""
    if reports.num_rows == 0:
        return HOURLY_SCHEMA.empty_table()
    con = duck()
    con.register("reports", reports)
    table = con.execute(f"""
        SELECT
            icao,
            substr(valid_utc, 1, 13) || ':00:00Z' AS hour_utc,
            min(vis_m) AS min_vis_m,
            min(ceiling_ft) AS min_ceiling_ft,
            max(severity) AS max_severity,
            {_LABEL_SQL.format(v='max(severity)')} AS severity_label,
            bool_or(convective) AS any_convective,
            bool_or(red) AS any_red,
            bool_or(imc) AS any_imc,
            max(gust_kt) AS max_gust_kt,
            count(*) AS n_reports,
            array_to_string(
                list_sort(list_distinct(list_filter(flatten(list(string_split(wx, ' '))), x -> x <> ''))),
                ' ') AS wx_all
        FROM reports
        GROUP BY icao, hour_utc
        ORDER BY icao, hour_utc
    """).arrow()
    return table.cast(HOURLY_SCHEMA)


def daily_from_hourly(hourly: pa.Table) -> pa.Table:
    """Horas UTC → dia LOCAL do aeroporto (fuso de voos.tz.airport_tz) com horas em IMC/vermelho/convecção."""
    if hourly.num_rows == 0:
        return DAILY_SCHEMA.empty_table()
    icaos = sorted(set(hourly.column("icao").to_pylist()))
    tzmap = pa.table({"icao": icaos, "tz": [airport_tz(i).key for i in icaos]})
    con = duck()
    con.register("hourly", hourly)
    con.register("tzmap", tzmap)
    table = con.execute("""
        WITH h AS (
            SELECT hourly.*,
                   strftime(timezone(tzmap.tz, strptime(hour_utc, '%Y-%m-%dT%H:%M:%SZ')::TIMESTAMPTZ),
                            '%Y-%m-%d') AS date_local
            FROM hourly JOIN tzmap USING (icao)
        )
        SELECT
            icao,
            date_local,
            count(*) FILTER (WHERE any_imc) AS hours_imc,
            count(*) FILTER (WHERE any_red) AS hours_red,
            count(*) FILTER (WHERE any_convective) AS hours_convective,
            min(min_vis_m) AS min_vis_m,
            min(min_ceiling_ft) AS min_ceiling_ft,
            max(max_gust_kt) AS max_gust_kt,
            max(max_severity) AS max_severity,
            count(*) AS n_hours
        FROM h
        GROUP BY icao, date_local
        ORDER BY icao, date_local
    """).arrow()
    return table.cast(DAILY_SCHEMA)


def _fetch_months(start_date: date, end_date: date, now: datetime | None = None) -> list[Path]:
    """Um pedido ao IEM por mês-calendário para todas as IEM_STATIONS (cache: meses fechados são imutáveis)."""
    now = now or datetime.now(timezone.utc)
    windows = month_windows(start_date, end_date)
    paths: list[Path] = []
    for i, (sts, ets) in enumerate(windows, 1):
        closed = ets + CLOSED_GRACE <= now
        log(f"IEM mês {sts:%Y-%m} ({i}/{len(windows)}){'' if closed else ' [mês corrente]'}")
        paths.append(fetch_asos(IEM_STATIONS, sts, ets, max_age_hours=None if closed else RECENT_MAX_AGE_HOURS))
    return paths


def metar_hourly(start_date: date, end_date: date | None = None) -> pa.Table:
    """Pior condição por icao × hora UTC entre start_date e end_date (inclusive; padrão: hoje UTC)."""
    end_date = end_date or datetime.now(timezone.utc).date()
    paths = _fetch_months(start_date, end_date)
    reports = parse_asos_many(paths)
    hourly = hourly_from_reports(reports)
    log(f"metar_hourly: {reports.num_rows} reportes → {hourly.num_rows} horas-estação "
        f"({start_date:%Y-%m-%d} → {end_date:%Y-%m-%d})")
    return hourly


def weather_daily(start_date: date, end_date: date | None = None) -> pa.Table:
    """Horas em IMC/vermelho/convecção por icao × dia local, derivado de metar_hourly (mesmo cache)."""
    daily = daily_from_hourly(metar_hourly(start_date, end_date))
    log(f"weather_daily: {daily.num_rows} dias-estação")
    return daily
