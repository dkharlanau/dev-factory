"""Deterministic composition of already-reviewed slices; no model or remote writes."""
from __future__ import annotations
import json
import time
from pathlib import Path

from .policy import Stop, Usage, check_quota, choose_model, scopes_overlap
from .repository import apply_delta, changed, create_worktree, fingerprint, review_snapshot
from .runtime import Runtime
from .runner import SCHEMA, WORKER_RULES, failure_excerpt, redact
from .state import atomic_json, digest


def _inside(path, scopes):
    return any(path==s or path.startswith(s.rstrip('/')+'/') for s in scopes)


def validate_reviewed_slices(runs):
    if len(runs) < 2:
        raise Stop('BLOCKED_BATCH','Batch composition requires at least two reviewed slices')
    ordered=sorted(runs,key=lambda r:r['id'])
    for run in ordered:
        d=run['data']
        if run['state']!='READY_LOCAL' or d.get('acceptance') is not True or d.get('review')!='PASS':
            raise Stop('BLOCKED_BATCH','Every batch slice must be READY_LOCAL with passed acceptance/review')
    projects={r['data'].get('project') for r in ordered}
    bases={r['data'].get('base_sha') for r in ordered}
    branches={r['data'].get('base_branch') for r in ordered}
    repositories={str(Path(r['data']['repository']['path']).resolve()) for r in ordered}
    if len(projects)!=1 or len(bases)!=1 or len(branches)!=1:
        raise Stop('BLOCKED_BATCH','Batch slices must share project, base SHA and base branch')
    if len(repositories)!=1:
        raise Stop('BLOCKED_BATCH','Batch slices must share the exact repository checkout')
    project=next(iter(projects));base=next(iter(bases));base_branch=next(iter(branches))
    repo_path=Path(next(iter(repositories)))
    seen_scopes=[];expected_files=[];children=[]
    for run in ordered:
        d=run['data']
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
        contract=d.get('task_contract')
        if not isinstance(contract,dict) or set(contract)!={'id','description','acceptance','paths'}:
            raise Stop('BLOCKED_BATCH','Reviewed slice lacks the immutable model-facing task contract')
        if contract.get('id')!=d.get('task_id') or contract.get('paths')!=scopes:
            raise Stop('BLOCKED_RECONCILIATION','Reviewed slice contract no longer matches saved task scope')
        children.append({'run_id':run['id'],'task_id':d['task_id'],'contract_hash':d['contract_hash'],
                         'task_contract':contract,'reviewed_fingerprint':d['reviewed_fingerprint'],
                         'worktree':str(wt),'scopes':scopes,'files':actual,'risk':d.get('risk'),
                         'profile':d.get('profile'),'repairs':d.get('repairs',0),'escalations':d.get('escalations',0)})
    return {'project':project,'base_sha':base,'base_branch':base_branch,'repository_path':str(repo_path),
            'children':children,'expected_files':sorted(expected_files),'scopes':seen_scopes}


def compose_reviewed_slices(runs, state_dir):
    meta=validate_reviewed_slices(runs)
    identity={'project':meta['project'],'base_sha':meta['base_sha'],
              'children':[[c['run_id'],c['contract_hash'],c['reviewed_fingerprint']] for c in meta['children']]}
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



