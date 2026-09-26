"""Offline policy checks by default. A live comparison must be explicitly invoked."""
from __future__ import annotations
import copy
from pathlib import Path
from .policy import Usage
from .state import atomic_json


def benchmark(config,live=False):
    result={'mode':'live' if live else 'offline','sample_size':0,'real_codex':live,
            'efficiency_claim':None,'parent_chat_usage':'unmeasured',
            'comparison_scope':'model/effort routing inside Factory' if live else 'offline policy validation',
            'attribution':'Account-wide allowance changes cannot be attributed to a run',
            'interpretation':'No live savings claim; validate routing deterministically and use paired live evidence.'}
    if not live:
        # Synthetic cases verify methodology and routing. They do not estimate performance.
        from .policy import classify
        cases=[({'risk':'low','complexity':'low','verification':'strong'},'fast'),
               ({'risk':'low','complexity':'medium'},'standard'),
               ({'risk':'high','complexity':'low'},'deep'),
               ({'risk':'low','complexity':'high'},'deep')]
        checks=[]
        for task,expected in cases:
            actual,_=classify(task,[])
            checks.append({'case':task,'expected':expected,'actual':actual,'passed':actual==expected})
        u=Usage();u.observe('t',{'total':{'inputTokens':10,'cachedInputTokens':5,'outputTokens':3,'reasoningOutputTokens':2,'totalTokens':13}})
        u.observe('t',{'total':{'inputTokens':10,'cachedInputTokens':5,'outputTokens':3,'reasoningOutputTokens':2,'totalTokens':13}})
        checks.append({'case':'no duplicate or nested-category double count','passed':u.aggregate()['totalTokens']==13})
        result.update(offline_cases=checks,passed=all(x['passed'] for x in checks),model_turns=0)
    else:
        from .fixture import prepare
        from .runner import Runner
        from .repository import git
        cfg=prepare(config,'benchmark-source')
        adapter=cfg['projects']['benchmark-source']
        variants=[]
        # One immutable starting commit. Separate branches/worktrees/fresh threads;
        # neither variant is given the other's receipts, solution or thread history.
        for name,baseline in [('benchmark-native',True),('benchmark-factory',False)]:
            cfg['projects'][name]=copy.deepcopy(adapter)
            runner=Runner(cfg)
            try: runs=runner.run(name,max_tasks=1,baseline=baseline)
            finally: runner.close()
            run=runs[0]
            if run.get('state')=='EXISTING_COMPLETION':
                from .state import Store
                saved=Store(cfg['state_dir'])
                try: run=saved.get(run['run_id'])
                finally: saved.close()
            d=run.get('data',{})
            variants.append({'variant':'native-model-effort-in-factory' if baseline else 'routed-model-effort-in-factory','starting_commit':adapter['base_sha'],
                'task_category':d.get('task_category'),'state':run['state'],
                'requested_effective_models':[{k:t.get(k) for k in ('requested_model','effective_model','requested_effort','role')} for t in d.get('turns',[])],
                'acceptance':d.get('acceptance'),'retry_count':d.get('repairs'),
                'review_defects':len(d.get('findings',[])),'wall_seconds':d.get('wall_seconds'),
                'usage':d.get('usage'),'human_interventions':d.get('human_interventions'),
                'receipt_id':run.get('id')})
        result.update(variants=variants,sample_size=1,
                      interpretation='Both arms use Factory Runner; this compares model/effort routing, not harness overhead. Direct-native workflow evaluation: scripts/evaluation/run.py.')
    path=Path(config['state_dir'])/'evidence'/('benchmark-live.json' if live else 'benchmark-offline.json')
    atomic_json(path,result);result['report']=str(path)
    return result
