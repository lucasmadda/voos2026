"""Marts "live": leituras dos snapshots que `voos.capture` arquiva em data/archive/.

- Fraport (painel de voos POA/FOR): `fraport_latest()` — estado atual de cada voo da janela do
  painel, enriquecido com o histórico resumido dos snapshots anteriores; `fraport_events()` —
  mudanças observadas entre snapshots (primeira observação, status, horário estimado, sumiço).
- SIROS diário: `siros_today()` — malha planejada do dia (horários em UTC).
- INMET avisos ativos: `inmet_alerts()`.
- `asof()`: carimbos de atualidade de tudo acima, para o rodapé do site.

Convenções do projeto: todo datetime sai como STRING — UTC 'YYYY-MM-DDTHH:MM:SSZ' (sufixo _utc),
local ingênuo 'YYYY-MM-DDTHH:MM:SS' (sufixo _local), datas 'YYYY-MM-DD'. Nunca tipos timestamp do
Arrow. Qualquer número de snapshots é aceito (o launchd grava um a cada 15 min); arquivos parciais
ou corrompidos são ignorados com aviso no stderr. Os snapshots são lidos um a um (streaming), então
a memória não cresce com o tamanho do arquivo.
"""
from __future__ import annotations

import csv
import gzip
import json
import re
import unicodedata
from collections.abc import Callable, Iterable, Iterator
from datetime import date, datetime, timedelta
from functools import lru_cache
from pathlib import Path

import pyarrow as pa

from .. import keys, tz, vocab
from ..config import ARCHIVE, FOCUS_ORIGIN, FRAPORT_ICAO, HUB_AIRPORTS, NE_AIRPORTS, OURAIRPORTS_CSV, RAW, REF
from ..http import cached_download, log
from ..io import rel

SOURCE = "fraport"
# (chave na payload, direção canônica, chave do "outro" aeroporto)
SECTIONS = (("departures", "dep", "destination"), ("arrivals", "arr", "origin"))
DIRECTION_ALIASES = {"dep": "dep", "departures": "dep", "arr": "arr", "arrivals": "arr"}
# Um voo que some do painel com a partida prevista a ≥ 2 h no futuro "desapareceu";
# antes disso (ou no passado) ele apenas saiu da janela rolante.
DISAPPEAR_HORIZON = timedelta(hours=2)

_OST_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2})(?::\d{2})?$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_HHMM_RE = re.compile(r"^\d{1,2}:\d{2}$")
_PLACE_RE = re.compile(r"^([A-Z]{2})\s*-\s*(.+)$")
_STAMP_RE = re.compile(r"^(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})Z")

_Snapshot = tuple[str, dict]  # (fetched_at ISO UTC, payload)


# --------------------------------------------------------------------------- formatação de tempo
def fmt_utc(dt: datetime) -> str:
    """datetime (aware ou ingênuo = UTC) → 'YYYY-MM-DDTHH:MM:SSZ'."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=tz.UTC)
    return dt.astimezone(tz.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def fmt_local(dt: datetime) -> str:
    """datetime local ingênuo → 'YYYY-MM-DDTHH:MM:SS'."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S")


def parse_utc(s: str) -> datetime:
    """ISO 8601 ('…Z' ou '…+00:00'; sem fuso = UTC) → datetime aware em UTC."""
    dt = datetime.fromisoformat(s.strip().replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=tz.UTC)
    return dt.astimezone(tz.UTC)


def stamp_from_name(name: str) -> str | None:
    """'20261024T231934Z.json.gz' → '2026-10-24T23:19:34Z' (carimbo dos arquivos do capture)."""
    m = _STAMP_RE.match(name)
    if not m:
        return None
    y, mo, d, h, mi, s = m.groups()
    return f"{y}-{mo}-{d}T{h}:{mi}:{s}Z"


def _fold(s: str) -> str:
    """Normaliza para comparação: sem acentos, casefold, espaços colapsados."""
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return " ".join(s.casefold().split())


def _text(v) -> str | None:
    """Extrai texto de {'text': …} ou str; vazio → None."""
    if isinstance(v, dict):
        v = v.get("text")
    if v is None:
        return None
    s = str(v).strip()
    return s or None


