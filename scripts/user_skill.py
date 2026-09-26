#!/usr/bin/env python3
"""Explicit owner action only. Never replace another installation's skill."""
import argparse
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('action',choices=['enable','disable']);a=p.parse_args()
source=Path(__file__).resolve().parents[1]/'.agents/skills/factory'
target=Path.home()/'.agents/skills/factory'
if a.action=='enable':
    if target.is_symlink() and target.resolve()==source.resolve():
        print('Already enabled')
    elif target.exists() or target.is_symlink():
        raise SystemExit('An existing factory skill belongs to another installation; left untouched')
    else:
        target.parent.mkdir(parents=True,exist_ok=True)
        target.symlink_to(source,target_is_directory=True)
        print('Factory skill enabled. Open a new Codex chat.')
else:
    if target.is_symlink() and target.resolve()==source.resolve():
        target.unlink();print('Removed only this installation\'s Factory skill link')
    else:
        print('No owned global skill link; nothing changed')
