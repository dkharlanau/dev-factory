"""Compile the current backlog into deterministic local execution batches without model turns."""
from __future__ import annotations
import re
from pathlib import Path
from .policy import Stop
from .state import atomic_json
from .tasks import resolve

def _artifact_path(config, project):
    safe=re.sub(r'[^A-Za-z0-9_.-]+','-',project)
    return Path(config['state_dir'])/'projects'/safe/'campaign.json'

def compile_campaign(config, project, *, max_tasks=50):
    if not 1 <= max_tasks <= 200:
        raise Stop('BLOCKED_POLICY','compile max-tasks must be 1..200')
    old_completed=config.get('_completed_keys')
    old_cache=config.get('_planning_cache')
    config['_completed_keys']=[]
    config['_planning_cache']={}
    batches=[]; seen=set(); total=0; terminal=None; base_sha=None
    try:
        while total < max_tasks:
            limit=min(max_tasks-total,config.get('batching',{}).get('max_tasks',1))
            plan=resolve(config,project,mutate=True,batch_limit=limit)
            base_sha=base_sha or plan.get('base_sha')
            if plan.get('state')!='EXECUTE':
                terminal={'state':plan.get('state'),'reason':plan.get('reason')}
                break
            keys=tuple(plan.get('member_task_keys') or [plan['task_key']])
            if keys in seen:
                terminal={'state':'BLOCKED_STATE','reason':'Campaign compiler repeated a batch'}
                break
            seen.add(keys)
            tasks=plan.get('tasks') or [plan['task']]
            batches.append({'batch':len(batches)+1,'batch_id':plan['task']['id'],
                            'task_ids':[t['id'] for t in tasks],
                            'paths':plan['task']['paths'],'checks':plan['task']['checks'],
                            'profile':plan['profile'],'risk':plan['risk'],
                            'context_roots':plan.get('context_roots',[]),
                            'repo_profile_hash':plan.get('repo_profile_hash')})
            for key in keys:
                if key not in config['_completed_keys']: config['_completed_keys'].append(key)
            total += len(keys)
        result={'state':'COMPILED','project':project,'base_sha':base_sha,'task_count':total,
                'batch_count':len(batches),'batches':batches,'after':terminal,
                'model_turns':0}
        target=_artifact_path(config,project)
        atomic_json(target,result)
        result['artifact']=str(target)
        return result
    finally:
        if old_completed is None: config.pop('_completed_keys',None)
        else: config['_completed_keys']=old_completed
        if old_cache is None: config.pop('_planning_cache',None)
        else: config['_planning_cache']=old_cache
