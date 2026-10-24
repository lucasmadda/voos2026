import sys; from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "pipeline"))
from datetime import date, datetime, timezone
from voos.marts.weather import weather_daily
from voos.io import write_parquet_stdout
write_parquet_stdout(weather_daily(date(2024, 1, 1), datetime.now(timezone.utc).date()))
