"""Cliente HTTP com cache por ETag/Last-Modified em data/raw/manifest.json."""
from __future__ import annotations

import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import certifi
import httpx

from .config import RAW

MANIFEST = RAW / "manifest.json"
USER_AGENT = "voos2026/0.1"  # sem URL/parênteses: o WAF do SIROS rejeita


def log(msg: str) -> None:
    print(f"[{datetime.now(timezone.utc):%H:%M:%S}] {msg}", file=sys.stderr, flush=True)


def client(timeout: float = 120.0) -> httpx.Client:
    return httpx.Client(
        timeout=timeout,
        headers={"User-Agent": USER_AGENT},
        follow_redirects=True,
        verify=certifi.where(),
    )


def get_bytes(url: str, headers: dict | None = None, retries: int = 3, timeout: float = 120.0) -> bytes:
    last: Exception | None = None
    for attempt in range(retries):
        try:
            with client(timeout) as c:
                r = c.get(url, headers=headers or {})
                if r.status_code in (429, 500, 502, 503, 504):
                    raise httpx.HTTPStatusError(f"{r.status_code}", request=r.request, response=r)
                r.raise_for_status()
                return r.content
        except Exception as e:  # noqa: BLE001
            last = e
            wait = 2 ** attempt * 3
            log(f"GET falhou ({e}); tentativa {attempt + 1}/{retries}, esperando {wait}s")
            time.sleep(wait)
    raise RuntimeError(f"GET {url} falhou após {retries} tentativas: {last}")


def _load_manifest() -> dict:
    if MANIFEST.exists():
        return json.loads(MANIFEST.read_text())
    return {}


def _save_manifest(m: dict) -> None:
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps(m, indent=1, ensure_ascii=False, sort_keys=True))


def cached_download(url: str, dest: Path, headers: dict | None = None, force: bool = False,
                    max_age_hours: float | None = None) -> Path:
    """Baixa `url` para `dest` só se ETag/Last-Modified mudou (HEAD) ou o arquivo não existe.

    `max_age_hours`: se definido e o arquivo local for mais novo que isso, nem faz HEAD.
    Registra etag, last_modified, fetched_at, size e sha256 em data/raw/manifest.json.
    """
    dest = Path(dest)
    manifest = _load_manifest()
    entry = manifest.get(url, {})
    if dest.exists() and not force:
        if max_age_hours is not None and entry.get("fetched_at"):
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(entry["fetched_at"])).total_seconds() / 3600
            if age < max_age_hours:
                return dest
        try:
            with client(60) as c:
                h = c.head(url, headers=headers or {})
            etag = h.headers.get("etag")
            lm = h.headers.get("last-modified")
            if h.status_code == 200 and (etag or lm) and etag == entry.get("etag") and lm == entry.get("last_modified"):
                return dest
        except Exception as e:  # noqa: BLE001
            log(f"HEAD {url} falhou ({e}); usando cópia local")
            return dest
    log(f"baixando {url}")
    with client(300) as c:
        r = c.get(url, headers=headers or {})
        r.raise_for_status()
        content = r.content
        etag = r.headers.get("etag")
        lm = r.headers.get("last-modified")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(content)
    manifest[url] = {
        "etag": etag,
        "last_modified": lm,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "size": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
        "path": str(dest.relative_to(RAW.parent.parent)) if dest.is_relative_to(RAW.parent.parent) else str(dest),
    }
    _save_manifest(manifest)
    return dest


def source_stamp(url: str) -> dict:
    """Metadados de proveniência de uma URL já baixada (para o mart `sources`)."""
    return _load_manifest().get(url, {})
