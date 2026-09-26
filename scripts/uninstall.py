#!/usr/bin/env python3
"""Remove only this installation's marked virtual environment. Preserve all work."""
from pathlib import Path
import shutil
root=Path(__file__).resolve().parents[1]
venv=root/'.venv'
marker=venv/'.devfactory-owner'
if not marker.exists() or marker.read_text().strip()!='devfactory-owned-environment-v1':
    raise SystemExit('No owned environment marker; refusing deletion. Source and receipts preserved.')
if venv.is_symlink(): raise SystemExit('Refusing symlinked environment')
shutil.rmtree(venv)
print('Removed only the local Factory virtual environment. Source, skill, receipts and worktrees preserved.')
print('No global Codex settings or installed plugins changed. Remove a separately created global skill link manually if applicable.')
