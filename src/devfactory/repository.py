from __future__ import annotations
import hashlib
import json
import re
import subprocess
from pathlib import Path
from .policy import Stop


def command(argv, cwd=None, timeout=30, check=True):
    try:
        r = subprocess.run(argv,cwd=cwd,capture_output=True,text=True,timeout=timeout)
    except (FileNotFoundError,subprocess.TimeoutExpired) as e:
        raise Stop('BLOCKED_INFRASTRUCTURE',type(e).__name__+': '+argv[0]) from e
    if check and r.returncode:
        # No raw stderr persistence: authenticated tools can include sensitive context.
        raise Stop('BLOCKED_INFRASTRUCTURE',f'{argv[0]} operation failed (exit {r.returncode})')
    return r


def git(path,*args,check=True,timeout=30):
    return command(['git','-c','core.hooksPath=/dev/null','-C',str(path),*args],check=check,timeout=timeout).stdout.strip()


def repository_id(remote):
    match = re.fullmatch(r'(?:https://github\.com/|git@github\.com:)([\w.-]+/[\w.-]+?)(?:\.git)?/?',remote)
    return match.group(1).lower() if match else None


def snapshot(path, expected=None, *, remote=True):
    p = Path(path).expanduser().resolve()
    root = Path(git(p,'rev-parse','--show-toplevel')).resolve()
    if root != p:
        raise Stop('BLOCKED_REPOSITORY','Configured path is not the Git repository root')
    origin = git(p,'remote','get-url','origin',check=False)
    if expected and repository_id(origin) != expected.lower():
        raise Stop('BLOCKED_REPOSITORY','Git remote identity differs from configured repository')
    head = git(p,'rev-parse','HEAD')
    operations = []
    for op in ('MERGE_HEAD','CHERRY_PICK_HEAD','REVERT_HEAD','rebase-merge','rebase-apply','BISECT_LOG'):
        candidate = Path(git(p,'rev-parse','--git-path',op))
        if not candidate.is_absolute(): candidate = p/candidate
        if candidate.exists(): operations.append(op)
    status = git(p,'status','--porcelain=v1','--untracked-files=normal')
    return {'path':str(p),'repository':expected or repository_id(origin),'head':head,
            'branch':git(p,'branch','--show-current'),'dirty':bool(status),
            'status_hash':hashlib.sha256(status.encode()).hexdigest(),
            'operations':operations,'origin':origin}


def tracked_authority(path, sha, names):
    result = []
    for name in names:
        r = command(['git','-C',str(path),'show',f'{sha}:{name}'],check=False)
        if r.returncode == 0:
            text = r.stdout
            result.append({'path':name,'sha256':hashlib.sha256(text.encode()).hexdigest(),'text':text})
    return result


def branch_conflicts(authority):
    conflicts = []
    for doc in authority:
        if re.search(r'work only on [`*]*main|main[`*]* is the only active product branch|main.*only active product branch',doc['text'],re.I):
            conflicts.append({'path':doc['path'],'conflict':'Repository requires main; Factory requires an isolated working branch'})
    return conflicts


def changed(path, base):
    tracked = git(path,'diff','--name-only',base).splitlines()
    new = git(path,'ls-files','--others','--exclude-standard').splitlines()
    return sorted(set(tracked+new))


def fingerprint(path, base):
    names = changed(path,base)
    h = hashlib.sha256()
    h.update(git(path,'rev-parse','HEAD').encode())
    # Git diff includes modes, deletions, renames and binary changes; files include untracked.
    h.update(command(['git','-C',str(path),'diff','--binary',base]).stdout.encode())
    for n in names:
        p = Path(path)/n
        h.update(n.encode())
        if p.is_symlink():
            h.update(str(p.readlink()).encode())
        elif p.is_file():
            h.update(p.read_bytes())
    return h.hexdigest()


def create_worktree(repo, path, branch, base):
    path = Path(path)
    if path.exists():
        current = snapshot(path,remote=False)
        if current['branch'] != branch:
            raise Stop('BLOCKED_RECONCILIATION','Existing worktree belongs to another branch')
        return path
    # Factory runs outside Desktop tool context. Git is the available worktree adapter.
    git(repo,'worktree','add','-b',branch,str(path),base)
    return path


def commit_owned(path, base, allowed):
    names = changed(path,base)
    if not names:
        return git(path,'rev-parse','HEAD')
    if any(not any(n == a or n.startswith(a.rstrip('/')+'/') for a in allowed) for n in names):
        raise Stop('BLOCKED_SCOPE','Worker changed files outside task paths')
    git(path,'add','--',*names)
    # Controller-owned commits must not depend on the operator's global Git identity.
    git(path,'-c','user.name=DevFactory','-c','user.email=devfactory@localhost',
        'commit','-m','DevFactory: complete bounded task')
    return git(path,'rev-parse','HEAD')


