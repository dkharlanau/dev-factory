"""Resolve current task contracts from existing authority, never a Factory backlog."""
from __future__ import annotations
import json
import re
from pathlib import Path
from .policy import Stop, screen_task, classify
from .repository import GitHub, snapshot, git, tracked_authority, branch_conflicts, command
from .state import digest

CONTRACT_KEYS = {'id','description','acceptance','paths','category','risk','complexity','verification',
                 'checks','dependencies','required_capabilities','priority','state','higher_risk_approved'}


def parse_contract(text):
    blocks = re.findall(r'```factory-task\s*\n(.*?)\n```',text,re.S)
    out = []
    for block in blocks:
        try: value = json.loads(block)
        except ValueError: raise Stop('NATIVE_HANDOFF','Malformed task contract in current authority')
        if not isinstance(value,dict) or set(value)-CONTRACT_KEYS:
            raise Stop('NATIVE_HANDOFF','Task contract contains unsupported fields; policy/commands cannot come from tasks')
        if not all(value.get(k) for k in ('id','description','acceptance','paths','checks')):
            raise Stop('NATIVE_HANDOFF','Task contract lacks acceptance, scope or named checks')
        if not isinstance(value['paths'],list) or not isinstance(value['checks'],list):
            raise Stop('NATIVE_HANDOFF','Task paths/checks must be lists')
        if not all(isinstance(x,str) and x for x in value['paths']+value['checks']):
            raise Stop('NATIVE_HANDOFF','Task paths/checks must be non-empty strings')
        # Task prose cannot self-approve a higher-risk gate.
        value.pop('higher_risk_approved',None)
        screen_task(value)
        out.append(value)
    return out


def resolve(config, project, *, mutate=False):
    if project not in config['projects']:
        raise Stop('NOT_FOUND','Unknown project; configured: '+', '.join(config['projects']))
    adapter = config['projects'][project]
    if not adapter.get('path'):
        raise Stop('NATIVE_HANDOFF','Set the verified checkout path in ignored factory.local.toml')
    repo = snapshot(adapter['path'],adapter.get('repository'))
    if repo['operations']:
        raise Stop('BLOCKED_REPOSITORY','Unfinished Git operation: '+', '.join(repo['operations']))
    github = None
    prs, issues = [], []
    if adapter.get('fixture'):
        base = adapter['base_sha']
        meta = {'defaultBranchRef':{'name':'main'},'hasIssuesEnabled':False}
    else:
        github = GitHub(adapter['repository'],adapter.get('allow_gh',False))
        meta,prs,issues = github.refresh()
        branch = meta['defaultBranchRef']['name']
        remote = git(repo['path'],'ls-remote','origin','refs/heads/'+branch)
        if not remote:
            raise Stop('BLOCKED_GITHUB','Remote default branch unavailable')
        base = remote.split()[0]
        has = command(['git','-C',repo['path'],'cat-file','-e',base+'^{commit}'],check=False).returncode == 0
        if not has and mutate:
            git(repo['path'],'fetch','--no-tags','origin',branch)
            has = True
        if not has:
            return {'state':'NATIVE_HANDOFF','project':project,'repository':repo,'base_sha':base,
                    'reason':'Remote base object absent locally; run may fetch before isolated work',
                    'open_prs':prs,'next':'factory run '+project+' --max-tasks 1'}
    names = list(dict.fromkeys(adapter.get('instructions',[])+adapter.get('backlogs',[])))
    authority = tracked_authority(repo['path'],base,names)
    conflicts = branch_conflicts(authority)
    # Current uncommitted governing instructions are not silently ignored.
    dirty_authority = [d['path'] for d in authority if (Path(repo['path'])/d['path']).exists()
                       and (Path(repo['path'])/d['path']).read_text() != d['text']]
    tasks = []
    for doc in authority:
        for t in parse_contract(doc['text']):
            t['source'] = {'kind':'file','path':doc['path'],'base_sha':base}
            tasks.append(t)
    for issue in issues:
        for t in parse_contract(issue.get('body') or ''):
            t['source'] = {'kind':'issue','number':issue['number'],'url':issue['url'],'updated_at':issue['updatedAt']}
            tasks.append(t)
    executable = [t for t in tasks if t.get('state') in ('EXECUTE','IN_PROGRESS')]
    executable.sort(key=lambda t:(t.get('state')!='IN_PROGRESS',t.get('priority',100),str(t['id'])))
    plan = {'project':project,'state':'IDLE','repository':repo,'base_sha':base,
            'base_branch':meta['defaultBranchRef']['name'],'issues_enabled':meta['hasIssuesEnabled'],
            'open_prs':prs,'authority':[{k:v for k,v in d.items() if k!='text'} for d in authority],
            'conflicts':conflicts,'dirty_authority':dirty_authority,
            'task':None,'reason':'No executable task contract in current repository authority'}
    if conflicts or dirty_authority:
        plan.update(state='NATIVE_HANDOFF',reason='Current repository authority conflicts with the execution plan')
        return plan
    if not executable:
        if issues or any('EXECUTE' in d['text'] for d in authority) or prs:
            plan.update(state='NATIVE_HANDOFF',reason='Current work exists but has no unambiguous machine-readable acceptance/scope; native selection required')
        return plan
    for task in executable:
        dependencies = task.get('dependencies',[])
        if dependencies and (not github or not all(github.dependency(n) for n in dependencies)):
            continue
        issue_number = task['source'].get('number')
        overlap = [p for p in prs if issue_number and any(i['number']==issue_number for i in p.get('closingIssuesReferences',[]))]
        if overlap:
            plan.update(state='NATIVE_HANDOFF',reason='Finish existing related PR before starting another implementation',task=task)
            return plan
        required = task.get('required_capabilities',[])
        if any(c not in ('shell','git','python','node','rust') for c in required):
            plan.update(state='NATIVE_HANDOFF',reason='Required capability needs native Codex: '+', '.join(required),task=task)
            return plan
        named = adapter.get('checks',{})
        final = adapter.get('final_checks',[])
        if not final or any(c not in named for c in task['checks']+final):
            plan.update(state='NATIVE_HANDOFF',reason='Owner check allowlist/final gate is not configured',task=task)
            return plan
        for name in task['checks']+final:
            argv = named[name]
            if not isinstance(argv,list) or not argv or not all(isinstance(a,str) for a in argv):
                raise Stop('BLOCKED_POLICY','Configured checks must be nonempty argv lists')
        profile,risk = classify(task,adapter.get('high_risk_paths',[]))
        contract_hash = digest(task)
        task_key = digest([adapter.get('repository',project),task['id']])
        if task_key in config.get('_completed_keys',[]):
            continue
        # Explicit higher-risk approval is local owner configuration bound to exact contract.
        if risk in ('high','unknown') and contract_hash not in adapter.get('approved_contracts',[]):
            plan.update(state='NATIVE_HANDOFF',reason='Higher-risk gate requires owner approval of this exact contract',task=task,contract_hash=contract_hash)
            return plan
        plan.update(state='EXECUTE',task=task,contract_hash=contract_hash,profile=profile,risk=risk,
                    task_key=digest([adapter.get('repository',project),task['id']]),
                    reason='Current executable contract; dependencies reconciled')
        return plan
    plan['reason'] = 'All candidate tasks depend on unmerged work'
    return plan