def review_composed_batch(config, composition, *, runtime_factory=Runtime):
    """Run combined final checks and one fresh interaction review. No remote writes."""
    if composition.get('state')!='COMPOSED_LOCAL':
        raise Stop('BLOCKED_BATCH','Integration review requires a completed local composition')
    project=composition['project']
    if project not in config['projects']:
        raise Stop('BLOCKED_BATCH','Batch project is not configured')
    adapter=config['projects'][project]
    wt=Path(composition['worktree'])
    base=composition['base_sha']
    if not wt.is_dir() or fingerprint(wt,base)!=composition['combined_fingerprint']:
        raise Stop('BLOCKED_RECONCILIATION','Composed batch worktree changed before integration review')
    root=Path(config['state_dir']).resolve()/'batches'/composition['batch_id']
    receipt=root/'integration.json'
    names=list(dict.fromkeys(adapter.get('final_checks',[])))
    checks=adapter.get('checks',{})
    if not names or any(name not in checks for name in names):
        raise Stop('BLOCKED_POLICY','Batch integration requires configured final checks')
    gate_hash=digest({'policy_version':config.get('policy_version'),
                      'profiles':config.get('profiles'),
                      'final_checks':[(name,checks[name]) for name in names]})
    if receipt.exists():
        saved=json.loads(receipt.read_text())
        if saved.get('composition_fingerprint')!=composition['combined_fingerprint']:
            raise Stop('BLOCKED_RECONCILIATION','Saved batch integration receipt belongs to another composition')
        if saved.get('gate_hash')!=gate_hash:
            raise Stop('BLOCKED_RECONCILIATION','Batch integration policy/check configuration changed')
        if fingerprint(wt,base)!=saved.get('composition_fingerprint'):
            raise Stop('BLOCKED_RECONCILIATION','Batch worktree changed after integration receipt')
        return saved

    deadline=time.time()+config['budget']['deadline_seconds']
    final_receipts=[]
    with runtime_factory(wt) as rt:
        for name in names:
            before=fingerprint(wt,base)
            result=rt.command(wt,checks[name],timeout=min(600,max(1,deadline-time.time())))
            row={'check':name,'exit_code':result.get('exitCode'),
                 'failure_excerpt':failure_excerpt(result)}
            final_receipts.append(row)
            if fingerprint(wt,base)!=before:
                raise Stop('BLOCKED_VALIDATION','Combined final validation changed source files')
            if result.get('exitCode')!=0:
                out={'state':'BLOCKED_BATCH_VALIDATION','batch_id':composition['batch_id'],
                     'composition_fingerprint':composition['combined_fingerprint'],'gate_hash':gate_hash,
                     'final_checks':final_receipts,'review':None,'model_turns':0}
                atomic_json(receipt,out)
                return out

        budget=config['budget']
        quota=rt.quota();check_quota(quota,budget)
        children=composition['children']
        deep=any(c.get('profile')=='deep' or c.get('risk')=='high' or
                 c.get('repairs',0)>0 or c.get('escalations',0)>0 for c in children)
        profile='deep' if deep else 'review'
        selection=choose_model(profile,config,rt.catalog,rt.native,high_risk=deep)
        attempts=sorted(root.glob('integration-review-*'))
        review_dir=root/f'integration-review-{len(attempts)+1}'
        before_review=fingerprint(wt,base)
        review_snapshot(wt,review_dir,base)
        review_fingerprint=fingerprint(review_dir,base)
        instructions=WORKER_RULES+(
            '\nRole: independently review the combined diff against every supplied task acceptance. '
            'Do not edit. Use the supplied final-check evidence; rerun a passing check only for a '
            'specific unresolved concern. Report concrete file/line findings.\n')
        tid=rt.start(review_dir,selection,instructions,read_only=False,resume=None)
        usage=Usage()
        packet={'role':'review','batch':composition['batch_id'],'base_sha':base,
                'tasks':[c['task_contract'] for c in children],
                'combined_files':composition['combined_files'],
                'final_checks':final_receipts,'diff_command':['git','diff',base]}
        raw=json.dumps(packet,separators=(',',':'),ensure_ascii=False)
        def event(method,payload):
            if method=='thread/tokenUsage/updated':
                usage.observe(payload['threadId'],payload['tokenUsage'])
        result=rt.turn(tid,raw,selection,deadline=deadline,on_event=event,
                       on_start=lambda *_: None,output_schema=SCHEMA,external=True)
        if result.get('usage'): usage.observe(tid,result['usage'])
        if result['status']!='completed':
            raise Stop('BLOCKED_RUNTIME','Batch integration review turn did not complete')
        try: verdict=json.loads(result.get('final') or '')
        except ValueError: raise Stop('BLOCKED_RESULT','Batch reviewer did not return structured verdict')
        if not isinstance(verdict,dict) or verdict.get('verdict') not in ('PASS','REPAIR','BLOCKED'):
            raise Stop('BLOCKED_RESULT','Invalid batch reviewer verdict')
        if fingerprint(review_dir,base)!=review_fingerprint:
            raise Stop('BLOCKED_REVIEW','Batch reviewer modified its isolated snapshot')
        if fingerprint(wt,base)!=before_review:
            raise Stop('BLOCKED_RECONCILIATION','Composed batch changed during integration review')
        passed=verdict['verdict']=='PASS' and not verdict.get('findings')
        out={'state':'BATCH_READY_LOCAL' if passed else 'BLOCKED_BATCH_REVIEW',
             'batch_id':composition['batch_id'],'composition_fingerprint':composition['combined_fingerprint'],
             'gate_hash':gate_hash,
             'final_checks':final_receipts,'review':verdict['verdict'],
             'review_summary':redact(str(verdict.get('summary','')))[:1200],
             'findings':verdict.get('findings',[]),'reviewer':selection.dict(),
             'usage':usage.aggregate(),'model_turns':1,'packet_utf8_bytes':len(raw.encode())}
        atomic_json(receipt,out)
        return out
