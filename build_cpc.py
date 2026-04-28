#!/usr/bin/env python3
"""Build the Amstrad CPC version of Soul Player."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from build_cpc import main


if __name__ == "__main__":
    raise SystemExit(main())