# --------------------------------------------------------------------------- referências
@lru_cache(maxsize=1)
def uf_siglas() -> frozenset[str]:
    with open(REF / "ufs.csv", newline="", encoding="utf-8") as f:
        return frozenset(r["uf"].strip().upper() for r in csv.DictReader(f))


@lru_cache(maxsize=1)
def uf_by_name() -> dict[str, str]:
    """Nome normalizado (_fold) → sigla, a partir de data/ref/ufs.csv."""
    with open(REF / "ufs.csv", newline="", encoding="utf-8") as f:
        return {_fold(r["uf_nome"]): r["uf"].strip().upper() for r in csv.DictReader(f)}


@lru_cache(maxsize=1)
def iata_to_icao() -> dict[str, str]:
    """IATA → ICAO via OurAirports (cache compartilhado em data/raw/ourairports/airports.csv).

    Prefere linhas com scheduled_service='yes' quando um IATA se repete; quando `icao_code` está
    vazio usa `ident` se for um código de 4 letras. Complementa com data/ref/airports_override.csv
    (field == 'iata'). Sem rede e sem cópia local devolve {} (other_icao fica nulo) em vez de falhar.
    """
    dest = RAW / "ourairports" / "airports.csv"
    try:
        path = cached_download(OURAIRPORTS_CSV, dest, max_age_hours=168)
    except Exception as e:  # noqa: BLE001
        if not dest.exists():
            log(f"live: OurAirports indisponível ({e!r}); other_icao ficará nulo")
            return {}
        log(f"live: OurAirports não atualizado ({e!r}); usando cópia local")
        path = dest
    out: dict[str, str] = {}
    sched: dict[str, bool] = {}
    with open(path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            iata = (r.get("iata_code") or "").strip().upper()
            if not iata:
                continue
            icao = (r.get("icao_code") or "").strip().upper()
            if not re.fullmatch(r"[A-Z0-9]{4}", icao):
                ident = (r.get("ident") or "").strip().upper()
                icao = ident if re.fullmatch(r"[A-Z]{4}", ident) else ""
            if not icao:
                continue
            is_sched = (r.get("scheduled_service") or "").strip().lower() == "yes"
            if iata not in out or (is_sched and not sched[iata]):
                out[iata] = icao
                sched[iata] = is_sched
    override = REF / "airports_override.csv"
    if override.exists():
        with open(override, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                if (r.get("field") or "").strip() == "iata" and r.get("value") and r.get("icao"):
                    out.setdefault(r["value"].strip().upper(), r["icao"].strip().upper())
    return out


def split_place(name: str | None) -> tuple[str | None, str | None]:
    """'BA - Salvador' → ('BA', 'Salvador'); 'Lisboa' → (None, 'Lisboa'); '' → (None, None).

    O prefixo só vira `other_uf` quando é uma UF de data/ref/ufs.csv ('BH - Confins' → (None, 'Confins')).
    """
    s = (name or "").strip()
    if not s:
        return None, None
    m = _PLACE_RE.match(s)
    if not m:
        return None, s
    prefix, city = m.group(1), m.group(2).strip()
    return (prefix if prefix in uf_siglas() else None), (city or None)


# --------------------------------------------------------------------------- snapshots Fraport
def list_snapshots(site: str) -> list[Path]:
    """Snapshots de um site em ordem cronológica (o nome é 'YYYYMMDDTHHMMSSZ.json.gz')."""
    d = ARCHIVE / "fraport" / site.upper()
    return sorted(d.glob("*/*.json.gz"), key=lambda p: p.name)


def load_snapshot(path: Path) -> _Snapshot:
    """Lê um snapshot → (fetched_at 'YYYY-MM-DDTHH:MM:SSZ', payload {departures, arrivals})."""
    with gzip.open(path, "rt", encoding="utf-8") as g:
        env = json.load(g)
    if isinstance(env, dict) and "payload" in env:
        fetched = env.get("fetched_at")
        fetched_at = fmt_utc(parse_utc(fetched)) if fetched else stamp_from_name(path.name)
        payload = env.get("payload") or {}
    else:  # arquivo sem envelope (não deveria acontecer): usa o carimbo do nome
        fetched_at, payload = stamp_from_name(path.name), (env or {})
    if fetched_at is None:
        raise ValueError(f"snapshot sem fetched_at: {path.name}")
    return fetched_at, payload


def iter_snapshots(site: str) -> Iterator[tuple[Path, str, dict]]:
    """Snapshots legíveis de um site, em ordem; parciais/corrompidos são pulados com log."""
    for p in list_snapshots(site):
        try:
            fetched_at, payload = load_snapshot(p)
        except (OSError, EOFError, ValueError) as e:  # BadGzipFile ⊂ OSError, JSONDecodeError ⊂ ValueError
            log(f"live: snapshot ilegível {rel(p)} ({e!r}); ignorado")
            continue
        yield p, fetched_at, payload


def iter_flights(section) -> Iterator[tuple[str, dict]]:
    """Itera (date_key, voo) tanto para o formato dict {'YYYY-MM-DD': [...]} quanto lista plana."""
    if isinstance(section, dict):
        for day, items in section.items():
            for f in items or []:
                if isinstance(f, dict):
                    yield str(day), f
    elif isinstance(section, list):
        for f in section:
            if isinstance(f, dict):
                yield (f.get("original_scheduled_time") or "")[:10], f


def _snapshot_flights(payload: dict) -> Iterator[tuple[str, str, dict]]:
    """(direction, date_key, voo) para as duas seções de um payload."""
    for section, direction, _other in SECTIONS:
        for date_key, f in iter_flights((payload or {}).get(section)):
            yield direction, date_key, f


def sched_local_of(f: dict, date_key: str | None = None) -> str | None:
    """Horário previsto ORIGINAL local 'YYYY-MM-DDTHH:MM:SS' (de original_scheduled_time, ou
    date_key + scheduled_time como fallback). None se não houver."""
    m = _OST_RE.match((f.get("original_scheduled_time") or "").strip())
    if m:
        return f"{m.group(1)}T{m.group(2)}:00"
    st = (f.get("scheduled_time") or "").strip()
    if date_key and _DATE_RE.match(date_key) and _HHMM_RE.match(st):
        h, mi = st.split(":")
        return f"{date_key}T{int(h):02d}:{mi}:00"
    return None


def _light(site: str, direction: str, f: dict, date_key: str | None) -> tuple[str, str | None, str | None] | None:
    """Extração barata para percorrer muitos snapshots: (event_key, status_raw, estimated_time raw)."""
    sched_local = sched_local_of(f, date_key)
    if sched_local is None:
        return None
    code = (f.get("flight") or "").strip()
    return f"{site}|{direction}|{code}|{sched_local}", _text(f.get("status")), (f.get("estimated_time") or "").strip() or None


def normalize_flight(site: str, direction: str, f: dict, fetched_at: str, date_key: str | None = None) -> dict:
    """Um voo do painel → linha plana (ver chaves no FLIGHT_SCHEMA).

    `direction` aceita 'dep'/'arr' (ou 'departures'/'arrivals'). Levanta ValueError quando o voo não
    tem horário previsto (nem original_scheduled_time nem date_key + scheduled_time).
    """
    site = site.upper()
    direction = DIRECTION_ALIASES[direction]
    airport_icao = FRAPORT_ICAO[site]
    sched_local = sched_local_of(f, date_key)
    if sched_local is None:
        raise ValueError(f"voo sem horário previsto: {f.get('flight')!r}")
    sched_dt = datetime.fromisoformat(sched_local)
    sched_utc_dt = tz.local_naive_to_utc(sched_dt, airport_icao)

    code = (f.get("flight") or "").strip()
    carrier_iata, number = keys.split_fraport_flight(code)
    carrier_iata = carrier_iata or None
    flight_number = number if carrier_iata else None
    carrier_icao = keys.carrier_icao_from_iata(carrier_iata) if carrier_iata else None
    carrier_group = keys.carrier_group(carrier_icao) if carrier_icao else "outras"

    place = f.get("destination" if direction == "dep" else "origin")
    other_iata = other_name = None
    if isinstance(place, dict):
        other_iata = _text(place.get("iata"))
        other_name = _text(place.get("name"))
    other_uf, other_city = split_place(other_name)
    other_icao = iata_to_icao().get(other_iata.upper()) if other_iata else None

    est_dt = tz.hhmm_near((f.get("estimated_time") or "").strip(), sched_dt)
    status_raw = _text(f.get("status"))
    st = vocab.canon(SOURCE, status_raw) if status_raw else vocab.Status("unknown", "FlightLeg", "provisório", 0.0, "sem status")
    delay_min = None
    if est_dt is not None and st.status_canon != "cancelled":
        delay_min = round((est_dt - sched_dt).total_seconds() / 60)

    origin_icao = airport_icao if direction == "dep" else other_icao
    flight_key = None
    if carrier_icao and origin_icao and flight_number:
        flight_key = keys.flight_key(carrier_icao, flight_number, origin_icao, sched_utc_dt)
    fid = f.get("id")
    fraport_id = int(fid) if isinstance(fid, int) or (isinstance(fid, str) and fid.isdigit()) else None

    return {
        "site": site,
        "airport_icao": airport_icao,
        "direction": direction,
        "flight_code_raw": code,
        "carrier_iata": carrier_iata,
        "flight_number": flight_number,
        "carrier_icao": carrier_icao,
        "carrier_group": carrier_group,
        "airline_name": _text(f.get("airline")),
        "other_iata": other_iata,
        "other_name_raw": other_name,
        "other_city": other_city,
        "other_uf": other_uf,
        "other_icao": other_icao,
        "sched_local": sched_local,
        "sched_utc": fmt_utc(sched_utc_dt),
        "sched_date_local": sched_local[:10],
        "sched_hour_local": sched_dt.hour,
        "est_local": fmt_local(est_dt) if est_dt else None,
        "est_utc": fmt_utc(tz.local_naive_to_utc(est_dt, airport_icao)) if est_dt else None,
        "delay_min": delay_min,
        "status_raw": status_raw,
        "status_canon": st.status_canon,
        "event_class": st.event_class,
        "status_kind": st.status_kind,
        "confidence": float(st.confidence),
        "is_disruption": st.status_canon in vocab.DISRUPTION,
        "gate": _text(f.get("gate")),
        "fraport_id": fraport_id,
        "event_key": f"{site}|{direction}|{code}|{sched_local}",
        "flight_key": flight_key,
        "source": SOURCE,
        "fetched_at": fetched_at,
    }


FLIGHT_SCHEMA = pa.schema([
    ("site", pa.string()), ("airport_icao", pa.string()), ("direction", pa.string()),
    ("flight_code_raw", pa.string()), ("carrier_iata", pa.string()), ("flight_number", pa.string()),
    ("carrier_icao", pa.string()), ("carrier_group", pa.string()), ("airline_name", pa.string()),
    ("other_iata", pa.string()), ("other_name_raw", pa.string()), ("other_city", pa.string()),
    ("other_uf", pa.string()), ("other_icao", pa.string()),
    ("sched_local", pa.string()), ("sched_utc", pa.string()), ("sched_date_local", pa.string()),
    ("sched_hour_local", pa.int64()),
    ("est_local", pa.string()), ("est_utc", pa.string()), ("delay_min", pa.int64()),
    ("status_raw", pa.string()), ("status_canon", pa.string()), ("event_class", pa.string()),
    ("status_kind", pa.string()), ("confidence", pa.float64()), ("is_disruption", pa.bool_()),
    ("gate", pa.string()), ("fraport_id", pa.int64()),
    ("event_key", pa.string()), ("flight_key", pa.string()), ("source", pa.string()), ("fetched_at", pa.string()),
])
LATEST_SCHEMA = pa.schema(list(FLIGHT_SCHEMA) + [
    pa.field("first_seen_at", pa.string()), pa.field("n_snapshots", pa.int64()),
    pa.field("prev_status_raw", pa.string()), pa.field("status_changed_at", pa.string()),
])
EVENTS_SCHEMA = pa.schema([
    ("site", pa.string()), ("direction", pa.string()), ("flight_code_raw", pa.string()),
    ("carrier_group", pa.string()), ("carrier_icao", pa.string()), ("other_iata", pa.string()),
    ("other_uf", pa.string()), ("sched_local", pa.string()), ("sched_date_local", pa.string()),
    ("changed_at", pa.string()), ("field", pa.string()), ("from_value", pa.string()),
    ("to_value", pa.string()), ("status_canon_to", pa.string()),
])


def _site_stream(site: str) -> Iterator[_Snapshot]:
    for _path, fetched_at, payload in iter_snapshots(site):
        yield fetched_at, payload


def _latest_from_stream(site: str, stream: Iterable[_Snapshot]) -> list[dict]:
    """Linhas do último snapshot do stream + first_seen_at / n_snapshots / prev_status_raw /
    status_changed_at acumulados ao longo de todos os snapshots anteriores."""
    site = site.upper()
    state: dict[str, dict] = {}
    last: _Snapshot | None = None
    for fetched_at, payload in stream:
        seen: set[str] = set()
        for direction, date_key, f in _snapshot_flights(payload):
            lt = _light(site, direction, f, date_key)
            if lt is None or lt[0] in seen:
                continue
            key, status, _est = lt
            seen.add(key)
            s = state.get(key)
            if s is None:
                state[key] = {"first_seen_at": fetched_at, "n": 1, "status": status, "since": None, "prev": None}
            else:
                s["n"] += 1
                if status != s["status"]:
                    s["prev"], s["status"], s["since"] = s["status"], status, fetched_at
        last = (fetched_at, payload)
    if last is None:
        log(f"live: fraport {site} sem snapshots")
        return []
    fetched_at, payload = last
    rows: list[dict] = []
    seen = set()
    skipped = dups = 0
    for direction, date_key, f in _snapshot_flights(payload):
        try:
            row = normalize_flight(site, direction, f, fetched_at, date_key)
        except (ValueError, KeyError):
            skipped += 1
            continue
        if row["event_key"] in seen:
            dups += 1
            continue
        seen.add(row["event_key"])
        s = state[row["event_key"]]
        row.update(first_seen_at=s["first_seen_at"], n_snapshots=s["n"], prev_status_raw=s["prev"], status_changed_at=s["since"])
        rows.append(row)
    if skipped or dups:
        log(f"live: fraport {site}: {skipped} voos sem horário e {dups} duplicados ignorados")
    return rows


def fraport_latest() -> pa.Table:
    """Estado atual do painel (último snapshot de cada site, ambas as direções) com histórico resumido."""
    rows: list[dict] = []
    for site in FRAPORT_ICAO:
        site_rows = _latest_from_stream(site, _site_stream(site))
        log(f"live: fraport_latest {site}: {len(site_rows)} voos")
        rows.extend(site_rows)
    rows.sort(key=lambda r: (r["site"], r["direction"], r["sched_utc"]))
    return pa.Table.from_pylist(rows, schema=LATEST_SCHEMA)


def _events_from_stream(site: str, stream: Iterable[_Snapshot]) -> list[dict]:
    """Percorre os snapshots em ordem e emite uma linha por mudança observada (ver EVENTS_SCHEMA)."""
    site = site.upper()
    airport_icao = FRAPORT_ICAO[site]
    state: dict[str, dict] = {}  # event_key → {direction, date_key, f, status, est}
    events: list[dict] = []

    def emit(s: dict, changed_at: str, field: str, from_value: str | None, to_value: str | None) -> None:
        try:
            n = normalize_flight(site, s["direction"], s["f"], changed_at, s["date_key"])
        except (ValueError, KeyError):
            return
        if field == "estimated":  # 'HH:MM' cru → horário local resolvido contra o previsto
            sched_dt = datetime.fromisoformat(n["sched_local"])
            fv, tv = tz.hhmm_near(from_value or "", sched_dt), tz.hhmm_near(to_value or "", sched_dt)
            from_value, to_value = (fmt_local(fv) if fv else None), (fmt_local(tv) if tv else None)
        events.append({
            "site": site, "direction": n["direction"], "flight_code_raw": n["flight_code_raw"],
            "carrier_group": n["carrier_group"], "carrier_icao": n["carrier_icao"],
            "other_iata": n["other_iata"], "other_uf": n["other_uf"],
            "sched_local": n["sched_local"], "sched_date_local": n["sched_date_local"],
            "changed_at": changed_at, "field": field, "from_value": from_value, "to_value": to_value,
            "status_canon_to": vocab.canon(SOURCE, to_value).status_canon if field == "status" and to_value else None,
        })

    for fetched_at, payload in stream:
        now = parse_utc(fetched_at)
        present: set[str] = set()
        for direction, date_key, f in _snapshot_flights(payload):
            lt = _light(site, direction, f, date_key)
            if lt is None or lt[0] in present:
                continue
            key, status, est = lt
            present.add(key)
            s = state.get(key)
            if s is None:
                s = state[key] = {"direction": direction, "date_key": date_key, "f": f, "status": status, "est": est}
                emit(s, fetched_at, "first_seen", None, status)
                continue
            s["f"], s["date_key"] = f, date_key
            if status != s["status"]:
                emit(s, fetched_at, "status", s["status"], status)
                s["status"] = status
            if est != s["est"]:
                emit(s, fetched_at, "estimated", s["est"], est)
                s["est"] = est
        for key in [k for k in state if k not in present]:
            s = state.pop(key)
            sched_utc = tz.local_naive_to_utc(datetime.fromisoformat(key.rsplit("|", 1)[1]), airport_icao)
            if sched_utc - now >= DISAPPEAR_HORIZON:
                emit(s, fetched_at, "disappeared", s["status"], None)
    return events


def fraport_events() -> pa.Table:
    """Mudanças observadas entre snapshots consecutivos, por site."""
    rows: list[dict] = []
    for site in FRAPORT_ICAO:
        ev = _events_from_stream(site, _site_stream(site))
        log(f"live: fraport_events {site}: {len(ev)} eventos")
        rows.extend(ev)
    rows.sort(key=lambda r: (r["site"], r["changed_at"], r["direction"], r["sched_local"], r["field"]))
    return pa.Table.from_pylist(rows, schema=EVENTS_SCHEMA)


# --------------------------------------------------------------------------- SIROS diário
SIROS_WEEKDAY_COLS = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]  # índice = isoweekday − 1
SIROS_SCHEMA = pa.schema([
    ("snapshot_date", pa.string()), ("carrier_icao", pa.string()), ("carrier_name", pa.string()),
    ("carrier_group", pa.string()), ("flight_number", pa.string()), ("number_prefix", pa.string()),
    ("equipment", pa.string()), ("seats", pa.int64()), ("n_siros", pa.string()),
    ("data_registro_utc", pa.string()), ("inicio_operacao", pa.string()), ("fim_operacao", pa.string()),
    ("natureza", pa.string()), ("tipo_servico", pa.string()), ("objeto", pa.string()),
    ("leg_number", pa.int64()), ("origin_icao", pa.string()), ("origin_name", pa.string()),
    ("dest_icao", pa.string()), ("dest_name", pa.string()),
    ("sched_dep_utc", pa.string()), ("sched_arr_utc", pa.string()), ("operates_today", pa.bool_()),
    ("codeshare", pa.string()), ("flight_key", pa.string()), ("is_focus_leg", pa.bool_()),
])
_NE, _HUB = frozenset(NE_AIRPORTS), frozenset(HUB_AIRPORTS)


def list_siros_diario() -> list[Path]:
    """Snapshots diários do SIROS em ordem cronológica ('diario_YYYY-MM-DD.csv.gz')."""
    return sorted((ARCHIVE / "siros" / "diario").glob("diario_*.csv.gz"), key=lambda p: p.name)


def _int(s: str | None) -> int | None:
    s = (s or "").strip()
    return int(s) if s.isdigit() else None


def _hhmm_on(day: date, hhmm: str | None) -> datetime | None:
    s = (hhmm or "").strip()
    if not _HHMM_RE.match(s):
        return None
    h, m = (int(x) for x in s.split(":"))
    return datetime(day.year, day.month, day.day, h, m, tzinfo=tz.UTC)


def is_focus_leg(origin_icao: str | None, dest_icao: str | None) -> bool:
    """Trecho de interesse: toca SBPA, ou liga um hub a um aeroporto do Nordeste (em qualquer sentido)."""
    o, d = origin_icao or "", dest_icao or ""
    return FOCUS_ORIGIN in (o, d) or (o in _HUB and d in _NE) or (o in _NE and d in _HUB)


def siros_leg(rec: dict[str, str], snapshot_date: str) -> dict:
    """Uma linha do CSV diário (dict pelo cabeçalho original) → linha do mart (ver SIROS_SCHEMA)."""
    day = date.fromisoformat(snapshot_date)
    g = lambda k: (rec.get(k) or "").strip()  # noqa: E731
    carrier_icao = g("Cód. Empresa").upper() or None
    flight_number, number_prefix = keys.normalize_number(g("Nr. Voo"))
    flight_number = flight_number or None
    origin_icao, dest_icao = g("Cód Origem").upper() or None, g("Cód Destino").upper() or None
    dep_dt = _hhmm_on(day, g("Partida Prevista"))
    arr_dt = _hhmm_on(day, g("Chegada Prevista"))
    if dep_dt and arr_dt and arr_dt < dep_dt:
        arr_dt += timedelta(days=1)
    registro = None
    for fmt in ("%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M"):
        try:
            registro = fmt_utc(tz.brasilia_naive_to_utc(datetime.strptime(g("Data Registro"), fmt)))
            break
        except ValueError:
            continue
    weekday_val = g(SIROS_WEEKDAY_COLS[day.isoweekday() - 1])
    flight_key = None
    if carrier_icao and flight_number and origin_icao and dep_dt:
        flight_key = keys.flight_key(carrier_icao, flight_number, origin_icao, dep_dt)
    return {
        "snapshot_date": snapshot_date,
        "carrier_icao": carrier_icao,
        "carrier_name": g("Empresa") or None,
        "carrier_group": keys.carrier_group(carrier_icao) if carrier_icao else "outras",
        "flight_number": flight_number,
        "number_prefix": number_prefix or None,
        "equipment": g("Equip.") or None,
        "seats": _int(g("Qtde Assentos")),
        "n_siros": g("Nº SIROS") or None,
        "data_registro_utc": registro,
        "inicio_operacao": g("Início Operação") or None,
        "fim_operacao": g("Fim Operação") or None,
        "natureza": g("Natureza Operação") or None,
        "tipo_servico": g("Tipo Serviço") or None,
        "objeto": g("Objeto Transporte") or None,
        "leg_number": _int(g("Nr. Etapa")),
        "origin_icao": origin_icao,
        "origin_name": g("Arpt Origem") or None,
        "dest_icao": dest_icao,
        "dest_name": g("Arpt Destino") or None,
        "sched_dep_utc": fmt_utc(dep_dt) if dep_dt else None,
        "sched_arr_utc": fmt_utc(arr_dt) if arr_dt else None,
        # a coluna do dia da semana traz o dígito (1..7) quando opera; '0' ou vazio quando não
        "operates_today": weekday_val not in ("", "0"),
        "codeshare": g("Codeshare") or None,
        "flight_key": flight_key,
        "is_focus_leg": is_focus_leg(origin_icao, dest_icao),
    }


def read_siros_diario(path: Path) -> tuple[str, list[dict[str, str]]]:
    """Lê 'diario_YYYY-MM-DD.csv.gz' (BOM, linha 1 'Importante: Horários em UTC', ';') →
    (snapshot_date, registros como dicts pelo cabeçalho original)."""
    m = re.search(r"(\d{4}-\d{2}-\d{2})", path.name)
    if not m:
        raise ValueError(f"nome sem data: {path.name}")
    with gzip.open(path, "rt", encoding="utf-8-sig", newline="") as g:
        lines = g.read().splitlines()
    header_idx = next((i for i, ln in enumerate(lines[:5]) if "Nr. Voo" in ln), None)
    if header_idx is None:
        raise ValueError(f"cabeçalho SIROS não encontrado em {path.name}")
    reader = csv.reader(lines[header_idx:], delimiter=";")
    header = [h.strip() for h in next(reader)]
    recs = [dict(zip(header, row)) for row in reader if any(c.strip() for c in row)]
    return m.group(1), recs


def siros_today() -> pa.Table:
    """Malha planejada do snapshot diário mais recente do SIROS (UTC)."""
    snaps = list_siros_diario()
    if not snaps:
        log("live: siros diário sem snapshots")
        return pa.Table.from_pylist([], schema=SIROS_SCHEMA)
    snapshot_date, recs = read_siros_diario(snaps[-1])
    rows = [siros_leg(r, snapshot_date) for r in recs]
    rows.sort(key=lambda r: (r["sched_dep_utc"] or "", r["carrier_icao"] or "", r["flight_number"] or "", r["leg_number"] or 0))
    log(f"live: siros_today {snapshot_date}: {len(rows)} trechos, {sum(r['is_focus_leg'] for r in rows)} de interesse")
    return pa.Table.from_pylist(rows, schema=SIROS_SCHEMA)


# --------------------------------------------------------------------------- INMET
def list_inmet_snapshots() -> list[Path]:
    return sorted((ARCHIVE / "inmet").glob("*/*.json.gz"), key=lambda p: p.name)


def _brasilia_str_to_utc(s: str | None) -> str | None:
    """'2026-10-24 00:01' (horário de Brasília, como o INMET publica) → ISO UTC; inválido → None."""
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"):
        try:
            return fmt_utc(tz.brasilia_naive_to_utc(datetime.strptime((s or "").strip(), fmt)))
        except ValueError:
            continue
    return None


def inmet_alert(a: dict, grupo: str | None = None) -> dict:
    """Um aviso do INMET → dict enxuto (sem 'poligono', 'icone' nem o texto longo de 'municipios')."""
    estados = a.get("estados") or ""
    ufs: list[str] = []
    for name in (x.strip() for x in estados.split(",")):
        if not name:
            continue
        sigla = uf_by_name().get(_fold(name))
        if sigla:
            ufs.append(sigla)
        else:
            log(f"live: inmet estado desconhecido {name!r}")
    geocodes = [x.strip() for x in (a.get("geocodes") or "").split(",") if x.strip()]
    inicio, fim = a.get("inicio"), a.get("fim")
    return {
        "id": a.get("id"),
        "id_aviso": a.get("id_aviso"),
        "grupo": grupo,
        "codigo": a.get("codigo"),
        "descricao": a.get("descricao"),
        "severidade": a.get("severidade"),
        "cor": a.get("aviso_cor"),
        "inicio": inicio,
        "fim": fim,
        "inicio_utc": _brasilia_str_to_utc(inicio),
        "fim_utc": _brasilia_str_to_utc(fim),
        "estados": estados,
        "ufs": ufs,
        "regioes": a.get("regioes"),
        "n_municipios": len(geocodes),
        "geocodes": geocodes,
        "riscos": a.get("riscos"),
        "instrucoes": a.get("instrucoes"),
        "alterado": a.get("alterado"),
        "encerrado": a.get("encerrado"),
    }


def inmet_alerts() -> dict:
    """Avisos ativos do snapshot INMET mais recente ({'hoje': [...], 'futuro': [...]} achatado)."""
    snaps = list_inmet_snapshots()
    if not snaps:
        log("live: inmet sem snapshots")
        return {"fetched_at": None, "source": "inmet", "snapshot_file": None, "n_alerts": 0, "alerts": []}
    path = snaps[-1]
    with gzip.open(path, "rt", encoding="utf-8") as g:
        j = json.load(g)
    groups = j.items() if isinstance(j, dict) else [(None, j)]
    alerts = [inmet_alert(a, grupo) for grupo, lst in groups if isinstance(lst, list) for a in lst if isinstance(a, dict)]
    alerts.sort(key=lambda a: (a["inicio"] or "", a["id"] or 0))
    return {
        "fetched_at": stamp_from_name(path.name),
        "source": "inmet",
        "snapshot_file": rel(path),
        "n_alerts": len(alerts),
        "alerts": alerts,
    }


# --------------------------------------------------------------------------- as-of
def asof() -> dict:
    """Atualidade das fontes 'live' (para o rodapé do site)."""
    out: dict = {"built_at": fmt_utc(datetime.now(tz.UTC)), "fraport": {}, "inmet": None, "siros_diario": None}
    for site in FRAPORT_ICAO:
        snaps = list_snapshots(site)
        entry = None
        for p in reversed(snaps):  # último snapshot legível
            try:
                fetched_at, payload = load_snapshot(p)
            except (OSError, EOFError, ValueError):
                continue
            dates: dict[str, dict[str, int]] = {}
            n = {"dep": 0, "arr": 0}
            for direction, date_key, _f in _snapshot_flights(payload):
                dates.setdefault(date_key or "?", {"dep": 0, "arr": 0})[direction] += 1
                n[direction] += 1
            entry = {"fetched_at": fetched_at, "snapshot_file": rel(p), "n_snapshots": len(snaps),
                     "n_dep": n["dep"], "n_arr": n["arr"], "dates": dict(sorted(dates.items()))}
            break
        out["fraport"][site] = entry
    if list_inmet_snapshots():
        a = inmet_alerts()
        out["inmet"] = {"fetched_at": a["fetched_at"], "snapshot_file": a["snapshot_file"], "n_alerts": a["n_alerts"]}
    siros = list_siros_diario()
    if siros:
        snapshot_date, recs = read_siros_diario(siros[-1])
        out["siros_diario"] = {"snapshot_date": snapshot_date, "snapshot_file": rel(siros[-1]), "n_legs": len(recs)}
    return out
