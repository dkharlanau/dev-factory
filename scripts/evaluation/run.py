#!/usr/bin/env python3
"""Explicit, sequential experiments. No product repository or upstream remote writes."""
from __future__ import annotations
import argparse
import copy
import hashlib
import io
import json
import re
import subprocess
import sys
import tarfile
import time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'src'))
from devfactory.config import load
from devfactory.policy import Usage, Stop, choose_model, check_budget, check_quota
from devfactory.repository import git, command, fingerprint, changed, review_snapshot
from devfactory.runner import Runner, WORKER_RULES, SCHEMA
from devfactory.runtime import Runtime
from devfactory.state import atomic_json, digest
from devfactory.tasks import resolve

AREA=ROOT/'.factory/evaluation'
CASES=json.loads(Path(__file__).with_name('cases.json').read_text())
PYTHON=str(ROOT/'.venv/bin/python')
CHECK=[PYTHON,'-m','unittest','discover','-s','tests']


def prepare(case):
    upstream=AREA/'upstream'
    if not upstream.exists():
        command(['git','clone','--quiet','--no-tags','https://github.com/more-itertools/more-itertools.git',str(upstream)],timeout=120)
    path=AREA/'sources'/case['id']
    if not path.exists():
        path.mkdir(parents=True)
        raw=subprocess.check_output(['git','-C',str(upstream),'archive',case['base']])
        with tarfile.open(fileobj=io.BytesIO(raw)) as archive: archive.extractall(path,filter='data')
        task={k:case[k] for k in ('id','category','description','acceptance','complexity')}
        task.update(risk='low',verification='strong',paths=['more_itertools','tests','docs','README.rst'],checks=['suite'],state='EXECUTE')
        (path/'EVALUATION_TASK.md').write_text('Local evaluation copy; do not contact upstream.\n\n```factory-task\n'+json.dumps(task,indent=2)+'\n```\n\nValidation: '+ ' '.join(CHECK)+'\n')
        # All original source and license files stay identical. Remove no historical tests.
        git(path,'init','-q','-b','main')
        git(path,'config','user.name','DevFactory Evaluation')
        git(path,'config','user.email','evaluation@localhost')
        git(path,'add','.')
        git(path,'commit','-qm','Frozen evaluation source and common task contract')
        atomic_json(AREA/'sources'/f'{case["id"]}.json',{'upstream_sha':git(upstream,'rev-parse',case['base']),'snapshot_sha':git(path,'rev-parse','HEAD'),'case_hash':digest(case)})
    meta=json.loads((AREA/'sources'/f'{case["id"]}.json').read_text())
    if meta['case_hash']!=digest(case): raise RuntimeError('Frozen case changed; use a separate experiment directory')
    cfg=load(ROOT)
    cfg['state_dir']=str(AREA/'state'/case['id'])
    cfg['projects']={case['id']:{'fixture':True,'path':str(path),'base_sha':meta['snapshot_sha'],
        'instructions':[],'backlogs':['EVALUATION_TASK.md'],'checks':{'suite':CHECK},'final_checks':['suite'],
        'high_risk_paths':[],'boundary':'Local upstream snapshot. No upstream contact or access to other evaluation variants.'}}
    return cfg,meta


def context_metrics(rt, tid):
    """Read only this experiment's public items, discard text; persist counts/hashes."""
    state=rt.rpc('thread/read',{'threadId':tid,'includeTurns':True})['thread']
    cmds=[]; reads=[]; output_chars=0; compactions=0
    for turn in state.get('turns',[]):
        for item in turn.get('items',[]):
            if item.get('type')=='contextCompaction': compactions+=1
            if item.get('type')!='commandExecution': continue
            c=item.get('command','')
            cmds.append(c)
            output_chars+=len(item.get('aggregatedOutput') or '')
            if re.search(r'\b(cat|sed|rg|head|tail|git show)\b',c): reads.append(hashlib.sha256(c.encode()).hexdigest())
    return {'command_count':len(cmds),'read_like_command_count':len(reads),
            'repeated_exact_read_commands':len(reads)-len(set(reads)),
            'command_output_characters':output_chars,'persisted_compactions':compactions,
            'test_like_command_count':sum(bool(re.search(r'(-m unittest|pytest|doctest)',c)) for c in cmds),
            'reference_oracle_path_mentions':sum(bool(re.search(r'evaluation/(upstream|references)|evaluation/oracle',c)) for c in cmds),
            'repeated_file_reads':'unknown: shell syntax and command hashes cannot prove file-level reads'}


