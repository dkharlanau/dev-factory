#!/usr/bin/env python3
"""Export one namespaced evaluation without mutating historical benchmark results."""
import argparse
import hashlib
import json
from pathlib import Path
from run import ROOT,AREA,CASES,git,atomic_json,experiment_slug,experiment_area


def portable(value):
    if isinstance(value,str): return value.replace(str(ROOT),'<DEVFACTORY_ROOT>')
    if isinstance(value,list): return [portable(v) for v in value]
    if isinstance(value,dict): return {k:portable(v) for k,v in value.items()}
    return value


def diff_size(d):
    wt=Path(d['worktree']);added=deleted=0;binary=[]
    for line in git(wt,'diff','--numstat',d['meta']['snapshot_sha']).splitlines():
        a,b,path=line.split('\t',2)
        if a=='-' or b=='-': binary.append(path)
        else: added+=int(a);deleted+=int(b)
    untracked=git(wt,'ls-files','--others','--exclude-standard').splitlines()
    return {'tracked_added_lines':added,'tracked_deleted_lines':deleted,'binary_files':binary,
            'untracked_files':untracked,'untracked_bytes':sum((wt/p).stat().st_size for p in untracked),
            'untracked_lines':sum(len((wt/p).read_bytes().splitlines()) for p in untracked)}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--experiment',required=True,type=experiment_slug)
    args=parser.parse_args()
    root=experiment_area(args.experiment); results=[]; raw={}
    for case in CASES:
        for variant in ('native','factory'):
            p=root/'results'/f'{case["id"]}-{variant}.json'
            if not p.exists(): continue
            d=json.loads(p.read_text());raw[p.name]=hashlib.sha256(p.read_bytes()).hexdigest()
            if d.get('experiment')!=args.experiment:
                raise RuntimeError('Receipt experiment namespace mismatch')
            tokens=d['usage'];turns=d['turns']
            d['uncached_input_tokens']=(tokens['inputTokens']-tokens['cachedInputTokens']
                if all(tokens.get(k) is not None for k in ('inputTokens','cachedInputTokens')) else None)
            d['workflow_complete']=d['state'] in ('READY_LOCAL','COMPLETE_SELF_REVIEWED')
            d['diff_size']=diff_size(d)
            d['tool_commands_with_nonzero_exit']=sum(c.get('exit_code') not in (0,None)
                for t in turns for c in (t.get('commands') or []))
            d['model_turn_seconds']=sum(m['turn_seconds'] for m in d['measurement'] if 'turn_seconds' in m)
            d['internal_model_retries']='unknown'
            d['repository_read_bytes']='unknown'
            d['final_quality_scope']='Full original+added tests and held-out behavioral checks; not upstream acceptance, docs build or type-check proof'
            results.append(d)
    for case in CASES:
        paired=[r for r in results if r['case']==case['id']]
        if len(paired)==2:
            assert paired[0]['meta']==paired[1]['meta'],'Paired starting state/contract mismatch'
    out={'schema_version':2,'experiment':args.experiment,'runs_observed':len(results),
         'pairs_planned':len(CASES),'replicates_per_cell':1,
         'policy_versions':sorted({str(r.get('policy_version')) for r in results}),
         'factory_revisions':sorted({r['factory_revision'] for r in results}),
         'runtime_versions':sorted({r['runtime'] for r in results}),
         'effective_model_observability':'unknown absent actual serving/reroute telemetry',
         'cost_efficiency':'unknown','general_savings_claim':None,'parent_chat_usage':'unknown',
         'source':'https://github.com/more-itertools/more-itertools','results':results,
         'raw_receipt_sha256':raw}
    destination=ROOT/'docs/benchmarks'/f'{args.experiment}.json'
    atomic_json(destination,portable(out))
    print(destination)
    for case in CASES:
        rows=[r for r in results if r['case']==case['id']]
        print(case['id'],[(r['variant'],r['state'],round(r['workflow_seconds'],1),
              r['usage']['totalTokens'],r['assessment']['quality']) for r in rows])


if __name__=='__main__': main()
