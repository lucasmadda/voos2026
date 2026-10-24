"""Testes das funções puras de meteorologia: flags do METAR, janelas mensais e agregações."""
from datetime import date, datetime, timezone

import pyarrow as pa
import pytest

from voos.marts.weather import (
    DAILY_SCHEMA, HOURLY_SCHEMA, REPORT_SCHEMA, daily_from_hourly, hourly_from_reports, parse_asos,
)
from voos.sources.iem import build_url, cache_path, looks_like_asos_csv, month_windows
from voos.tz import local_day

HEADER = ("station,valid,tmpf,dwpf,relh,drct,sknt,p01i,alti,mslp,vsby,gust,skyc1,skyc2,skyc3,skyc4,"
          "skyl1,skyl2,skyl3,skyl4,wxcodes,ice_accretion_1hr,ice_accretion_3hr,ice_accretion_6hr,"
          "peak_wind_gust,peak_wind_drct,peak_wind_time,feel,metar,snowdepth")


def row(station: str, valid: str, vsby: str, gust: str, skyc: tuple, skyl: tuple, wx: str, metar: str,
        tmpf: str = "69.80", alti: str = "29.80", drct: str = "190.00", sknt: str = "6.00") -> str:
    skyc = tuple(skyc) + ("",) * (4 - len(skyc))
    skyl = tuple(skyl) + ("",) * (4 - len(skyl))
    return ",".join([station, valid, tmpf, "66.20", "88.36", drct, sknt, "0.00", alti, "", vsby, gust,
                     *skyc, *skyl, wx, "", "", "", "", "", "", tmpf, metar, ""])


CSV = "\n".join([
    "#DEBUG: linha de comentário que o IEM às vezes emite",
    HEADER,
    # vis 2000 m + BKN009 → IMC mas não vermelho
    row("SBPA", "2026-10-24 18:00", "1.24", "", ("BKN", "BKN", "FEW"), ("900.00", "3000.00", "4000.00"), "RA BR",
        "SBPA 241800Z 19006KT 2000 RA BR BKN009 BKN030 FEW040TCU 19/17 Q1007 RERA"),
    # vis 1200 m → vermelho
    row("SBPA", "2026-10-24 19:00", "0.75", "", ("BKN",), ("3000.00",), "RA BR",
        "SBPA 241900Z 19006KT 1200 RA BR BKN030 19/17 Q1007"),
    # SPECI (minuto ≠ 00) com TS → convectivo
    row("SBPA", "2026-10-24 19:20", "6.21", "", ("SCT", "FEW"), ("2500.00", "4000.00"), "TS",
        "SBPA 241920Z 19006KT 9999 TS SCT025 FEW040CB 19/17 Q1007"),
    # TCU sozinho não é convectivo; vsby 6.21 → 10000 m; 'RERA' e o indicador SBGR não disparam nada
    row("SBGR", "2026-10-24 18:00", "6.21", "", ("FEW",), ("4000.00",), "",
        "SBGR 241800Z 10008KT 9999 FEW040TCU 25/15 Q1015 RERA"),
    # rajada 30 kt → gusty, severidade 2
    row("SBSV", "2026-10-24 18:00", "6.21", "30.00", (), (), "",
        "SBSV 241800Z 07018G30KT CAVOK 28/22 Q1011"),
    # abaixo de CAT I por visibilidade 400 m (0.25 mi)
    row("SBFL", "2026-10-24 18:00", "0.25", "", ("OVC",), ("200.00",), "FG",
        "SBFL 241800Z 00000KT 0400 FG OVC002 15/15 Q1020"),
    # teto 100 ft por VV001 → abaixo de CAT I
    row("SBFL", "2026-10-24 19:00", "0.50", "", ("VV",), ("100.00",), "FG",
        "SBFL 241900Z 00000KT 0800 FG VV001 15/15 Q1020"),
    # visibilidade e teto vazios → não limitante, severidade 0, nulos preservados
    row("SBFN", "2026-10-24 01:00", "", "", (), (), "",
        "SBFN 240100Z 10010KT CAVOK 26/22 Q1012"),
    # chuva forte → convectivo; '+RA' em código IEM
    row("SBFN", "2026-10-24 02:00", "2.49", "", ("BKN",), ("1500.00",), "+RA",
        "SBFN 240200Z 10010KT 4000 +RA BKN015 24/22 Q1012"),
    # VCTS → convectivo mesmo sem TS isolado; CB na camada também
    row("SBRF", "2026-10-24 18:00", "6.21", "", ("FEW",), ("2000.00",), "VCTS",
        "SBRF 241800Z 10010KT 9999 VCTS FEW020CB 29/24 Q1011"),
    # linha duplicada deve ser removida
    row("SBSV", "2026-10-24 18:00", "6.21", "30.00", (), (), "",
        "SBSV 241800Z 07018G30KT CAVOK 28/22 Q1011"),
]) + "\n"