class GitHub:
    """Explicitly permitted gh fallback; fixed argv and repository identity."""
    def __init__(self, repository, allowed):
        self.repository = repository
        if not re.fullmatch(r'[\w.-]+/[\w.-]+',repository):
            raise Stop('BLOCKED_REPOSITORY','Invalid GitHub identity')
        if not allowed:
            raise Stop('NATIVE_HANDOFF','SDK has no stable deterministic connector-call adapter; gh fallback not enabled')
        command(['gh','auth','status'],check=True)

    def json(self,*args):
        r = command(['gh',*args],timeout=45)
        try: return json.loads(r.stdout)
        except ValueError: raise Stop('BLOCKED_GITHUB','GitHub returned invalid JSON')

    def refresh(self):
        meta = self.json('repo','view',self.repository,'--json','nameWithOwner,defaultBranchRef,hasIssuesEnabled')
        if meta['nameWithOwner'].lower() != self.repository.lower():
            raise Stop('BLOCKED_REPOSITORY','GitHub repository mismatch')
        prs = self.json('pr','list','--repo',self.repository,'--state','open','--limit','500',
                        '--json','number,title,headRefName,headRefOid,baseRefName,url,isDraft,closingIssuesReferences')
        issues = self.json('issue','list','--repo',self.repository,'--state','open','--limit','500',
                           '--json','number,title,body,labels,updatedAt,url') if meta['hasIssuesEnabled'] else []
        if len(prs) == 500 or len(issues) == 500:
            raise Stop('NATIVE_HANDOFF','Backlog exceeds bounded discovery; use explicit current task reference')
        return meta, prs, issues

    def dependency(self, number):
        r = self.json('pr','view',str(int(number)),'--repo',self.repository,'--json','state,mergedAt,headRefOid')
        return r['state'] == 'MERGED' and bool(r['mergedAt'])

    def find_pr(self, branch):
        rows = self.json('pr','list','--repo',self.repository,'--head',branch,'--state','all',
                         '--json','number,url,state,headRefOid,isDraft')
        if len(rows) > 1:
            raise Stop('BLOCKED_RECONCILIATION','Multiple PRs match Factory branch')
        return rows[0] if rows else None

    def ensure_pr(self, branch, base, body_file, title, cwd):
        existing = self.find_pr(branch)
        if existing: return existing
        # Ambiguous failures are reconciled once; do not blindly retry a write.
        result = command(['gh','pr','create','--repo',self.repository,'--head',branch,'--base',base,
                          '--draft','--title',title,'--body-file',str(body_file)],cwd=cwd,check=False)
        found = self.find_pr(branch)
        if found: return found
        raise Stop('BLOCKED_GITHUB',f'PR creation not confirmed (exit {result.returncode}); resume to reconcile')


def apply_delta(source, destination, base):
    """Apply exact tracked/untracked source delta to an existing checkout."""
    import shutil
    source,destination=Path(source),Path(destination)
    patch = command(['git','-C',str(source),'diff','--binary',base]).stdout
    if patch:
        r = subprocess.run(['git','-C',str(destination),'apply','--binary','-'],
                           input=patch,text=True,capture_output=True)
        if r.returncode:
            raise Stop('BLOCKED_RECONCILIATION','Could not apply reviewed delta')
    for n in git(source,'ls-files','--others','--exclude-standard').splitlines():
        src,dst=source/n,destination/n
        if src.is_symlink(): raise Stop('NATIVE_HANDOFF','Untracked symlink requires owner review')
        if dst.exists() or dst.is_symlink():
            raise Stop('BLOCKED_RECONCILIATION','Untracked batch path already exists: '+n)
        dst.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(src,dst)
    return changed(destination,base)


def review_snapshot(source, destination, base):
    """Isolated exact source snapshot; writable test scratch without builder access."""
    destination = Path(destination)
    if destination.exists():
        raise Stop('BLOCKED_RECONCILIATION','Review snapshot already exists; use a new identity')
    command(['git','-c','core.hooksPath=/dev/null','clone','--quiet','--no-hardlinks','--no-checkout',str(source),str(destination)])
    git(destination,'checkout','--detach',base)
    apply_delta(source,destination,base)
    # Preserve gitignored validation scratch as scratch only; no node_modules copy.
    return destination


def trigger_snapshot(path):
    """Read potential integration/spend triggers; never assume no hidden host trigger."""
    names = [n for n in git(path,'ls-files').splitlines() if n.startswith('.github/workflows/') or
             Path(n).name in ('netlify.toml','vercel.json','wrangler.json','wrangler.jsonc','package.json')]
    files = []
    for name in names:
        p=Path(path)/name
        if p.is_file(): files.append({'path':name,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()})
    from .state import digest
    return {'files':files,'hash':digest(files),'external_host_triggers':'unknown until owner inspection'}
