"""Ensures the repository root is importable as `contracts` without setting PYTHONPATH."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
