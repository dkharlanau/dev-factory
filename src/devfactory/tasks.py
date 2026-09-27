"""Resolve current task contracts from existing authority; batch only compatible work."""
from __future__ import annotations
import json
import re
from pathlib import Path
from .policy import Stop, screen_task, classify
from .repository import GitHub, snapshot, git, tracked_authority, branch_conflicts, command
from .state import digest
from .navigation import ensure_profile, roots_related

CONTRACT_KEYS = {'id','description','acceptance','paths','category','risk','complexity','verification',
                 'checks','dependencies','required_capabilities','priority','state','higher_risk_approved'}
LOCAL_CAPABILITIES = {'shell','git','python','node','rust'}

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
        value.pop('higher_risk_approved',None)
        screen_task(value)
        out.append(value)
    return out

def context_roots(paths):
    roots=set()
    for raw in paths:
        parts=Path(raw).parts
        if len(parts) <= 1: roots.add('.')
        elif len(parts) == 2: roots.add(parts[0])
        else: roots.add('/'.join(parts[:2]))
    return roots

def _load_snapshot(config, project, adapter, mutate):
    repo = snapshot(adapter['path'],adapter.get('repository'))
    if repo['operations']:
        raise Stop('BLOCKED_REPOSITORY','Unfinished Git operation: '+', '.join(repo['operations']))
    cache = config.get('_planning_cache')
    cached = cache.get(project) if isinstance(cache,dict) else None
    cache_key=(repo['path'],adapter.get('repository'),tuple(adapter.get('instructions',[])),tuple(adapter.get('backlogs',[])))
    if cached and cached.get('cache_key') == cache_key:
        meta,prs,issues,base,authority = (cached[k] for k in ('meta','prs','issues','base','authority'))
        github = cached.get('github')
    else:
        github=None; prs=[]; issues=[]
        if adapter.get('fixture'):
            base=adapter['base_sha']
            meta={'defaultBranchRef':{'name':'main'},'hasIssuesEnabled':False}
        else:
            github=GitHub(adapter['repository'],adapter.get('allow_gh',False))
            meta,prs,issues=github.refresh()
            branch=meta['defaultBranchRef']['name']
            remote=git(repo['path'],'ls-remote','origin','refs/heads/'+branch)
            if not remote: raise Stop('BLOCKED_GITHUB','Remote default branch unavailable')
            base=remote.split()[0]
            has=command(['git','-C',repo['path'],'cat-file','-e',base+'^{commit}'],check=False).returncode == 0
            if not has and mutate:
                git(repo['path'],'fetch','--no-tags','origin',branch,timeout=120)
                has=command(['git','-C',repo['path'],'cat-file','-e',base+'^{commit}'],check=False).returncode == 0
            if not has:
                return repo,None,None,None,None,None,{'state':'NATIVE_HANDOFF','project':project,'repository':repo,
                    'base_sha':base,'reason':'Remote base object absent locally; run may fetch before isolated work',
                    'open_prs':prs,'next':'factory run '+project+' --max-tasks 1'}
        names=list(dict.fromkeys(adapter.get('instructions',[])+adapter.get('backlogs',[])))
        authority=tracked_authority(repo['path'],base,names)
        if isinstance(cache,dict):
            cache[project]={'cache_key':cache_key,'meta':meta,'prs':prs,'issues':issues,'base':base,
                            'authority':authority,'github':github}
    return repo,github,meta,prs,issues,base,authority

def dirty_authority_paths(repo, base, authority):
    """A clean ancestor checkout is stale, not an uncommitted policy override."""
    mismatches=[]
    for doc in authority:
        path=Path(repo['path'])/doc['path']
        current=path.read_text() if path.is_file() else None
        if current!=doc['text']: mismatches.append((doc['path'],current))
    if not mismatches: return []
    ancestor=command(['git','-C',repo['path'],'merge-base','--is-ancestor',repo['head'],base],check=False).returncode==0
    dirty=[]
    for name,current in mismatches:
        original=command(['git','-C',repo['path'],'show',repo['head']+':'+name],check=False)
        unchanged=current==(original.stdout if original.returncode==0 else None)
        if not ancestor or not unchanged: dirty.append(name)
    return dirty


