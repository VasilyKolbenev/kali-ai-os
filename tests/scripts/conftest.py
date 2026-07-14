"""tests/scripts импортируют из scripts/ (не пакет) — кладём repo root в sys.path."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
