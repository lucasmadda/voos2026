"""Captura de fontes voláteis → snapshots imutáveis em data/archive/.

Só biblioteca padrão (roda com o python3 do sistema ou do .venv, e sob launchd/cron):
  python -m voos.capture --site POA --site FOR --inmet --siros-diario [--loop 900]

- Fraport (painel de voos POA/FOR): janela rolante ≈ −48 h/+25 h → arquivar sempre.
  Remove os SVGs inline (`airline.icon`, `status.icon`): 11 MB → ~25 KB gz.
  data/archive/fraport/{SITE}/{YYYY-MM-DD}/{YYYYMMDDTHHMMSSZ}.json.gz (data = dia UTC da coleta)
- INMET avisos ativos: salva só quando o corpo muda (sha256).
- SIROS diário (malha planejada de hoje, UTC): 1 cópia por dia.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from .config import ARCHIVE, FRAPORT_SITES, FRAPORT_URL, INMET_ALERTS_URL, SIROS_DIARIO_SERIE, SIROS_DIARIO_URL

USER_AGENT = "voos2026/0.1"  # sem URL/parênteses: o WAF do SIROS rejeita
STATUS_ALERT = {"Cancelado", "Atrasado", "Alternado", "Cancelled", "Delayed", "Diverted"}


def log(msg: str) -> None:
    print(f"[{datetime.now(timezone.utc):%Y-%m-%d %H:%M:%S}Z] {msg}", file=sys.stderr, flush=True)


def _ssl_context() -> ssl.SSLContext:
    try:
        import certifi  # type: ignore

        return ssl.create_default_context(cafile=certifi.where())
    except Exception:  # noqa: BLE001
        return ssl.create_default_context()


def fetch(url: str, headers: dict | None = None, timeout: int = 120, retries: int = 3) -> bytes:
    """GET com urllib; se o TLS do Python falhar (python.org sem certificados), cai para curl."""
    hdrs = {"User-Agent": USER_AGENT, "Accept": "application/json, text/csv, */*"}
    hdrs.update(headers or {})
    last: Exception | None = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=hdrs)
            with urllib.request.urlopen(req, timeout=timeout, context=_ssl_context()) as r:
                body = r.read()
            _reject_html(body, url)
            return body
        except (urllib.error.URLError, ssl.SSLError, TimeoutError) as e:
            last = e
            if isinstance(e, urllib.error.URLError) and isinstance(getattr(e, "reason", None), ssl.SSLError) or isinstance(e, ssl.SSLError):
                try:
                    cmd = ["curl", "-sS", "-m", str(timeout), "-A", USER_AGENT]
                    for k, v in hdrs.items():
                        cmd += ["-H", f"{k}: {v}"]
                    cmd.append(url)
                    out = subprocess.run(cmd, check=True, capture_output=True).stdout
                    if out:
                        _reject_html(out, url)
                        return out
                except Exception as ce:  # noqa: BLE001
                    last = ce
            wait = 5 * (attempt + 1)
            log(f"GET {url[:80]}… falhou ({e!r}); nova tentativa em {wait}s")
            time.sleep(wait)
    raise RuntimeError(f"GET {url} falhou após {retries} tentativas: {last!r}")


class RejectedResponse(RuntimeError):
    """Corpo HTML onde se esperava JSON/CSV (ex.: 'Request Rejected' do WAF da ANAC)."""


def _reject_html(body: bytes, url: str) -> None:
    head = body[:200].lstrip(b"\xef\xbb\xbf \r\n\t").lower()
    if head.startswith(b"<html") or head.startswith(b"<!doctype html"):
        raise RejectedResponse(f"resposta HTML inesperada de {url[:80]}: {body[:120]!r}")


def strip_icons(obj):
    """Remove recursivamente chaves 'icon' (SVGs inline) e 'src'/'src_mobile' dentro delas."""
    if isinstance(obj, dict):
        return {k: strip_icons(v) for k, v in obj.items() if k not in ("icon",)}
    if isinstance(obj, list):
        return [strip_icons(x) for x in obj]
    return obj


def _iter_flights(section):
    if isinstance(section, dict):
        for day, items in section.items():
            for f in items or []:
                yield day, f
    elif isinstance(section, list):
        for f in section:
            yield (f.get("original_scheduled_time") or "")[:10], f


def summarize(payload: dict) -> dict:
    out = {"departures": {}, "arrivals": {}, "alerts": []}
    for direction in ("departures", "arrivals"):
        for day, f in _iter_flights(payload.get(direction)):
            out[direction][day] = out[direction].get(day, 0) + 1
            st = (f.get("status") or {}).get("text") if isinstance(f.get("status"), dict) else f.get("status")
            if st in STATUS_ALERT:
                place = f.get("destination") if direction == "departures" else f.get("origin")
                iata = place.get("iata") if isinstance(place, dict) else None
                out["alerts"].append(f"{direction[:3]} {f.get('flight')} {iata} {f.get('original_scheduled_time')} {st}")
    return out


def capture_fraport(site: str, archive: Path = ARCHIVE) -> Path:
    site = site.upper()
    host = FRAPORT_SITES[site]
    t0 = time.time()
    raw = fetch(FRAPORT_URL, headers={"X-Current-Site-Id": host})
    payload = json.loads(raw)
    slim = strip_icons(payload)
    now = datetime.now(timezone.utc)
    envelope = {
        "source": "fraport",
        "site": site,
        "site_id": host,
        "url": FRAPORT_URL,
        "fetched_at": now.isoformat(timespec="seconds"),
        "raw_bytes": len(raw),
        "payload": slim,
    }
    dest = archive / "fraport" / site / f"{now:%Y-%m-%d}" / f"{now:%Y%m%dT%H%M%SZ}.json.gz"
    dest.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(dest, "wt", encoding="utf-8") as g:
        json.dump(envelope, g, ensure_ascii=False)
    s = summarize(slim)
    log(f"fraport {site}: {len(raw)/1e6:.1f} MB em {time.time()-t0:.1f}s → {dest.name} "
        f"({dest.stat().st_size//1024} KB) partidas={s['departures']} chegadas={s['arrivals']}")
    for a in s["alerts"]:
        log(f"  ! {a}")
    return dest


def capture_inmet(archive: Path = ARCHIVE) -> Path | None:
    raw = fetch(INMET_ALERTS_URL)
    sha = hashlib.sha256(raw).hexdigest()
    d = archive / "inmet"
    d.mkdir(parents=True, exist_ok=True)
    last = d / ".last_sha256"
    if last.exists() and last.read_text().strip() == sha:
        log("inmet: sem mudança")
        return None
    now = datetime.now(timezone.utc)
    dest = d / f"{now:%Y-%m-%d}" / f"{now:%Y%m%dT%H%M%SZ}.json.gz"
    dest.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(dest, "wb") as g:
        g.write(raw)
    last.write_text(sha)
    try:
        j = json.loads(raw)
        n = sum(len(v) for v in j.values() if isinstance(v, list))
    except Exception:  # noqa: BLE001
        n = -1
    log(f"inmet: {len(raw)//1024} KB, {n} avisos → {dest.name}")
    return dest


def capture_siros_diario(archive: Path = ARCHIVE) -> Path | None:
    now = datetime.now(timezone.utc)
    dest = archive / "siros" / "diario" / f"diario_{now:%Y-%m-%d}.csv.gz"
    if dest.exists():
        return None
    # a série datada é estável, mas só é publicada ~08Z: antes disso o arquivo do dia (UTC) dá 404
    # e não vale tentar de novo nem cair no diario.csv (o WAF da ANAC o rejeita).
    url = SIROS_DIARIO_SERIE.format(year=now.year, day=f"{now:%Y-%m-%d}")
    try:
        raw = fetch(url, timeout=180, retries=1)
    except Exception as e:  # noqa: BLE001
        if "404" in repr(e):
            log(f"siros diário {now:%Y-%m-%d} ainda não publicado (404); tento na próxima captura")
            return None
        log(f"siros série {now:%Y-%m-%d} indisponível ({e!r}); tentando diario.csv")
        raw = fetch(SIROS_DIARIO_URL, timeout=180)
    dest.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(dest, "wb") as g:
        g.write(raw)
    log(f"siros diário: {len(raw)//1024} KB → {dest.name}")
    return dest


def run_once(sites: list[str], inmet: bool, siros: bool) -> int:
    errors = 0
    for site in sites:
        try:
            capture_fraport(site)
        except Exception as e:  # noqa: BLE001
            errors += 1
            log(f"ERRO fraport {site}: {e!r}")
    if inmet:
        try:
            capture_inmet()
        except Exception as e:  # noqa: BLE001
            errors += 1
            log(f"ERRO inmet: {e!r}")
    if siros:
        try:
            capture_siros_diario()
        except Exception as e:  # noqa: BLE001
            errors += 1
            log(f"ERRO siros: {e!r}")
    return errors


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--site", action="append", choices=sorted(FRAPORT_SITES), help="POA, FOR (repetível)")
    p.add_argument("--inmet", action="store_true")
    p.add_argument("--siros-diario", action="store_true")
    p.add_argument("--loop", type=int, metavar="SECONDS", help="repete a cada N segundos (Ctrl+C para parar)")
    a = p.parse_args(argv)
    sites = a.site or []
    if not sites and not a.inmet and not a.siros_diario:
        p.error("nada a capturar: use --site, --inmet e/ou --siros-diario")
    while True:
        errors = run_once(sites, a.inmet, a.siros_diario)
        if not a.loop:
            return 1 if errors else 0
        log(f"próxima captura em {a.loop}s")
        time.sleep(a.loop)


if __name__ == "__main__":
    raise SystemExit(main())
