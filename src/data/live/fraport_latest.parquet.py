import sys; from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "pipeline"))
from voos.marts.live import fraport_latest
from voos.io import write_parquet_stdout
write_parquet_stdout(fraport_latest())
