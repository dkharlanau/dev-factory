from __future__ import annotations
import importlib.metadata
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from .runtime import Runtime, versions
from .policy import choose_model
from .state import atomic_json


def doctor(config, *, runtime_factory=Runtime):
    cli=shutil.which('codex')
    r=subprocess.run([cli,'--version'],capture_output=True,text=True,timeout=10) if cli else None
    result={'python':sys.version.split()[0],'platform':platform.platform(),'architecture':platform.machine(),
            'installed_cli':r.stdout.strip() if r else None,'packages':versions(),'model_turns':0,
            'parent_model':'unchanged / not controlled','foreground_only':True}
    with runtime_factory(Path(config['root']),inventory_only=True) as runtime:
        result.update(runtime.inventory())
        result['profiles']={p:choose_model(p,config,runtime.catalog,runtime.native).dict() for p in config['profiles']}
    path=Path(config['state_dir'])/'evidence'/'doctor.json'
    atomic_json(path,result)
    result['evidence_path']=str(path)
    return result
