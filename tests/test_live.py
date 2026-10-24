"""Testes das funções puras de voos.marts.live (Fraport, SIROS, INMET)."""
from __future__ import annotations

from voos.marts import live


def dep(flight: str, ost: str, status: str, est: str = "", dest: dict | None = None, **extra) -> dict:
    return {
        "airline": {"text": "Gol Transportes Aereos"},
        "destination": dest if dest is not None else {"iata": "SSA", "name": "BA - Salvador"},
        "origin": [],
        "estimated_time": est,
        "scheduled_time": ost[11:16],
        "original_scheduled_time": ost,
        "flight": flight,
        "gate": "4",
        "id": 210420668,
        "status": {"text": status},
        **extra,
    }


def arr(flight: str, ost: str, status: str, est: str = "", origin: dict | None = None) -> dict:
    f = dep(flight, ost, status, est)
    f["destination"], f["origin"] = [], (origin if origin is not None else {"iata": "VCP", "name": "SP - Campinas"})
    return f


FETCHED = "2026-10-24T23:19:34Z"


# --------------------------------------------------------------------------- normalize_flight
def test_cancelled_departure_g31979():
    row = live.normalize_flight("POA", "dep", dep("G31979", "2026-10-24 10:30:00", "Cancelado", est="10:30"), FETCHED)
    assert row["sched_local"] == "2026-10-24T10:30:00"
    assert row["sched_utc"] == "2026-10-24T13:30:00Z"
    assert row["sched_date_local"] == "2026-10-24" and row["sched_hour_local"] == 10
    assert row["carrier_iata"] == "G3" and row["flight_number"] == "1979"
    assert row["carrier_icao"] == "GLO" and row["carrier_group"] == "GOL"
    assert row["flight_key"] == "GLO-1979-SBPA-20261024T1330Z"
    assert row["delay_min"] is None  # cancelado: atraso não se aplica
    assert row["status_canon"] == "cancelled" and row["is_disruption"] is True
    assert row["event_class"] == "OperationalCancellation" and row["status_kind"] == "provisório"
    assert row["other_uf"] == "BA" and row["other_city"] == "Salvador" and row["other_iata"] == "SSA"
    assert row["other_icao"] == "SBSV"
    assert row["event_key"] == "POA|dep|G31979|2026-10-24T10:30:00"
    assert row["airport_icao"] == "SBPA" and row["direction"] == "dep" and row["source"] == "fraport"
    assert row["fraport_id"] == 210420668 and row["fetched_at"] == FETCHED
    assert set(row) == set(live.FLIGHT_SCHEMA.names)


def test_delayed_arrival_after_midnight():
    row = live.normalize_flight("POA", "arr", arr("AD2680", "2026-10-25 00:15:00", "Atrasado", est="01:15"), FETCHED)
    assert row["est_local"] == "2026-10-25T01:15:00" and row["est_utc"] == "2026-10-25T04:15:00Z"
    assert row["delay_min"] == 60 and row["status_canon"] == "delayed" and row["is_disruption"]
    assert row["carrier_icao"] == "AZU" and row["carrier_group"] == "Azul"
    # chegada: origem da chave é o outro aeroporto (VCP → SBKP)
    assert row["other_icao"] == "SBKP" and row["flight_key"] == "AZU-2680-SBKP-20261025T0315Z"
    assert row["other_uf"] == "SP" and row["other_city"] == "Campinas"


def test_estimated_rolls_over_midnight():
    row = live.normalize_flight("FOR", "dep", dep("G31234", "2026-10-24 23:50:00", "Previsto", est="00:20"), FETCHED)
    assert row["est_local"] == "2026-10-25T00:20:00" and row["delay_min"] == 30
    assert row["airport_icao"] == "SBFZ" and row["sched_utc"] == "2026-10-25T02:50:00Z"


def test_international_and_unknown_carrier():
    f = dep("TP118", "2026-10-24 21:00:00", "Previsto", dest={"iata": "LIS", "name": "Lisboa"})
    row = live.normalize_flight("POA", "departures", f, FETCHED)
    assert row["other_uf"] is None and row["other_city"] == "Lisboa" and row["other_icao"] == "LPPT"
    assert row["carrier_iata"] == "TP" and row["carrier_icao"] is None and row["carrier_group"] == "outras"
    assert row["flight_key"] is None  # companhia fora de carriers.csv
    assert row["delay_min"] is None and row["est_local"] is None


def test_arrival_with_unknown_origin_has_no_flight_key():
    f = arr("G31244", "2026-10-24 16:45:00", "Alternado", origin={"iata": "XXX", "name": "SP - Lugar"})
    row = live.normalize_flight("POA", "arr", f, FETCHED)
    assert row["other_icao"] is None and row["flight_key"] is None
    assert row["status_canon"] == "diverted" and row["is_disruption"]


