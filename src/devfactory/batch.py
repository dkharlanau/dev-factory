"""Deterministic composition of already-reviewed slices; no model or remote writes."""
from __future__ import annotations
import json
import time
from contextlib import contextmanager
from pathlib import Path

from .policy import Stop, Usage, Selection, check_quota, choose_model
from .repository import apply_delta, changed, create_worktree, fingerprint, review_snapshot
from .runtime import Runtime
from .runner import SCHEMA, WORKER_RULES, failure_excerpt, redact, scopes_overlap
from .state import Store, atomic_json, digest


@contextmanager
def _worker(state_dir, operation, project, identity, **metadata):
    """Batch work shares the regular runner's lock, lease and pause/status store."""
    store=Store(state_dir)
    rid=None
    claimed=False
    try:
        store.acquire_lock()
        key=operation+':'+digest(identity)
        previous=store.existing(key)
        data={'operation':operation,'phase':operation,'task_id':key,**metadata}
        rid=previous['id'] if previous else store.create(project,key,data)
        store.claim(rid,recovering=previous is not None)
        claimed=True
        yield store,rid,data
    except BaseException as error:
        if claimed:
            current=store.get(rid)['data']
            current['reason']=redact(str(error))[:1200] if isinstance(error,Stop) else type(error).__name__
            store.save(rid,error.state if isinstance(error,Stop) else 'BLOCKED_RECONCILIATION',current)
        raise
    finally:
        if claimed: store.release(rid)
        store.close()


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
        contracts=d.get('task_contracts')
        if not contracts:
            single=d.get('task_contract')
            contracts=[single] if single else []
        if not contracts or any(not isinstance(c,dict) or set(c)!={'id','description','acceptance','paths'} for c in contracts):
            raise Stop('BLOCKED_BATCH','Reviewed slice lacks immutable model-facing task contracts')
        union=list(dict.fromkeys(p for c in contracts for p in c['paths']))
        if union!=scopes:
            raise Stop('BLOCKED_RECONCILIATION','Reviewed slice contracts no longer match saved task scope')
        children.append({'run_id':run['id'],'task_id':d['task_id'],'task_ids':d.get('task_ids') or [d['task_id']],
                         'contract_hash':d['contract_hash'],'task_contracts':contracts,
                         'reviewed_fingerprint':d['reviewed_fingerprint'],
                         'worktree':str(wt),'scopes':scopes,'files':actual,'risk':d.get('risk'),
                         'profile':d.get('profile'),'repairs':d.get('repairs',0),'escalations':d.get('escalations',0)})
    return {'project':project,'base_sha':base,'base_branch':base_branch,'repository_path':str(repo_path),
            'children':children,'expected_files':sorted(expected_files),'scopes':seen_scopes}


def compose_reviewed_slices(runs, state_dir):
    identity=sorted(run['id'] for run in runs)
    project=runs[0]['project'] if runs else 'unknown'
    with _worker(state_dir,'batch',project,identity,run_ids=identity) as (store,rid,data):
        result=_compose_reviewed_slices(runs,state_dir)
        result['run_id']=rid
        store.save(rid,result['state'],{**data,**result})
        return result


def _compose_reviewed_slices(runs, state_dir):
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
    with _worker(config['state_dir'],'batch-review',composition['project'],composition['batch_id'],
                 batch_id=composition['batch_id'],worktree=composition['worktree']) as (store,rid,data):
        def checkpoint(value):
            store.save(rid,value['state'],{**data,**value})
        result=_review_composed_batch(config,composition,runtime_factory=runtime_factory,
                                     run_id=rid,checkpoint=checkpoint,paused=lambda:store.paused(rid))
        checkpoint(result)
        return result


