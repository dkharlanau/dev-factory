#!/usr/bin/env python3
"""Explicit private-fixture lifecycle; inject ambiguity after push and PR creation."""
import argparse
import json
import sys
import os
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'src'))
from devfactory.config import load
from devfactory.fixture import prepare
from devfactory.repository import git,GitHub,trigger_snapshot,command
from devfactory.runner import Runner
import devfactory.runner as runner_module
from devfactory.tasks import resolve
from devfactory.state import atomic_json,digest
from devfactory.policy import Stop

REPOSITORY=os.environ.get('DEVFACTORY_PRIVATE_FIXTURE_REPOSITORY', '')
AREA=ROOT/'.factory/evaluation/pr-lifecycle'


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--live',action='store_true');args=parser.parse_args()
    if not args.live:parser.error('--live is required for model turns and remote writes')
    if (AREA/'result.json').exists():
        print('EXISTING_EVALUATION',AREA/'result.json');return
    if not REPOSITORY:
        raise RuntimeError('Set DEVFACTORY_PRIVATE_FIXTURE_REPOSITORY to a dedicated private evaluation repository')
    cfg=load(ROOT);cfg['state_dir']=str(AREA)
    cfg=prepare(cfg,'pr-lifecycle');adapter=cfg['projects']['pr-lifecycle'];path=Path(adapter['path'])
    marker=AREA/'prepared.json'
    if not marker.exists():
        # Newly-created dedicated repo only. Never targets a product remote.
        assert GitHub(REPOSITORY,True).json('repo','view',REPOSITORY,'--json','isPrivate')['isPrivate']
        (path/'AGENTS.md').write_text('Worker: only change clamp.py; preserve tests; no worker remote actions.\nController: this dedicated private evaluation repository permits push and draft PR only, no merge or deploy.\n')
        git(path,'add','AGENTS.md');git(path,'commit','-qm','Authorize dedicated evaluation controller lifecycle')
        git(path,'remote','add','origin','https://github.com/'+REPOSITORY+'.git')
        git(path,'push','-u','origin','main')
        atomic_json(marker,{'base_sha':git(path,'rev-parse','HEAD')})
    adapter.update(repository=REPOSITORY,allow_gh=True,fixture=False)
    plan=resolve(cfg,'pr-lifecycle')
    triggers=trigger_snapshot(path)
    gh=GitHub(REPOSITORY,True)
    hooks=gh.json('api','repos/'+REPOSITORY+'/hooks')
    deployments=gh.json('api','repos/'+REPOSITORY+'/deployments')
    assert not hooks and not deployments and not triggers['files']
    adapter['integration_approvals']={plan['contract_hash']:{'trigger_hash':triggers['hash'],
        'authority_hash':digest(plan['authority']),'triggers_reviewed':True,'spend_reviewed':True,'owner_restrictions_reviewed':True}}
    cfg['integration'].update(push=True,pull_request=True)
    # Durable injection markers avoid injecting twice on script recovery.
    real_git=runner_module.git
    def ambiguous_push(path,*args,**kw):
        result=real_git(path,*args,**kw)
        if args and args[0]=='push' and not (AREA/'push-injected.json').exists():
            atomic_json(AREA/'push-injected.json',{'after_remote_push':True})
            raise Stop('INJECTED_AFTER_PUSH','Controlled controller failure after confirmed push before PR')
        return result
    runner_module.git=ambiguous_push
    real_pr=GitHub.ensure_pr
    def ambiguous_pr(self,*args,**kw):
        result=real_pr(self,*args,**kw)
        if not (AREA/'pr-injected.json').exists():
            atomic_json(AREA/'pr-injected.json',result)
            raise Stop('INJECTED_AFTER_PR','Controlled controller failure after confirmed PR before saved receipt')
        return result
    GitHub.ensure_pr=ambiguous_pr
    runner=Runner(cfg)
    stages=[]
    try:
        existing=runner.store.by_task('pr-lifecycle',plan['task']['id'])
        result=runner.resume(existing['id']) if existing else runner.run('pr-lifecycle')[0]
        stages.append({'state':result['state'],'turns':len(result.get('data',{}).get('turns',[]))})
        for _ in range(2):
            if result['state'] not in ('INJECTED_AFTER_PUSH','INJECTED_AFTER_PR'):break
            result=runner.resume(result['id'])
            stages.append({'state':result['state'],'turns':len(result.get('data',{}).get('turns',[]))})
        repeat=runner.run('pr-lifecycle')[0]
        d=result.get('data',{})
        summary={'stages':stages,'state':result['state'],'run_id':result.get('id'),
            'repeat':repeat,'pr':d.get('pr'),'head_sha':d.get('head_sha'),'reviewed_sha':d.get('reviewed_sha'),
            'reviewed_base':d.get('reviewed_base'),'base_sha':d.get('base_sha'),
            'tests':d.get('tests'),'review':d.get('review'),'turns':d.get('turns'),'usage':d.get('usage'),
            'reason':d.get('reason'),'human_interventions':0,'remote_repo':REPOSITORY,
            'trigger_files':triggers['files'],'hooks':len(hooks),'deployments_before':len(deployments),
            'merge':False,'deploy':False}
        atomic_json(AREA/'result.json',summary)
        print(json.dumps(summary,indent=2))
    finally:runner.close()

if __name__=='__main__':main()