def test_missing_original_time_falls_back_to_date_key():
    f = dep("AD4151", "2026-10-24 07:00:00", "Decolagem", est="07:05")
    f.pop("original_scheduled_time")
    row = live.normalize_flight("POA", "dep", f, FETCHED, date_key="2026-10-24")
    assert row["sched_local"] == "2026-10-24T07:00:00" and row["delay_min"] == 5


def test_split_place():
    assert live.split_place("BA - Salvador") == ("BA", "Salvador")
    assert live.split_place("Lisboa") == (None, "Lisboa")
    assert live.split_place("BH - Confins") == (None, "Confins")  # prefixo que não é UF
    assert live.split_place("") == (None, None) and live.split_place(None) == (None, None)


def test_iter_flights_both_shapes():
    f1, f2 = dep("G31", "2026-10-24 10:00:00", "Previsto"), dep("G32", "2026-10-25 11:00:00", "Previsto")
    assert list(live.iter_flights({"2026-10-24": [f1], "2026-10-25": [f2]})) == [("2026-10-24", f1), ("2026-10-25", f2)]
    assert list(live.iter_flights([f1, f2])) == [("2026-10-24", f1), ("2026-10-25", f2)]
    assert list(live.iter_flights(None)) == [] and list(live.iter_flights({})) == []


def test_stamp_and_parse():
    assert live.stamp_from_name("20261024T231934Z.json.gz") == "2026-10-24T23:19:34Z"
    assert live.fmt_utc(live.parse_utc("2026-10-24T23:19:34+00:00")) == "2026-10-24T23:19:34Z"


# --------------------------------------------------------------------------- snapshot walks
def _stream():
    g = dep("G31979", "2026-10-24 22:00:00", "Previsto", est="22:00")
    a = dep("AD1111", "2026-10-24 21:00:00", "Previsto", est="21:00")  # 00:00Z do dia 25
    old = dep("LA3000", "2026-10-24 10:00:00", "Decolagem", est="10:05")  # já passou: sai da janela
    snap1 = ("2026-10-24T20:00:00Z", {"departures": {"2026-10-24": [g, a, old]}, "arrivals": {}})
    g2 = dict(g, status={"text": "Atrasado"}, estimated_time="23:00", id=999)
    snap2 = ("2026-10-24T20:15:00Z", {"departures": [g2], "arrivals": []})
    return [snap1, snap2]


def test_events_from_stream():
    ev = live._events_from_stream("POA", _stream())
    by_field = {}
    for e in ev:
        by_field.setdefault(e["field"], []).append(e)
    assert len(by_field["first_seen"]) == 3
    assert all(e["changed_at"] == "2026-10-24T20:00:00Z" and e["from_value"] is None for e in by_field["first_seen"])
    (st,) = by_field["status"]
    assert (st["flight_code_raw"], st["from_value"], st["to_value"], st["status_canon_to"]) == ("G31979", "Previsto", "Atrasado", "delayed")
    assert st["changed_at"] == "2026-10-24T20:15:00Z" and st["carrier_group"] == "GOL" and st["other_uf"] == "BA"
    (es,) = by_field["estimated"]
    assert (es["from_value"], es["to_value"], es["status_canon_to"]) == ("2026-10-24T22:00:00", "2026-10-24T23:00:00", None)
    (dis,) = by_field["disappeared"]  # AD1111 sumiu com a partida ainda a 3h45 no futuro; LA3000 só rolou
    assert dis["flight_code_raw"] == "AD1111" and dis["from_value"] == "Previsto" and dis["to_value"] is None
    assert len(ev) == 6 and set(ev[0]) == set(live.EVENTS_SCHEMA.names)


def test_latest_from_stream():
    rows = live._latest_from_stream("POA", _stream())
    assert len(rows) == 1
    r = rows[0]
    assert r["flight_code_raw"] == "G31979" and r["status_raw"] == "Atrasado" and r["delay_min"] == 60
    assert r["first_seen_at"] == "2026-10-24T20:00:00Z" and r["n_snapshots"] == 2
    assert r["prev_status_raw"] == "Previsto" and r["status_changed_at"] == "2026-10-24T20:15:00Z"
    assert r["fetched_at"] == "2026-10-24T20:15:00Z" and set(r) == set(live.LATEST_SCHEMA.names)


