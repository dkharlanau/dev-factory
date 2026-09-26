#!/usr/bin/env python3
"""Export portable observations, keeping raw receipts and failed assessments intact."""
import json
import hashlib
from pathlib import Path
from run import ROOT,AREA,CASES,git,atomic_json


def portable(value):
    if isinstance(value,str):return value.replace(str(ROOT),'<DEVFACTORY_ROOT>')
    if isinstance(value,list):return [portable(v) for v in value]
    if isinstance(value,dict):return {k:portable(v) for k,v in value.items()}
    return value


def diff_size(d):
    wt=Path(d['worktree']);added=deleted=0;binary=[]
    for line in git(wt,'diff','--numstat',d['meta']['snapshot_sha']).splitlines():
        a,b,path=line.split('\t',2)
        if a=='-' or b=='-':binary.append(path)
        else:added+=int(a);deleted+=int(b)
    untracked=git(wt,'ls-files','--others','--exclude-standard').splitlines()
    return {'tracked_added_lines':added,'tracked_deleted_lines':deleted,'binary_files':binary,
        'untracked_files':untracked,'untracked_bytes':sum((wt/p).stat().st_size for p in untracked),
        'untracked_lines':sum(len((wt/p).read_bytes().splitlines()) for p in untracked)}


def main():
    results=[];raw={}
    for case in CASES:
        for variant in ('native','factory'):
            p=AREA/'results'/f'{case["id"]}-{variant}.json'
            if not p.exists():continue
            d=json.loads(p.read_text());raw[p.name]=hashlib.sha256(p.read_bytes()).hexdigest()
            correction=AREA/'results'/f'{case["id"]}-{variant}-reassessment.json'
            if correction.exists():
                d['original_assessment']=d['assessment']
                d['assessment']=json.loads(correction.read_text())['assessment']
                d['assessment_amended']=True
                raw[correction.name]=hashlib.sha256(correction.read_bytes()).hexdigest()
            tokens=d['usage']; turns=d['turns']
            d['uncached_input_tokens']=tokens['inputTokens']-tokens['cachedInputTokens'] if all(tokens.get(k) is not None for k in ('inputTokens','cachedInputTokens')) else None
            d['workflow_complete']=d['state'] in ('READY_LOCAL','COMPLETE_SELF_REVIEWED')
            d['diff_size']=diff_size(d)
            d['tool_commands_with_nonzero_exit']=sum(c.get('exit_code') not in (0,None) for t in turns for c in (t.get('commands') or []))
            d['internal_model_retries']='unknown'
            d['model_turn_seconds']=sum(m['turn_seconds'] for m in d['measurement'] if 'turn_seconds' in m)
            d['model_turn_timing_includes_observer_readback']=False
            d['repository_read_bytes']='unknown'
            d['final_quality_scope']='Full original+added tests and held-out behavioral checks; not upstream acceptance, docs build or type-check proof'
            results.append(d)
    for case in CASES:
        paired=[r for r in results if r['case']==case['id']]
        if len(paired)==2:
            assert paired[0]['meta']==paired[1]['meta'], 'Paired starting state/contract mismatch'
    experiments={}
    for key,path in {'pr_lifecycle':AREA/'pr-lifecycle/result.json','recovery':AREA/'recovery/result.json',
                     'oracle_amendment':AREA/'oracle-amendment.json','expired_compaction_before':AREA/'expired-compaction-before.json',
                     'oracle_references':AREA/'oracle-reference.json','oracle_sensitivity':AREA/'oracle-sensitivity.json','thread_observations':AREA/'thread-observations.json',
                     'unconsumed_queue_before':AREA/'unconsumed-queue-before.json'}.items():
        if path.exists():experiments[key]=json.loads(path.read_text())
    for label in ('before','after'):
        p=AREA/f'doctor-{label}.json'
        if p.exists():
            d=json.loads(p.read_text())
            experiments['doctor_'+label]={k:d.get(k) for k in ('versions','native','auth_mode','model_turns')}
    out={'schema_version':1,'date':'2026-09-26','primary_target_revision':'60876067bfc69f7b085d7dd126d101d6032fcef2',
         'primary_runs_observed':len(results),'primary_pairs_planned':5,'replicates_per_cell':1,
         'primary_budget':{'soft_tokens':150000,'external_model_turns':6,'deadline_seconds':1800,'reserve_percent':10},
         'native_configured_defaults':{'model':'gpt-6-astra','effort':'xhigh'},
         'runtime_version':'0.157.1','effective_model_observability':'unknown absent actual serving/reroute telemetry',
         'cost_efficiency':'unknown','general_savings_claim':None,'parent_chat_usage':'unknown',
         'source':'https://github.com/more-itertools/more-itertools','results':results,
         'experiments':experiments,'raw_receipt_sha256':raw}
    atomic_json(ROOT/'docs/benchmarks/results.json',portable(out))
    for c in CASES:
        rows=[r for r in results if r['case']==c['id']]
        print(c['id'],[(r['variant'],r['state'],round(r['workflow_seconds'],1),r['usage']['totalTokens'],r['assessment']['quality']) for r in rows])

if __name__=='__main__':main()
