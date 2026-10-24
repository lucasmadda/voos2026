import sys; from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "pipeline"))
from datetime import date, datetime, timezone
from voos.marts.weather import metar_hourly
from voos.io import write_parquet_stdout
write_parquet_stdout(metar_hourly(date(2024, 1, 1), datetime.now(timezone.utc).date()))