def _review_composed_batch(config, composition, *, runtime_factory, run_id, checkpoint, paused):
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
    saved=None
    if receipt.exists():
        saved=json.loads(receipt.read_text())
        if saved.get('composition_fingerprint')!=composition['combined_fingerprint']:
            raise Stop('BLOCKED_RECONCILIATION','Saved batch integration receipt belongs to another composition')
        if saved.get('gate_hash')!=gate_hash:
            raise Stop('BLOCKED_RECONCILIATION','Batch integration policy/check configuration changed')
        if fingerprint(wt,base)!=saved.get('composition_fingerprint'):
            raise Stop('BLOCKED_RECONCILIATION','Batch worktree changed after integration receipt')
        if saved.get('state') in ('BATCH_READY_LOCAL','BLOCKED_BATCH_VALIDATION','BLOCKED_BATCH_REVIEW'):
            return saved

    def save(value):
        value['run_id']=run_id
        atomic_json(receipt,value)
        checkpoint(value)

    def guard(deadline):
        if paused(): raise Stop('PAUSED','Owner requested batch pause')
        if time.time()>=deadline: raise Stop('PAUSED_DEADLINE','Batch foreground deadline reached')

    # Once dispatch may have happened, this command can only reconcile that attempt.
    # Missing telemetry or a lost acknowledgement never authorizes a second turn.
    if saved and saved.get('dispatch_started'):
        usage=Usage(saved.get('usage_threads'))
        result=saved.get('result')
        if result is None:
            tid=saved.get('thread_id')
            turn_id=saved.get('turn_id')
            if not tid or not turn_id:
                raise Stop('BLOCKED_RECONCILIATION','Batch review dispatch acknowledgement is unknown; inspect the preserved native thread')
            with runtime_factory(wt) as rt:
                selection=Selection(**saved['reviewer'])
                rt.start(saved['review_worktree'],selection,WORKER_RULES,resume=tid)
                thread=rt.rpc('thread/read',{'threadId':tid,'includeTurns':True})['thread']
                matches=[t for t in thread.get('turns',[]) if t.get('id')==turn_id]
                if thread.get('status',{}).get('type')=='active' or any(t.get('status')=='inProgress' for t in thread.get('turns',[])):
                    raise Stop('BLOCKED_RECONCILIATION','Batch review native turn is still active; no new dispatch allowed')
                if len(matches)!=1 or matches[0].get('status')!='completed':
                    raise Stop('BLOCKED_RECONCILIATION','Batch review did not complete with a recoverable verdict; no new dispatch allowed')
                messages=[i.get('text') for i in matches[0].get('items',[])
                          if i.get('type')=='agentMessage' and i.get('phase') in (None,'final_answer')]
                if not messages:
                    raise Stop('BLOCKED_RECONCILIATION','Completed batch review has no persisted final verdict')
                result={'status':'completed','final':messages[-1]}
                saved.update(result=result,usage_complete=False,recovered=True)
                save(saved)
        return _finish_review(saved,result,usage,wt,base,save)

    deadline=time.time()+config['budget']['deadline_seconds']
    final_receipts=[]
    with runtime_factory(wt) as rt:
        for name in names:
            guard(deadline)
            before=fingerprint(wt,base)
            result=rt.command(wt,checks[name],timeout=min(600,max(1,deadline-time.time())),should_pause=paused)
            row={'check':name,'exit_code':result.get('exitCode'),
                 'failure_excerpt':failure_excerpt(result)}
            final_receipts.append(row)
            if fingerprint(wt,base)!=before:
                raise Stop('BLOCKED_VALIDATION','Combined final validation changed source files')
            if result.get('exitCode')!=0:
                out={'state':'BLOCKED_BATCH_VALIDATION','batch_id':composition['batch_id'],
                     'composition_fingerprint':composition['combined_fingerprint'],'gate_hash':gate_hash,
                     'final_checks':final_receipts,'review':None,'model_turns':0}
                save(out)
                return out

        budget=config['budget']
        guard(deadline)
        quota=rt.quota();check_quota(quota,budget)
        children=composition['children']
        deep=any(c.get('profile')=='deep' or c.get('risk')=='high' or
                 c.get('repairs',0)>0 or c.get('escalations',0)>0 for c in children)
        profile='deep' if deep else 'review'
        selection=choose_model(profile,config,rt.catalog,rt.native,high_risk=deep)
        attempts=sorted(root.glob('integration-review-*'))
        review_dir=root/f'integration-review-{len(attempts)+1}'
        review_snapshot(wt,review_dir,base)
        review_fingerprint=fingerprint(review_dir,base)
        instructions=WORKER_RULES+(
            '\nRole: independently review the combined diff against every supplied task acceptance. '
            'Do not edit. Use the supplied final-check evidence; rerun a passing check only for a '
            'specific unresolved concern. Report concrete file/line findings.\n')
        usage=Usage()
        packet={'role':'review','batch':composition['batch_id'],'base_sha':base,
                'tasks':[contract for c in children for contract in c['task_contracts']],
                'combined_files':composition['combined_files'],
                'final_checks':final_receipts,'diff_command':['git','diff',base]}
        raw=json.dumps(packet,separators=(',',':'),ensure_ascii=False)
        pending={'state':'BATCH_REVIEW_PENDING','batch_id':composition['batch_id'],
                 'composition_fingerprint':composition['combined_fingerprint'],'gate_hash':gate_hash,
                 'final_checks':final_receipts,'review':None,'reviewer':selection.dict(),
                 'review_worktree':str(review_dir),'review_fingerprint':review_fingerprint,
                 'usage_threads':{},'usage':usage.aggregate(),'usage_complete':False,
                 'model_turns':0,'dispatch_attempts':0,'packet_utf8_bytes':len(raw.encode())}
        save(pending)
        guard(deadline)
        tid=rt.start(review_dir,selection,instructions,read_only=False,resume=None)
        pending.update(thread_id=tid,dispatch_started=True,dispatch_attempts=1,model_turns=None)
        save(pending)
        def started(thread_id,turn_id):
            pending.update(state='BATCH_REVIEW_RUNNING',thread_id=thread_id,turn_id=turn_id,model_turns=1)
            save(pending)
        def event(method,payload):
            if method=='thread/tokenUsage/updated':
                usage.observe(payload['threadId'],payload['tokenUsage'])
                pending.update(usage_threads=usage.totals,usage=usage.aggregate())
                save(pending)
        try:
            guard(deadline)
            result=rt.turn(tid,raw,selection,deadline=deadline,on_event=event,should_pause=paused,
                           on_start=started,output_schema=SCHEMA,external=True)
        except BaseException as error:
            pending.update(state='BLOCKED_RECONCILIATION',failure=type(error).__name__)
            save(pending)
            raise
        if result.get('usage'): usage.observe(tid,result['usage'])
        pending.update(result={k:result.get(k) for k in ('status','final','stop_state')},
                       usage_threads=usage.totals,usage=usage.aggregate(),usage_complete=bool(result.get('usage')))
        save(pending)
        return _finish_review(pending,result,usage,wt,base,save)