@pytest.fixture(scope="module")
def reports(tmp_path_factory) -> dict:
    p = tmp_path_factory.mktemp("iem") / "asos.csv"
    p.write_text(CSV)
    assert looks_like_asos_csv(p)
    table = parse_asos(p)
    assert table.schema.equals(REPORT_SCHEMA)
    return {(r["icao"], r["valid_utc"]): r for r in table.to_pylist()}


def test_dedup_and_shape(reports):
    assert len(reports) == 10  # 11 linhas de dados, 1 duplicada


def test_imc_not_red(reports):
    r = reports[("SBPA", "2026-10-24T18:00:00Z")]
    assert r["vis_m"] == 2000 and r["ceiling_ft"] == 900
    assert r["imc"] is True and r["red"] is False and r["below_cat1"] is False
    assert r["convective"] is False  # 'RERA' e 'TCU' não contam
    assert r["severity"] == 1 and r["severity_label"] == "IMC"
    assert r["report_type"] == 3
    assert r["sky"] == "BKN009 BKN030 FEW040"
    assert r["wx"] == "RA BR"
    assert r["temp_c"] == 21.0 and r["pressure_hpa"] == 1009.1
    assert r["wind_dir"] == 190 and r["wind_kt"] == 6.0 and r["gust_kt"] is None


def test_red(reports):
    r = reports[("SBPA", "2026-10-24T19:00:00Z")]
    assert r["vis_m"] == 1200 and r["ceiling_ft"] == 3000
    assert r["red"] is True and r["below_cat1"] is False
    assert r["severity"] == 2 and r["severity_label"] == "vermelho"


def test_speci_thunderstorm(reports):
    r = reports[("SBPA", "2026-10-24T19:20:00Z")]
    assert r["report_type"] == 4
    assert r["convective"] is True and r["imc"] is False
    assert r["severity"] == 2
    assert r["ceiling_ft"] is None  # SCT/FEW não formam teto


def test_tcu_alone_not_convective_and_vis_cap(reports):
    r = reports[("SBGR", "2026-10-24T18:00:00Z")]
    assert r["vis_m"] == 10000
    assert r["convective"] is False and r["severity"] == 0 and r["severity_label"] == "VMC"


def test_gusty(reports):
    r = reports[("SBSV", "2026-10-24T18:00:00Z")]
    assert r["gust_kt"] == 30 and r["gusty"] is True and r["severity"] == 2
    assert r["sky"] == "" and r["ceiling_ft"] is None and r["vis_m"] == 10000


def test_below_cat1(reports):
    by_vis = reports[("SBFL", "2026-10-24T18:00:00Z")]
    assert by_vis["vis_m"] == 400 and by_vis["ceiling_ft"] == 200
    assert by_vis["below_cat1"] is True and by_vis["severity"] == 3 and by_vis["severity_label"] == "abaixo CAT I"
    by_vv = reports[("SBFL", "2026-10-24T19:00:00Z")]
    assert by_vv["vis_m"] == 800 and by_vv["ceiling_ft"] == 100 and by_vv["sky"] == "VV001"
    assert by_vv["below_cat1"] is True and by_vv["severity"] == 3


def test_missing_vis_and_ceiling_not_limiting(reports):
    r = reports[("SBFN", "2026-10-24T01:00:00Z")]
    assert r["vis_m"] is None and r["ceiling_ft"] is None
    assert r["imc"] is False and r["red"] is False and r["severity"] == 0


def test_heavy_rain_and_vcts_and_cb(reports):
    assert reports[("SBFN", "2026-10-24T02:00:00Z")]["convective"] is True
    r = reports[("SBRF", "2026-10-24T18:00:00Z")]
    assert r["convective"] is True and r["severity"] == 2


def test_hourly_aggregation(reports):
    table = pa.Table.from_pylist(list(reports.values()), schema=REPORT_SCHEMA)
    hourly = hourly_from_reports(table)
    assert hourly.schema.equals(HOURLY_SCHEMA)
    rows = {(r["icao"], r["hour_utc"]): r for r in hourly.to_pylist()}
    h19 = rows[("SBPA", "2026-10-24T19:00:00Z")]  # METAR 19:00 (vermelho) + SPECI 19:20 (TS)
    assert h19["n_reports"] == 2
    assert h19["min_vis_m"] == 1200 and h19["min_ceiling_ft"] == 3000
    assert h19["max_severity"] == 2 and h19["severity_label"] == "vermelho"
    assert h19["any_convective"] is True and h19["any_red"] is True and h19["any_imc"] is True
    assert h19["wx_all"] == "BR RA TS"
    assert rows[("SBSV", "2026-10-24T18:00:00Z")]["max_gust_kt"] == 30
    assert rows[("SBFN", "2026-10-24T01:00:00Z")]["wx_all"] == ""


