"""I/O dos data loaders: Parquet zstd no stdout, DuckDB 1.x, logs no stderr."""
from __future__ import annotations

import io
import json
import sys

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

from .config import REPO_ROOT
from .http import log  # noqa: F401  (re-export)


def duck(threads: int = 4) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.execute(f"SET threads={threads}")
    con.execute("SET TimeZone='UTC'")
    return con


def write_parquet_stdout(table: pa.Table, compression: str = "zstd") -> None:
    buf = pa.BufferOutputStream()
    pq.write_table(table, buf, compression=compression)
    sys.stdout.buffer.write(buf.getvalue().to_pybytes())
    sys.stdout.buffer.flush()


def write_json_stdout(obj) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False))
    sys.stdout.flush()


def write_bytes_stdout(b: bytes) -> None:
    sys.stdout.buffer.write(b)
    sys.stdout.buffer.flush()


def rel(path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except Exception:  # noqa: BLE001
        return str(path)