def _finish_review(pending,result,usage,wt,base,save):
    if result['status']!='completed':
        pending['state']=result.get('stop_state') or 'BLOCKED_RUNTIME'
        save(pending)
        raise Stop(pending['state'],'Batch integration review turn did not complete; attempt preserved')
    try: verdict=json.loads(result.get('final') or '')
    except ValueError: raise Stop('BLOCKED_RESULT','Batch reviewer did not return structured verdict')
    if not isinstance(verdict,dict) or verdict.get('verdict') not in ('PASS','REPAIR','BLOCKED') or not isinstance(verdict.get('findings'),list):
        raise Stop('BLOCKED_RESULT','Invalid batch reviewer verdict')
    if fingerprint(pending['review_worktree'],base)!=pending['review_fingerprint']:
        raise Stop('BLOCKED_REVIEW','Batch reviewer modified its isolated snapshot')
    if fingerprint(wt,base)!=pending['composition_fingerprint']:
        raise Stop('BLOCKED_RECONCILIATION','Composed batch changed during integration review')
    passed=verdict['verdict']=='PASS' and not verdict['findings']
    pending.update(state='BATCH_READY_LOCAL' if passed else 'BLOCKED_BATCH_REVIEW',review=verdict['verdict'],
                   review_summary=redact(str(verdict.get('summary','')))[:1200],
                   findings=verdict['findings'],usage=usage.aggregate())
    save(pending)
    return pending



def load_composition(state_dir, batch_id):
    if not isinstance(batch_id,str) or len(batch_id)!=16 or any(c not in '0123456789abcdef' for c in batch_id):
        raise Stop('BLOCKED_BATCH','Invalid batch id')
    path=Path(state_dir).resolve()/'batches'/batch_id/'composition.json'
    if not path.is_file():
        raise Stop('NOT_FOUND','Batch composition receipt not found')
    value=json.loads(path.read_text())
    if value.get('batch_id')!=batch_id or value.get('state')!='COMPOSED_LOCAL':
        raise Stop('BLOCKED_RECONCILIATION','Invalid batch composition receipt')
    return value
