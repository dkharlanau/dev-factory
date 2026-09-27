"""Compact task-local repository navigation."""
from __future__ import annotations
import hashlib
import json
from collections import Counter
from pathlib import PurePosixPath
from .repository import git

ROOT_HINTS={'AGENTS.md','README.md','CONTRIBUTING.md','pyproject.toml','package.json','Cargo.toml',
            'go.mod','Makefile','justfile','tsconfig.json','vite.config.ts','vite.config.js'}

def _inside(path, prefix):
    prefix=prefix.rstrip('/')
    return path==prefix or path.startswith(prefix+'/')

def repository_registry(path, base_sha, task_paths, *, guidance_files=(), cold_paths=(), max_files=40):
    files=[x for x in git(path,'ls-tree','-r','--name-only',base_sha).splitlines() if x]
    cold=[x.rstrip('/') for x in cold_paths if x]
    task_paths=list(dict.fromkeys(task_paths))
    def task_allows_cold(f):
        return any(_inside(f,p) for p in task_paths if any(_inside(p,c) or _inside(c,p) for c in cold))
    active=[f for f in files if not any(_inside(f,c) for c in cold) or task_allows_cold(f)]
    counts=Counter((PurePosixPath(f).parts or ('.',))[0] for f in active)
    parents={str(PurePosixPath(p).parent) for p in task_paths}
    relevant=set(guidance_files)
    for f in active:
        parent=str(PurePosixPath(f).parent)
        if f in ROOT_HINTS or any(_inside(f,p) or _inside(p,f) for p in task_paths) or parent in parents:
            relevant.add(f)
    ordered=sorted(relevant,key=lambda f:(0 if any(_inside(f,p) or _inside(p,f) for p in task_paths) else
                                          1 if f in guidance_files else 2, f))
    nearby=ordered[:max(1,int(max_files))]
    payload={'base_sha':base_sha,'file_count':len(files),'active_file_count':len(active),
             'cold_excluded':len(files)-len(active),'top_roots':dict(counts.most_common(12))}
    payload['registry_hash']=hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    return payload, {'files':nearby,'cold_excluded':payload['cold_excluded']}
