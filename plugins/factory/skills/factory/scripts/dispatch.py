#!/usr/bin/env python3
"""Locate the source checkout or an explicitly installed Factory root; preserve argv."""
import os
from pathlib import Path
import subprocess
import sys

roots=([Path(os.environ['FACTORY_ROOT'])] if os.environ.get('FACTORY_ROOT') else [])+list(Path(__file__).resolve().parents)
root=next((p for p in roots if (p/'factory').is_file() and (p/'src/devfactory').is_dir()),None)
if root is None:
    raise SystemExit('Factory source checkout not found. Set FACTORY_ROOT to its installed directory.')
raise SystemExit(subprocess.call([str(root/'factory'),*(sys.argv[1:] or ['doctor'])]))
