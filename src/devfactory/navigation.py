"""Deterministic repository prep, context hygiene, and task-local navigation."""
from __future__ import annotations
import hashlib
import itertools
import json
import re
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath
from .policy import Stop
from .repository import git, command, snapshot
from .state import atomic_json, digest

ROOT_HINTS={'AGENTS.md','README.md','CONTRIBUTING.md','pyproject.toml','package.json','Cargo.toml',
            'go.mod','Makefile','justfile','tsconfig.json','vite.config.ts','vite.config.js'}
AUTO_COLD_NAMES={'archive','archives','history','dist','build','coverage','.next','.cache','target',
                 'node_modules','vendor','generated','out'}
INSTRUCTION_PATTERNS=(
    re.compile(r'(?i)before (?:every|any) (?:edit|change|task).*read'),
    re.compile(r'(?i)(?:always|must) read (?:all|the whole|the full)'),
    re.compile(r'(?i)(?:full|complete) repo(?:sitory)? map'),
)

def _inside(path, prefix):
    prefix=prefix.rstrip('/')
    return path==prefix or path.startswith(prefix+'/')

def context_root(path):
    parts=PurePosixPath(path).parts
    if len(parts)<=1: return '.'
    if len(parts)==2: return parts[0]
    return '/'.join(parts[:2])

def tree_inventory(path, base_sha):
    rows=[]
    raw=git(path,'ls-tree','-rl',base_sha)
    for line in raw.splitlines():
        left,sep,name=line.partition('\t')
        if not sep: continue
        fields=left.split()
        if len(fields)<4 or fields[1]!='blob': continue
        try: size=int(fields[3])
        except ValueError: size=None
        rows.append({'path':name,'size':size,'root':context_root(name)})
    return rows

def _cold_prefix(path):
    parts=PurePosixPath(path).parts[:-1]
    for i,part in enumerate(parts):
        if part.lower() in AUTO_COLD_NAMES:
            return '/'.join(parts[:i+1])+'/'
    return None

def _read_base_text(path, base_sha, name):
    r=command(['git','-C',str(path),'show',f'{base_sha}:{name}'],check=False)
    return r.stdout if r.returncode==0 else None

def _cochange(path, base_sha, *, history_commits=200, max_roots_per_commit=8,
              min_commits=2, min_confidence=.35):
    raw=command(['git','-C',str(path),'log','--format=__COMMIT__%H','--name-only','--no-renames',
                 '-n',str(int(history_commits)),base_sha],check=False)
    if raw.returncode:
        raise Stop('BLOCKED_INFRASTRUCTURE','Git co-change history is unavailable')
    commits=[]; current=[]
    for line in raw.stdout.splitlines():
        if line.startswith('__COMMIT__'):
            if current: commits.append(current)
            current=[]
        elif line.strip():
            current.append(line.strip())
    if current: commits.append(current)
    touches=Counter(); pairs=Counter()
    for names in commits:
        roots=sorted({context_root(n) for n in names if context_root(n)!='.'})
        if not 1 <= len(roots) <= int(max_roots_per_commit): continue
        for root in roots: touches[root]+=1
        for a,b in itertools.combinations(roots,2): pairs[(a,b)]+=1
    graph=defaultdict(list)
    for (a,b),count in pairs.items():
        confidence=count/max(1,min(touches[a],touches[b]))
        if count < int(min_commits) or confidence < float(min_confidence): continue
        edge_ab={'root':b,'count':count,'confidence':round(confidence,3)}
        edge_ba={'root':a,'count':count,'confidence':round(confidence,3)}
        graph[a].append(edge_ab); graph[b].append(edge_ba)
    for root in list(graph):
        graph[root]=sorted(graph[root],key=lambda x:(-x['confidence'],-x['count'],x['root']))[:8]
    return dict(sorted(graph.items()))

def roots_related(left, right, profile):
    left,right=set(left),set(right)
    if left & right: return True
    graph=(profile or {}).get('cochange',{})
    for root in left:
        if any(edge.get('root') in right for edge in graph.get(root,[])):
            return True
    return False

