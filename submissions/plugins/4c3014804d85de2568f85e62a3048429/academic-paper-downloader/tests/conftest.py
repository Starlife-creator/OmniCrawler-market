import sys
from pathlib import Path

# Mirror the subprocess worker's package-root import path for bundled helpers.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