class MeasuredRuntime(Runtime):
    measurements=[]
    def start(self,cwd,selection,instructions,**kw):
        t=time.monotonic()
        tid=super().start(cwd,selection,instructions,**kw)
        self.measurements.append({'thread_id':tid,'thread_setup_seconds':time.monotonic()-t,
            'instruction_utf8_bytes':len(instructions.encode()),'resume':bool(kw.get('resume'))})
        return tid
    def turn(self,tid,text,selection,**kw):
        t=time.monotonic(); first=[]; callback=kw.get('on_event',lambda *_:None)
        def event(m,p):
            if m=='thread/tokenUsage/updated' and not first: first.append(p['tokenUsage'])
            callback(m,p)
        kw['on_event']=event
        result=super().turn(tid,text,selection,**kw)
        metric={'thread_id':tid,'turn_id':result['turn_id'],'turn_seconds':time.monotonic()-t,
                'packet_utf8_bytes':len(text.encode()),'first_usage_event':first[0] if first else None,
                **context_metrics(self,tid)}
        self.measurements.append(metric)
        return result


def assess(wt,base,case,rt,label):
    destination=AREA/'assessments'/label
    review_snapshot(wt,destination,base)
    t=time.monotonic()
    suite=rt.command(destination,CHECK,timeout=180)
    oracle=rt.command(destination,[PYTHON,'-c','import sys,runpy;sys.path.insert(0,".");sys.argv=["oracle",'+repr(case['id'])+'];runpy.run_path('+repr(str(Path(__file__).with_name('oracle.py')))+',run_name="__main__")'],timeout=90)
    # Store complete deterministic test output locally, not model transcripts.
    for name,result in [('suite',suite),('oracle',oracle)]:
        (destination/f'{name}.log').write_text(result.get('stdout','')+'\n'+result.get('stderr',''))
    tests=re.search(r'Ran (\d+) tests?',suite.get('stderr','')+suite.get('stdout',''))
    return {'suite_exit':suite.get('exitCode'),'oracle_exit':oracle.get('exitCode'),
        'test_count':int(tests[1]) if tests else None,'seconds':time.monotonic()-t,
        'quality':'PASS' if suite.get('exitCode')==oracle.get('exitCode')==0 else 'FAIL',
        'regressions':'none detected' if suite.get('exitCode')==0 else 'see local suite.log',
        'logs':str(destination)}


def native(case,cfg,meta):
    path=AREA/'native'/case['id']
    if path.exists(): raise RuntimeError('Native checkout exists without a final receipt; reconcile before redispatch')
    command(['git','clone','--quiet','--no-hardlinks',cfg['projects'][case['id']]['path'],str(path)])
    plan=resolve(cfg,case['id']); usage=Usage();turns=[]; started=time.monotonic()
    deadline=time.time()+cfg['budget']['deadline_seconds']
    payload=json.dumps({'task':{k:v for k,v in plan['task'].items() if k!='source'},'validation_commands':[CHECK]})
    outcome='UNKNOWN';checks=[]
    with MeasuredRuntime(path) as rt:
        selection=choose_model(plan['profile'],cfg,rt.catalog,rt.native,baseline=True)
        print('Native child: native model/effort defaults',rt.native,flush=True)
        tid=rt.start(path,selection,WORKER_RULES.replace('DevFactory runs one bounded local task.','Run one local development task.')+'\nImplement the complete task, run the supplied validation and self-review the diff. Do not commit.\n')
        for attempt in range(3):
            try:
                check_budget(cfg['budget'],deadline=deadline,turns=len(turns),tokens=usage.aggregate()['totalTokens'])
                check_quota(rt.quota(),cfg['budget'])
            except Stop as stop:
                outcome=stop.state
                break
            result=rt.turn(tid,payload,selection,deadline=deadline,output_schema=SCHEMA)
            if result.get('usage'): usage.observe(tid,result['usage'])
            turns.append({k:result.get(k) for k in ('thread_id','turn_id','status','usage','effective_model','resolved_model','commands','compactions')})
            turns[-1].update(requested_model=None,requested_effort=None,role='build' if attempt==0 else 'repair')
            validation=rt.command(path,CHECK,timeout=180);checks.append({'exit_code':validation.get('exitCode')})
            if result['status']!='completed': outcome='BLOCKED_RUNTIME';break
            if validation.get('exitCode')==0: outcome='COMPLETE_SELF_REVIEWED';break
            payload='The configured test suite failed. Diagnose and repair within original task scope, preserving tests.\n'+validation.get('stdout','')[-8000:]+validation.get('stderr','')[-8000:]
        seconds=time.monotonic()-started
        evaluation=assess(path,meta['snapshot_sha'],case,rt,case['id']+'-native')
    return {'state':outcome,'turns':turns,'usage':usage.aggregate(),'workflow_seconds':seconds,'worktree':str(path),
        'repairs':len(turns)-1,'checks':checks,'independent_review':'not part of direct workflow; common external behavioral assessment follows',
        'assessment':evaluation,'human_interventions':0}