def analyze_repository(path, base_sha, *, configured_cold_paths=(), rules=None):
    rules=rules or {}
    inventory=tree_inventory(path,base_sha)
    file_count=len(inventory)
    total_bytes=sum(x['size'] or 0 for x in inventory)
    root_counts=Counter(x['root'] for x in inventory)
    direct=Counter(str(PurePosixPath(x['path']).parent) for x in inventory)
    configured=[x.rstrip('/')+'/' for x in configured_cold_paths if x]
    auto=set(); generated=[]
    for row in inventory:
        prefix=_cold_prefix(row['path'])
        if prefix:
            auto.add(prefix); generated.append(row['path'])
    cold=list(dict.fromkeys(configured+sorted(auto)))
    cold_files=[x for x in inventory if any(_inside(x['path'],p) for p in cold)]
    findings=[]
    large=int(rules.get('large_file_bytes',1_000_000))
    for row in sorted((x for x in inventory if (x['size'] or 0)>=large),
                      key=lambda x:-(x['size'] or 0))[:12]:
        findings.append({'severity':'warning','code':'LARGE_TRACKED_FILE','path':row['path'],
                         'detail':f"{row['size']} tracked bytes",
                         'recommendation':'Keep large generated/binary artifacts outside normal Git or use an appropriate artifact/LFS path.'})
    wide=int(rules.get('wide_directory_entries',500))
    for directory,count in direct.most_common(10):
        if count>=wide:
            findings.append({'severity':'warning','code':'WIDE_DIRECTORY','path':directory,
                             'detail':f'{count} direct tracked files',
                             'recommendation':'Split very wide generated/data directories or keep generated output outside the tracked source tree.'})
    roots=sum(1 for x in inventory if '/' not in x['path'])
    if roots>=int(rules.get('root_entries',40)):
        findings.append({'severity':'info','code':'ROOT_CLUTTER','path':'.','detail':f'{roots} tracked root files',
                         'recommendation':'Keep root navigation small; move non-entrypoint documentation/history into scoped directories.'})
    if generated:
        findings.append({'severity':'info','code':'TRACKED_COLD_OUTPUT','path':None,
                         'detail':f'{len(generated)} tracked files under archive/generated/build-style roots',
                         'examples':generated[:8],
                         'recommendation':'Factory excludes these from default agent navigation; review whether generated output should stay tracked.'})
    agent_paths=[x['path'] for x in inventory if PurePosixPath(x['path']).name=='AGENTS.md'][:20]
    instruction_stats=[]
    for name in agent_paths:
        text=_read_base_text(path,base_sha,name)
        if text is None: continue
        lines=text.count('\n')+1 if text else 0
        flags=[pattern.pattern for pattern in INSTRUCTION_PATTERNS if pattern.search(text)]
        instruction_stats.append({'path':name,'lines':lines,'bytes':len(text.encode()),'bloat_flags':len(flags)})
        if lines>int(rules.get('instruction_max_lines',120)) or len(text.encode())>int(rules.get('instruction_max_bytes',12000)) or flags:
            findings.append({'severity':'warning','code':'AGENT_INSTRUCTION_BLOAT','path':name,
                             'detail':f'{lines} lines, {len(text.encode())} bytes, {len(flags)} broad-read rules',
                             'recommendation':'Keep durable rules compact and point to specialized docs only when the task requires them.'})
    cochange_status={'state':'available'}
    try:
        cochange=_cochange(path,base_sha,
            history_commits=rules.get('history_commits',200),
            max_roots_per_commit=rules.get('max_roots_per_commit',8),
            min_commits=rules.get('min_cochange_commits',2),
            min_confidence=rules.get('min_cochange_confidence',.35))
    except Stop as error:
        if error.state!='BLOCKED_INFRASTRUCTURE': raise
        cochange={}
        cochange_status={'state':'unavailable','reason':error.reason}
        findings.append({'severity':'warning','code':'COCHANGE_UNAVAILABLE','path':None,
                         'detail':error.reason,
                         'recommendation':'Use shared task roots; cross-root batching requires observed history.'})
    profile={'version':1,'base_sha':base_sha,'metrics':{
                'tracked_files':file_count,'tracked_bytes':total_bytes,'root_files':roots,
                'cold_files':len(cold_files),'cold_bytes':sum(x['size'] or 0 for x in cold_files),
                'largest_roots':dict(root_counts.most_common(12))},
             'context':{'configured_cold_paths':configured,'auto_cold_paths':sorted(auto),
                        'effective_cold_paths':cold},
             'instructions':instruction_stats,'cochange':cochange,'cochange_status':cochange_status,'findings':findings,
             'cleanup':{'mode':'context_only','product_files_changed':False,
                        'reason':'Automatic prep optimizes agent visibility; destructive repository cleanup stays explicit and reviewed.'}}
    profile['profile_hash']=digest(profile)
    return profile