def authority_approval(adapter, base, authority, tasks):
    """Only a local owner decision bound to the current source/task snapshot applies."""
    approval=adapter.get('authority_approval') or {}
    public=[{k:v for k,v in d.items() if k!='text'} for d in authority]
    if (approval.get('base_sha')!=base or approval.get('authority_hash')!=digest(public)
            or not tasks or not approval.get('task_ids')
            or any(t['id'] not in approval['task_ids'] for t in tasks)
            or any(digest(t) not in approval.get('contract_hashes',[]) for t in tasks)):
        return {}
    return {k:approval.get(k) is True for k in ('isolated_branch','remote_authority')}


def resolve(config, project, *, mutate=False, batch_limit=1):
    if project not in config['projects']:
        raise Stop('NOT_FOUND','Unknown project; configured: '+', '.join(config['projects']))
    adapter=config['projects'][project]
    if not adapter.get('path'):
        raise Stop('NATIVE_HANDOFF','Set the verified checkout path in ignored factory.local.toml')
    loaded=_load_snapshot(config,project,adapter,mutate)
    if isinstance(loaded[-1],dict) and loaded[-1].get('state'):
        return loaded[-1]
    repo,github,meta,prs,issues,base,authority=loaded
    conflicts=branch_conflicts(authority)
    dirty_authority=dirty_authority_paths(repo,base,authority)
    tasks=[]
    for doc in authority:
        for t in parse_contract(doc['text']):
            t['source']={'kind':'file','path':doc['path'],'base_sha':base}; tasks.append(t)
    for issue in issues:
        for t in parse_contract(issue.get('body') or ''):
            t['source']={'kind':'issue','number':issue['number'],'url':issue['url'],'updated_at':issue['updatedAt']}
            tasks.append(t)
    executable=[t for t in tasks if t.get('state') in ('EXECUTE','IN_PROGRESS')]
    executable.sort(key=lambda t:(t.get('state')!='IN_PROGRESS',t.get('priority',100),str(t['id'])))
    approval=authority_approval(adapter,base,authority,executable)
    plan={'project':project,'state':'IDLE','repository':repo,'base_sha':base,
          'base_branch':meta['defaultBranchRef']['name'],'issues_enabled':meta['hasIssuesEnabled'],
          'open_prs':prs,'authority':[{k:v for k,v in d.items() if k!='text'} for d in authority],
          'conflicts':conflicts,'dirty_authority':dirty_authority,'authority_approval':approval,'task':None,'tasks':[],
          'reason':'No executable task contract in current repository authority','planning_snapshot':'frozen-per-run'}
    if (conflicts and not approval.get('isolated_branch')) or (dirty_authority and not approval.get('remote_authority')):
        plan.update(state='NATIVE_HANDOFF',reason='Current repository authority conflicts with the execution plan'); return plan
    if not executable:
        if issues or any('EXECUTE' in d['text'] for d in authority) or prs:
            plan.update(state='NATIVE_HANDOFF',reason='Current work exists but has no unambiguous machine-readable acceptance/scope; native selection required')
        return plan
    repo_profile=ensure_profile(config,project,repo['path'],base)
    batching=config.get('batching',{})
    if not batching.get('enabled',True) or config['integration'].get('push') or config['integration'].get('pull_request'):
        batch_limit=1
    batch_limit=max(1,min(int(batch_limit),int(batching.get('max_tasks',1))))
    selected=[]; details=[]; roots=None
    named=adapter.get('checks',{}); final=adapter.get('final_checks',[])
    setup=adapter.get('setup_checks',[])
    if not isinstance(setup,list) or not all(isinstance(n,str) and n for n in setup):
        raise Stop('BLOCKED_POLICY','Owner setup checks must be a list of check names')
    if not final:
        plan.update(state='NATIVE_HANDOFF',reason='Owner final check allowlist is not configured'); return plan
    for task in executable:
        contract_hash=digest(task)
        task_key=digest([adapter.get('repository',project),task['id']])
        if task_key in config.get('_completed_keys',[]): continue
        dependencies=task.get('dependencies',[])
        if dependencies and (not github or not all(github.dependency(n) for n in dependencies)):
            if selected: break
            continue
        issue_number=task['source'].get('number')
        overlap=[p for p in prs if issue_number and any(i['number']==issue_number for i in p.get('closingIssuesReferences',[]))]
        if overlap:
            if selected: break
            plan.update(state='NATIVE_HANDOFF',reason='Finish existing related PR before starting another implementation',task=task); return plan
        required=task.get('required_capabilities',[])
        unsupported=[c for c in required if c not in LOCAL_CAPABILITIES]
        if unsupported:
            if selected: break
            routes=adapter.get('capability_routes',{})
            routed={c:routes.get(c) for c in unsupported if routes.get(c)}
            reason='Required capability needs native Codex: '+', '.join(unsupported)
            if routed: reason+='; deferred route: '+json.dumps(routed,separators=(',',':'))
            plan.update(state='NATIVE_HANDOFF',reason=reason,task=task,capability_routes=routed); return plan
        if any(c not in named for c in task['checks']+final+setup):
            if selected: break
            plan.update(state='NATIVE_HANDOFF',reason='Owner check allowlist/final gate is not configured',task=task); return plan
        for name in task['checks']+final+setup:
            argv=named[name]
            if not isinstance(argv,list) or not argv or not all(isinstance(a,str) for a in argv):
                raise Stop('BLOCKED_POLICY','Configured checks must be nonempty argv lists')
        profile,risk=classify(task,adapter.get('high_risk_paths',[]))
        if risk in ('high','unknown') and contract_hash not in adapter.get('approved_contracts',[]):
            if selected: break
            plan.update(state='NATIVE_HANDOFF',reason='Higher-risk gate requires owner approval of this exact contract',
                        task=task,contract_hash=contract_hash); return plan
        detail={'task':task,'profile':profile,'risk':risk,'contract_hash':contract_hash,'task_key':task_key}
        if selected:
            if len(selected)>=batch_limit: break
            if profile!=details[0]['profile'] or risk!=details[0]['risk']: break
            candidate_roots=context_roots(task['paths'])
            if not roots_related(roots,candidate_roots,repo_profile): break
            merged_paths=list(dict.fromkeys([p for t in selected+[task] for p in t['paths']]))
            merged_checks=list(dict.fromkeys([c for t in selected+[task] for c in t['checks']]))
            packet=[{k:t[k] for k in ('id','description','acceptance','paths')} for t in selected+[task]]
            if len(merged_paths)>batching.get('max_paths',24) or len(merged_checks)>batching.get('max_checks',6):
                break
            if len(json.dumps(packet,separators=(',',':'),ensure_ascii=False).encode())>batching.get('max_packet_bytes',12000):
                break
            roots |= candidate_roots
        else:
            roots=context_roots(task['paths'])
        selected.append(task); details.append(detail)
    if not selected:
        plan['reason']='All candidate tasks depend on unmerged work'; return plan
    if len(selected)==1:
        aggregate=selected[0]; contract_hash=details[0]['contract_hash']; task_key=details[0]['task_key']
    else:
        member_hashes=[d['contract_hash'] for d in details]
        aggregate={'id':'batch-'+digest([t['id'] for t in selected])[:12],
                   'description':'Complete '+str(len(selected))+' compatible backlog tasks as one coherent change.',
                   'acceptance':'All member task acceptance criteria pass.',
                   'paths':list(dict.fromkeys([p for t in selected for p in t['paths']])),
                   'checks':list(dict.fromkeys([c for t in selected for c in t['checks']])),
                   'category':'batch','risk':details[0]['risk'],'complexity':'batched',
                   'verification':'strong' if all(t.get('verification')=='strong' for t in selected) else 'mixed',
                   'dependencies':[],'required_capabilities':list(dict.fromkeys([c for t in selected for c in t.get('required_capabilities',[])])),
                   'priority':min(t.get('priority',100) for t in selected),'state':'EXECUTE',
                   'source':{'kind':'batch','members':[t['source'] for t in selected]}}
        contract_hash=digest(member_hashes)
        task_key=digest([adapter.get('repository',project),'batch',[d['task_key'] for d in details]])
    plan.update(state='EXECUTE',task=aggregate,tasks=selected,contract_hash=contract_hash,
                member_contract_hashes=[d['contract_hash'] for d in details],
                member_task_keys=[d['task_key'] for d in details],
                profile=details[0]['profile'],risk=details[0]['risk'],task_key=task_key,
                context_roots=sorted(roots),repo_profile_hash=repo_profile['profile_hash'],
                reason=('Compatible micro-batch from one frozen authority snapshot' if len(selected)>1
                        else 'Current executable contract; dependencies reconciled'))
    return plan