def test_latest_without_change_has_no_prev_status():
    snap = ("2026-10-24T20:00:00Z", {"departures": [dep("G31979", "2026-10-24 22:00:00", "Previsto")], "arrivals": []})
    (r,) = live._latest_from_stream("POA", [snap, ("2026-10-24T20:15:00Z", snap[1])])
    assert r["n_snapshots"] == 2 and r["prev_status_raw"] is None and r["status_changed_at"] is None
    assert live._latest_from_stream("POA", []) == []


# --------------------------------------------------------------------------- SIROS
SIROS_REC = {
    "Cód. Empresa": "GLO", "Empresa": "GOL LINHAS AÉREAS S.A.", "Nr. Voo": "1979", "Equip.": "B738",
    "Seg": "0", "Ter": "0", "Qua": "0", "Qui": "0", "Sex": "0", "Sáb": "6", "Dom": "0",
    "Qtde Assentos": "186", "Nº SIROS": "GLO-0000000000049554468", "Data Registro": "22/10/2026 15:11:01",
    "Início Operação": "2026-10-24", "Fim Operação": "2026-10-24", "Natureza Operação": "DOMÉSTICA",
    "Tipo Serviço": "REGULAR DE PASSAGEIROS", "Objeto Transporte": "PASSAGEIROS", "Nr. Etapa": "1",
    "Cód Origem": "SBPA", "Arpt Origem": "SALGADO FILHO - PORTO ALEGRE - RS - BRASIL",
    "Cód Destino": "SBSV", "Arpt Destino": "DEPUTADO LUÍS EDUARDO MAGALHÃES - SALVADOR - BA - BRASIL",
    "Partida Prevista": "13:30", "Chegada Prevista": "16:45", "Codeshare": "TAP/5865 início: 24/10/2026 fim: 24/10/2026",
}


def test_siros_leg_glo_1979():
    r = live.siros_leg(SIROS_REC, "2026-10-24")  # sábado → coluna 'Sáb' = '6'
    assert r["flight_key"] == "GLO-1979-SBPA-20261024T1330Z"
    assert r["sched_dep_utc"] == "2026-10-24T13:30:00Z" and r["sched_arr_utc"] == "2026-10-24T16:45:00Z"
    assert r["data_registro_utc"] == "2026-10-22T18:11:01Z"  # Brasília → UTC
    assert r["operates_today"] is True and r["is_focus_leg"] is True
    assert r["seats"] == 186 and r["leg_number"] == 1 and r["carrier_group"] == "GOL"
    assert r["number_prefix"] is None and r["flight_number"] == "1979"
    assert set(r) == set(live.SIROS_SCHEMA.names)


def test_siros_leg_rollover_prefix_and_weekday():
    rec = dict(SIROS_REC, **{"Nr. Voo": "Z0845", "Partida Prevista": "23:30", "Chegada Prevista": "02:10",
                             "Cód Origem": "SBGR", "Cód Destino": "SBFZ", "Sáb": "0", "Dom": "7"})
    r = live.siros_leg(rec, "2026-10-24")
    assert r["flight_number"] == "845" and r["number_prefix"] == "Z"
    assert r["sched_arr_utc"] == "2026-10-25T02:10:00Z" and r["flight_key"] == "GLO-0845-SBGR-20261024T2330Z"
    assert r["operates_today"] is False  # sábado sem operação
    assert live.siros_leg(rec, "2026-10-25")["operates_today"] is True  # domingo
    assert r["is_focus_leg"] is True  # hub → Nordeste
    assert live.is_focus_leg("SBGR", "SBGL") is False and live.is_focus_leg("SBSV", "SBKP") is True


# --------------------------------------------------------------------------- INMET
def test_inmet_alert():
    a = {"id": 56153, "id_aviso": 28544, "descricao": "Tempestade", "severidade": "Perigo Potencial",
         "aviso_cor": "#FFFE00", "inicio": "2026-10-24 00:01", "fim": "2026-10-24 23:59",
         "estados": "Minas Gerais,Paraná,São Paulo,Espírito Santo", "regioes": "Sudeste,Sul",
         "geocodes": "3100104,3100203,4100103", "municipios": "longo…", "poligono": "{…}", "icone": "data:…",
         "riscos": ["Chuva…"], "instrucoes": ["Em caso…"], "alterado": False, "encerrado": False}
    r = live.inmet_alert(a, "hoje")
    assert r["ufs"] == ["MG", "PR", "SP", "ES"] and r["n_municipios"] == 3 and r["geocodes"] == ["3100104", "3100203", "4100103"]
    assert r["cor"] == "#FFFE00" and r["grupo"] == "hoje" and r["inicio_utc"] == "2026-10-24T03:01:00Z"
    assert "poligono" not in r and "municipios" not in r and "icone" not in r