def factory(case,cfg,meta):
    started=time.monotonic(); runner=Runner(cfg,runtime_factory=MeasuredRuntime)
    try:
        run=runner.run(case['id'])[0]
        if run.get('state')=='EXISTING_COMPLETION':run=runner.store.get(run['run_id'])
        d=run.get('data',{})
        repeat=runner.run(case['id'])[0]
    finally:runner.close()
    seconds=time.monotonic()-started
    with Runtime(d['worktree']) as rt:
        evaluation=assess(Path(d['worktree']),meta['snapshot_sha'],case,rt,case['id']+'-factory')
    return {'state':run['state'],'turns':d['turns'],'usage':d['usage'],'workflow_seconds':seconds,'worktree':d['worktree'],
        'repairs':d['repairs'],'checks':[{'exit_code':t['exit_code']} for t in d['tests']],
        'independent_review':d.get('review'),'review_findings':d.get('findings',[]),'review_summary':d.get('review_summary'),
        'repeat':repeat,'receipt_id':run['id'],'assessment':evaluation,'human_interventions':0,
        'reason':d.get('reason'),'phase':d.get('phase')}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--live',action='store_true')
    parser.add_argument('--case',choices=[c['id'] for c in CASES]);parser.add_argument('--variant',choices=['native','factory'])
    args=parser.parse_args()
    selected=[c for c in CASES if not args.case or c['id']==args.case]
    for case in selected:
        cfg,meta=prepare(case)
        if not args.live:
            print(case['id'],meta,flush=True);continue
        if not args.variant:parser.error('--live requires --variant (one foreground run)')
        receipt=AREA/'results'/f'{case["id"]}-{args.variant}.json'
        if receipt.exists(): print('EXISTING_EVALUATION',receipt,flush=True);continue
        MeasuredRuntime.measurements=[]
        print('START',case['id'],args.variant,meta,flush=True)
        result=(native if args.variant=='native' else factory)(case,cfg,meta)
        wt=Path(result['worktree'])
        result.update(case=case['id'],category=case['category'],variant=args.variant,meta=meta,
            runtime='0.157.1',factory_revision=git(ROOT,'rev-parse','HEAD'),
            measurement=MeasuredRuntime.measurements,changed_files=changed(wt,meta['snapshot_sha']),
            diff_numstat=git(wt,'diff','--numstat',meta['snapshot_sha']),
            fingerprint=fingerprint(wt,meta['snapshot_sha']),model_turns=len(result['turns']),
            context_occupation='unknown',initial_context_tokens='unknown',cost_currency='unknown',
            parent_chat_usage='unknown',natural_compaction_events=sum(len(t.get('compactions') or []) for t in result['turns']))
        atomic_json(receipt,result)
        print('RESULT',json.dumps({k:result[k] for k in ['case','variant','state','workflow_seconds','usage','assessment','model_turns']}),flush=True)

if __name__=='__main__':main()
