"""Deterministic composition of already-reviewed slices; no model or remote writes."""
from __future__ import annotations
import json
from pathlib import Path

from .policy import Stop, scopes_overlap
from .repository import apply_delta, changed, create_worktree, fingerprint
from .state import atomic_json, digest


def _inside(path, scopes):
    return any(path==s or path.startswith(s.rstrip('/')+'/') for s in scopes)


def validate_reviewed_slices(runs):
    if len(runs) < 2:
        raise Stop('BLOCKED_BATCH','Batch composition requires at least two reviewed slices')
    ordered=sorted(runs,key=lambda r:r['id'])
    first=ordered[0]['data']
    base=first['base_sha']; project=first['project']
    repo_path=Path(first['repository']['path']).resolve()
    base_branch=first['base_branch']
    seen_scopes=[];expected_files=[];children=[]
    for run in ordered:
        d=run['data']
        if run['state']!='READY_LOCAL' or d.get('acceptance') is not True or d.get('review')!='PASS':
            raise Stop('BLOCKED_BATCH','Every batch slice must be READY_LOCAL with passed acceptance/review')
        if d.get('project')!=project or d.get('base_sha')!=base or d.get('base_branch')!=base_branch:
            raise Stop('BLOCKED_BATCH','Batch slices must share project, base SHA and base branch')
        if Path(d['repository']['path']).resolve()!=repo_path:
            raise Stop('BLOCKED_BATCH','Batch slices must share the exact repository checkout')
        scopes=d.get('subsystem') or []
        if not scopes or scopes_overlap(seen_scopes,scopes):
            raise Stop('BLOCKED_BATCH','Batch slice declared scopes overlap')
        wt=Path(d.get('worktree',''))
        if not wt.is_dir() or not d.get('reviewed_fingerprint'):
            raise Stop('BLOCKED_RECONCILIATION','Reviewed slice worktree/fingerprint unavailable')
        if d.get('reviewed_base')!=base or fingerprint(wt,base)!=d['reviewed_fingerprint']:
            raise Stop('BLOCKED_RECONCILIATION','Reviewed slice changed after review')
        actual=changed(wt,base)
        if not actual:
            raise Stop('BLOCKED_BATCH','Reviewed slice has no changed files')
        if any(not _inside(name,scopes) for name in actual):
            raise Stop('BLOCKED_SCOPE','Reviewed slice contains files outside its declared scope')
        seen_scopes.extend(scopes);expected_files.extend(actual)
        children.append({'run_id':run['id'],'task_id':d['task_id'],'contract_hash':d['contract_hash'],
                         'reviewed_fingerprint':d['reviewed_fingerprint'],'worktree':str(wt),
                         'scopes':scopes,'files':actual})
    return {'project':project,'base_sha':base,'base_branch':base_branch,'repository_path':str(repo_path),
            'children':children,'expected_files':sorted(expected_files),'scopes':seen_scopes}


def compose_reviewed_slices(runs, state_dir):
    meta=validate_reviewed_slices(runs)
    identity={'project':meta['project'],'base_sha':meta['base_sha'],
              'children':[(c['run_id'],c['contract_hash'],c['reviewed_fingerprint']) for c in meta['children']]}
    batch_id=digest(identity)[:16]
    root=Path(state_dir).resolve()/'batches'/batch_id
    worktree=root/'worktree';manifest=root/'composition.json'
    branch='codex/factory-batch-'+batch_id
    if manifest.exists():
        saved=json.loads(manifest.read_text())
        if saved.get('identity')!=identity or not worktree.is_dir():
            raise Stop('BLOCKED_RECONCILIATION','Saved batch composition identity/worktree mismatch')
        if fingerprint(worktree,meta['base_sha'])!=saved.get('combined_fingerprint'):
            raise Stop('BLOCKED_RECONCILIATION','Saved batch worktree changed after composition')
        return saved
    if worktree.exists():
        raise Stop('BLOCKED_RECONCILIATION','Batch worktree exists without a completed composition receipt')
    root.mkdir(parents=True,exist_ok=True)
    create_worktree(meta['repository_path'],worktree,branch,meta['base_sha'])
    applied=[]
    for child in meta['children']:
        before=set(changed(worktree,meta['base_sha']))
        after=set(apply_delta(child['worktree'],worktree,meta['base_sha']))
        delta=sorted(after-before)
        if delta!=sorted(child['files']):
            raise Stop('BLOCKED_RECONCILIATION','Composed delta differs from reviewed slice files')
        applied.extend(delta)
    combined=changed(worktree,meta['base_sha'])
    if combined!=meta['expected_files'] or sorted(applied)!=meta['expected_files']:
        raise Stop('BLOCKED_RECONCILIATION','Combined batch file set differs from reviewed slices')
    result={'state':'COMPOSED_LOCAL','batch_id':batch_id,'identity':identity,
            'project':meta['project'],'base_sha':meta['base_sha'],'base_branch':meta['base_branch'],
            'branch':branch,'worktree':str(worktree),'children':meta['children'],
            'combined_files':combined,'combined_fingerprint':fingerprint(worktree,meta['base_sha']),
            'model_turns':0}
    atomic_json(manifest,result)
    return result
