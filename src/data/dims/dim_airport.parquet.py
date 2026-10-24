import sys; from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "pipeline"))
from voos.marts.dims import dim_airport
from voos.io import write_parquet_stdout
write_parquet_stdout(dim_airport())
