#!/usr/bin/env python3
from pathlib import Path
import runpy


if __name__ == "__main__":
    launcher = Path(__file__).resolve().parent / "scripts" / "dev" / "start.py"
    runpy.run_path(str(launcher), run_name="__main__")