def test_daily_local_date(reports):
    table = pa.Table.from_pylist(list(reports.values()), schema=REPORT_SCHEMA)
    daily = daily_from_hourly(hourly_from_reports(table))
    assert daily.schema.equals(DAILY_SCHEMA)
    rows = {(r["icao"], r["date_local"]): r for r in daily.to_pylist()}
    # SBFN (Noronha, UTC−2): 01:00Z de 24/10 ainda é 23/10 local; 02:00Z já é 00:00 de 24/10
    assert local_day(datetime(2026, 10, 24, 1, 0, tzinfo=timezone.utc), "SBFN") == date(2026, 10, 23)
    assert local_day(datetime(2026, 10, 24, 2, 0, tzinfo=timezone.utc), "SBFN") == date(2026, 10, 24)
    fn23, fn24 = rows[("SBFN", "2026-10-23")], rows[("SBFN", "2026-10-24")]
    assert fn23["n_hours"] == 1 and fn23["hours_convective"] == 0 and fn23["hours_imc"] == 0 and fn23["max_severity"] == 0
    assert fn24["n_hours"] == 1 and fn24["hours_convective"] == 1 and fn24["hours_imc"] == 1 and fn24["min_vis_m"] == 4000
    # em São Paulo (UTC−3) 02:00Z de 24/10 ainda seria 23/10
    assert local_day(datetime(2026, 10, 24, 2, 0, tzinfo=timezone.utc), "SBPA") == date(2026, 10, 23)
    poa = rows[("SBPA", "2026-10-24")]
    assert poa["n_hours"] == 2 and poa["hours_imc"] == 2 and poa["hours_red"] == 1 and poa["hours_convective"] == 1
    assert poa["min_vis_m"] == 1200 and poa["min_ceiling_ft"] == 900 and poa["max_severity"] == 2
    fl = rows[("SBFL", "2026-10-24")]
    assert fl["max_severity"] == 3 and fl["min_ceiling_ft"] == 100 and fl["min_vis_m"] == 400


def test_empty_and_header_only(tmp_path):
    header_only = tmp_path / "h.csv"
    header_only.write_text(HEADER + "\n")
    t = parse_asos(header_only)
    assert t.num_rows == 0 and t.schema.equals(REPORT_SCHEMA)
    assert hourly_from_reports(t).num_rows == 0
    assert daily_from_hourly(hourly_from_reports(t)).num_rows == 0
    missing = tmp_path / "nope.csv"
    assert parse_asos(missing).num_rows == 0
    html = tmp_path / "err.html"
    html.write_text("<html><body>Request Rejected</body></html>")
    assert not looks_like_asos_csv(html)


def test_month_windows():
    utc = timezone.utc
    w = month_windows(date(2024, 1, 1), date(2024, 3, 15))
    assert w == [
        (datetime(2024, 1, 1, tzinfo=utc), datetime(2024, 2, 1, tzinfo=utc)),
        (datetime(2024, 2, 1, tzinfo=utc), datetime(2024, 3, 1, tzinfo=utc)),
        (datetime(2024, 3, 1, tzinfo=utc), datetime(2024, 3, 16, tzinfo=utc)),
    ]
    w = month_windows(date(2025, 12, 20), date(2026, 1, 3))
    assert w == [
        (datetime(2025, 12, 20, tzinfo=utc), datetime(2026, 1, 1, tzinfo=utc)),
        (datetime(2026, 1, 1, tzinfo=utc), datetime(2026, 1, 4, tzinfo=utc)),
    ]
    assert month_windows(date(2026, 10, 24), date(2026, 10, 24)) == [
        (datetime(2026, 10, 24, tzinfo=utc), datetime(2026, 10, 25, tzinfo=utc)),
    ]
    assert month_windows(date(2026, 10, 24), date(2026, 10, 23)) == []
    assert len(month_windows(date(2024, 1, 1), date(2026, 10, 24))) == 34


def test_url_and_cache_path():
    sts, ets = datetime(2026, 10, 1, tzinfo=timezone.utc), datetime(2026, 11, 1, tzinfo=timezone.utc)
    url = build_url(["SBPA", "SBSV"], sts, ets)
    assert url.startswith("https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py?station=SBPA%2CSBSV&")
    assert "sts=2026-10-01T00%3A00Z&ets=2026-11-01T00%3A00Z" in url
    assert "report_type=3%2C4" in url and "tz=Etc%2FUTC" in url and "format=onlycomma" in url
    p = cache_path(["SBPA", "SBSV"], sts, ets)
    assert p.name.startswith("asos_20261001T0000_20261101T0000_2stations_") and p.name.endswith(".csv")
    assert len(p.stem.rsplit("_", 1)[1]) == 8
    assert p.parent.name == "iem" and p.parent.parent.name == "raw"
