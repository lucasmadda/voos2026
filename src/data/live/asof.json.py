import sys; from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "pipeline"))
from voos.marts.live import asof
from voos.io import write_json_stdout
write_json_stdout(asof())
