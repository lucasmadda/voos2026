import sys; from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "pipeline"))
from voos.marts.weather import metar_recent
from voos.io import write_parquet_stdout
write_parquet_stdout(metar_recent(days=8))