def _profile_path(config, project):
    safe=re.sub(r'[^A-Za-z0-9_.-]+','-',project)
    return Path(config['state_dir'])/'projects'/safe/'repo-profile.json'

def ensure_profile(config, project, repo_path, base_sha):
    cache=config.setdefault('_repo_profiles',{})
    existing=cache.get(project)
    if existing and existing.get('base_sha')==base_sha:
        return existing
    profile=analyze_repository(repo_path,base_sha,
        configured_cold_paths=config['context'].get('cold_paths',[]),
        rules=config.get('hygiene',{}))
    profile['project']=project
    target=_profile_path(config,project)
    atomic_json(target,profile)
    profile['profile_path']=str(target)
    cache[project]=profile
    return profile

def prepare_project(config, project):
    if project not in config['projects']:
        raise Stop('NOT_FOUND','Unknown project; configured: '+', '.join(config['projects']))
    adapter=config['projects'][project]
    if not adapter.get('path'):
        raise Stop('NATIVE_HANDOFF','Set the verified checkout path in ignored factory.local.toml')
    repo=snapshot(adapter['path'],adapter.get('repository'))
    if repo['operations']:
        raise Stop('BLOCKED_REPOSITORY','Unfinished Git operation: '+', '.join(repo['operations']))
    profile=ensure_profile(config,project,repo['path'],repo['head'])
    return {'state':'PREPARED','project':project,'base_sha':repo['head'],'dirty_worktree':repo['dirty'],
            'profile_path':profile['profile_path'],'metrics':profile['metrics'],'context':profile['context'],
            'cochange_roots':len(profile['cochange']),'findings':profile['findings'],
            'cleanup':profile['cleanup']}

def repository_registry(path, base_sha, task_paths, *, guidance_files=(), cold_paths=(), max_files=40, profile=None):
    inventory=tree_inventory(path,base_sha)
    extra=(profile or {}).get('context',{}).get('auto_cold_paths',[])
    cold=list(dict.fromkeys([x.rstrip('/') for x in list(cold_paths)+list(extra) if x]))
    task_paths=list(dict.fromkeys(task_paths))
    def task_allows_cold(f):
        return any(_inside(f,p) for p in task_paths if any(_inside(p,c) or _inside(c,p) for c in cold))
    active=[x['path'] for x in inventory if not any(_inside(x['path'],c) for c in cold) or task_allows_cold(x['path'])]
    counts=Counter((PurePosixPath(f).parts or ('.',))[0] for f in active)
    parents={str(PurePosixPath(p).parent) for p in task_paths}
    relevant=set(guidance_files)
    for f in active:
        parent=str(PurePosixPath(f).parent)
        if f in ROOT_HINTS or any(_inside(f,p) or _inside(p,f) for p in task_paths) or parent in parents:
            relevant.add(f)
    ordered=sorted(relevant,key=lambda f:(0 if any(_inside(f,p) or _inside(p,f) for p in task_paths) else
                                          1 if f in guidance_files else 2, f))
    nearby=ordered[:max(1,int(max_files))]
    payload={'base_sha':base_sha,'file_count':len(inventory),'active_file_count':len(active),
             'cold_excluded':len(inventory)-len(active),'top_roots':dict(counts.most_common(12)),
             'profile_hash':(profile or {}).get('profile_hash')}
    payload['registry_hash']=hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    return payload, {'files':nearby,'cold_excluded':payload['cold_excluded'],
                     'profile_hash':payload['profile_hash']}
