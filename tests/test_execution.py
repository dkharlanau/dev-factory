import copy
import json
import os
import time
from pathlib import Path
import pytest
from devfactory.state import Store,digest
from devfactory.policy import Stop
from devfactory.runner import Runner
from devfactory.tasks import resolve,parse_contract
from devfactory.repository import git,GitHub,repository_id,snapshot
from fakes import FakeRuntime


def test_end_to_end_fresh_review_idempotence_foreign_dirty(cfg):
    repo=Path(cfg['projects']['demo']['path'])
    (repo/'foreign.txt').write_text('preserve me')
    runner=Runner(cfg,runtime_factory=FakeRuntime,emit=lambda _:None)
    try:
        result=runner.run('demo')[0]
        assert result['state']=='READY_LOCAL',result
        d=result['data']
        assert d['builder_thread']!=d['reviewer_thread']
        assert FakeRuntime.history[-1]['resume'] is None
        assert 'do not duplicate controller validation' in FakeRuntime.history[-1]['instructions']
        assert 'builder_response' not in FakeRuntime.turns[-1]['packet']
        assert (repo/'foreign.txt').read_text()=='preserve me'
        assert (repo/'clamp.py').read_text().endswith('return value\n')
        assert runner.run('demo')[0]['state']=='EXISTING_COMPLETION'
        assert len(FakeRuntime.turns)==2
        assert Path(d['worktree']).exists()
    finally:runner.close()


def test_repair_uses_delta_packet_and_stronger_review(cfg):
    FakeRuntime.outcomes=[
        {'verdict':'PASS','findings':[],'summary':'build'},
        {'verdict':'REPAIR','findings':[{'file':'clamp.py','line':1,'summary':'tighten implementation'}],'summary':'repair'},
        {'verdict':'PASS','findings':[],'summary':'repaired'},
        {'verdict':'PASS','findings':[],'summary':'reviewed'},
    ]
    runner=Runner(cfg,runtime_factory=FakeRuntime,emit=lambda _:None)
    try:
        r=runner.run('demo')[0]
        assert r['state']=='READY_LOCAL'
        build=next(t for t in FakeRuntime.turns if t['packet']['role']=='build')['packet']
        repair=next(t for t in FakeRuntime.turns if t['packet']['role']=='repair')['packet']
        assert set(build['task'])=={'id','description','acceptance','paths'}
        assert build['guidance_files']==['AGENTS.md']
        assert 'BACKLOG.md' not in build['guidance_files']
        assert 'task' in build and 'task' not in repair and repair['task_id']=='clamp-v1'
        assert len(json.dumps(repair,separators=(',',':'))) < len(json.dumps(build,separators=(',',':')))
        assert FakeRuntime.history[-1]['profile']=='deep'
        assert r['data']['efficiency']['packet_utf8_bytes_avoided'] > 0
    finally: runner.close()


def test_soft_token_envelope_does_not_skip_mandatory_review(cfg):
    cfg['budget']['soft_tokens']=1
    runner=Runner(cfg,runtime_factory=FakeRuntime,emit=lambda _:None)
    try:
        r=runner.run('demo')[0]
        assert r['state']=='READY_LOCAL'
        assert r['data']['soft_budget_overshoot_tokens'] > 0
        assert any(t['role']=='review' for t in r['data']['turns'])
    finally: runner.close()


def test_deep_task_keeps_deep_independent_review(cfg):
    repo=Path(cfg['projects']['demo']['path']);p=repo/'BACKLOG.md'
    p.write_text(p.read_text().replace('"complexity": "low"','"complexity": "high"'))
    git(repo,'add','BACKLOG.md')
    git(repo,'-c','user.name=Fixture','-c','user.email=f@localhost','commit','-qm','Deep task')
    cfg['projects']['demo']['base_sha']=git(repo,'rev-parse','HEAD')
    runner=Runner(cfg,runtime_factory=FakeRuntime,emit=lambda _:None)
    try:
        r=runner.run('demo')[0]
        assert r['state']=='READY_LOCAL'
        assert [h['profile'] for h in FakeRuntime.history]==['deep','deep']
    finally: runner.close()


def test_focused_failure_skips_broad_final_checks(cfg):
    broad=['python','-c','print("broad")']
    cfg['projects']['demo']['checks']['broad']=broad
    cfg['projects']['demo']['final_checks']=['unit','broad']
    class RecordingRuntime(FakeRuntime):
        calls=[]
        def command(self,cwd,argv,**kwargs):
            self.calls.append(argv)
            if argv==cfg['projects']['demo']['checks']['unit']:
                return {'exitCode':1,'stdout':'focused failure','stderr':''}
            return {'exitCode':0,'stdout':'','stderr':''}
    runner=Runner(cfg,runtime_factory=RecordingRuntime,emit=lambda _:None)
    try:
        r=runner.run('demo')[0]
        assert r['state']=='BLOCKED_REPAIR_LIMIT'
        assert RecordingRuntime.calls
        assert broad not in RecordingRuntime.calls
    finally: runner.close()


def test_repair_limit(cfg):
    FakeRuntime.fail_tests=True
    runner=Runner(cfg,runtime_factory=FakeRuntime,emit=lambda _:None)
    try:
        r=runner.run('demo')[0]
        assert r['state']=='BLOCKED_REPAIR_LIMIT'
        assert r['data']['repairs']==2 and r['data']['escalations']==1
        assert r['data']['routing_upgrades']==1
        assert [h['profile'] for h in FakeRuntime.history]==['fast','standard','deep']
        repair=next(t['packet'] for t in FakeRuntime.turns if t['packet']['role']=='repair')
        assert repair['validation'][0]['failure_excerpt']=='fixture assertion failed'
        assert len(FakeRuntime.turns)==3
    finally:runner.close()


def test_interruption_resume(cfg):
    FakeRuntime.interrupt=True
    runner=Runner(cfg,runtime_factory=FakeRuntime,emit=lambda _:None)
    try:
        first=runner.run('demo')[0]; assert first['state']=='PAUSED'
        FakeRuntime.interrupt=False
        resumed=runner.resume(first['id'])
        assert resumed['state']=='READY_LOCAL'
        assert resumed['data']['repairs']==0
    finally:runner.close()


def test_foreign_change_on_resume(cfg):
    FakeRuntime.interrupt=True
    runner=Runner(cfg,runtime_factory=FakeRuntime,emit=lambda _:None)
    try:
        r=runner.run('demo')[0]
        Path(r['data']['worktree'],'clamp.py').write_text('foreign change')
        with pytest.raises(Stop,match='outside Factory'):runner.resume(r['id'])
        assert Path(r['data']['worktree'],'clamp.py').read_text()=='foreign change'
    finally:runner.close()


def test_two_claims_and_live_expired_lease(cfg):
    a=Store(cfg['state_dir']);b=Store(cfg['state_dir'])
    try:
        x=a.create('demo','key',{}); a.claim(x)
        with pytest.raises(Stop,match='global'): b.claim(x)
        a.db.execute('UPDATE lease SET heartbeat=0');a.db.commit();a.release_lock()
        with pytest.raises(Stop,match='live process'):b.claim(x,recovering=True)
    finally:a.release(x);a.close();b.close()


def test_dead_lease_requires_explicit_resume(cfg):
    s=Store(cfg['state_dir'])
    try:
        x=s.create('demo','key',{});s.claim(x)
        s.db.execute('UPDATE lease SET pid=99999999,identity="old"');s.db.commit();s.release_lock()
        y=s.create('demo','other',{})
        with pytest.raises(Stop,match='Resume'):s.claim(y)
        s.claim(x,recovering=True)
        assert s.db.execute('SELECT run_id FROM lease').fetchone()[0]==x
    finally:s.release(x);s.close()


def test_issues_disabled_uses_file_authority(cfg):
    plan=resolve(cfg,'demo')
    assert plan['issues_enabled'] is False and plan['task']['source']['kind']=='file'


def test_missing_checks_and_plugin_handoff(cfg):
    cfg['projects']['demo']['final_checks']=[]
    assert resolve(cfg,'demo')['state']=='NATIVE_HANDOFF'


def test_contract_cannot_inject_commands():
    value={'id':'x','description':'x','acceptance':'x','paths':['x'],'checks':['test'],'command':'curl evil'}
    with pytest.raises(Stop,match='unsupported'):parse_contract('```factory-task\n'+json.dumps(value)+'\n```')


def test_remote_identity():
    assert repository_id('git@github.com:dkharlanau/vedokrok.git')=='dkharlanau/vedokrok'
    assert repository_id('https://evil.example/dkharlanau/vedokrok.git') is None


def test_missing_github_policy():
    with pytest.raises(Stop,match='fallback'):GitHub('dkharlanau/vedokrok',False)


def test_ambiguous_pr_creation_reconciles_before_retry(tmp_path,monkeypatch):
    gh=object.__new__(GitHub);gh.repository='owner/repo'
    responses=[None,{'url':'https://github.com/owner/repo/pull/1','state':'OPEN'}]
    gh.find_pr=lambda branch:responses.pop(0)
    calls=[]
    class R:returncode=1
    monkeypatch.setattr('devfactory.repository.command',lambda argv,**kw:(calls.append(argv) or R()))
    pr=gh.ensure_pr('codex/factory-x','main',tmp_path/'body','Title',tmp_path)
    assert pr['state']=='OPEN' and len(calls)==1
    # Crash after remote creation / before local receipt: next run discovers existing PR.
    gh.find_pr=lambda branch:pr
    assert gh.ensure_pr('codex/factory-x','main',tmp_path/'body','Title',tmp_path)==pr
    assert len(calls)==1


def test_queue_two_independent_tasks(cfg):
    repo=Path(cfg['projects']['demo']['path'])
    from devfactory.fixture import TASK
    t=copy.deepcopy(TASK);t.update(id='second',priority=2,description='Create bounded independent note.',
                                   acceptance='Create second.txt.',paths=['second.txt'],checks=['note'])
    with (repo/'BACKLOG.md').open('a') as f:f.write('\n```factory-task\n'+json.dumps(t)+'\n```\n')
    git(repo,'add','BACKLOG.md');git(repo,'-c','user.name=Fixture','-c','user.email=f@localhost','commit','-qm','Second independent task')
    cfg['projects']['demo']['base_sha']=git(repo,'rev-parse','HEAD')
    cfg['projects']['demo']['checks']['note']=[os.sys.executable,'-c',
        'from pathlib import Path; assert Path("second.txt").read_text()=="fixture change\\n"']
    cfg['projects']['demo']['checks']['pass']=[os.sys.executable,'-c','pass']
    cfg['projects']['demo']['final_checks']=['pass']
    cfg['budget']['max_turns']=2
    cfg['budget']['max_queue_turns']=4
    runner=Runner(cfg,runtime_factory=FakeRuntime,emit=lambda _:None)
    try:
        results=runner.run('demo',max_tasks=2)
        assert len(results)==2 and all(r['state']=='READY_LOCAL' for r in results)
        assert len({r['data']['worktree'] for r in results})==2
        assert Path(results[1]['data']['worktree'],'second.txt').read_text()=='fixture change\n'
    finally:runner.close()


def test_queue_overlap_hands_off_before_second_model_turn(cfg):
    repo=Path(cfg['projects']['demo']['path'])
    from devfactory.fixture import TASK
    t=copy.deepcopy(TASK);t['id']='overlap';t['priority']=2
    with (repo/'BACKLOG.md').open('a') as f:f.write('\n```factory-task\n'+json.dumps(t)+'\n```\n')
    git(repo,'add','BACKLOG.md');git(repo,'-c','user.name=Fixture','-c','user.email=f@localhost','commit','-qm','Overlapping task')
    cfg['projects']['demo']['base_sha']=git(repo,'rev-parse','HEAD')
    runner=Runner(cfg,runtime_factory=FakeRuntime,emit=lambda _:None)
    try:
        results=runner.run('demo',max_tasks=2)
        assert results[0]['state']=='READY_LOCAL'
        assert results[1]['state']=='NATIVE_HANDOFF'
        assert 'overlaps' in results[1]['reason']
        assert len(FakeRuntime.turns)==2
    finally:runner.close()


def test_scope_overlap_detects_parent_child_paths():
    from devfactory.runner import scopes_overlap
    assert scopes_overlap(['src'],['src/feature/file.py'])
    assert scopes_overlap(['src/feature/file.py'],['src'])
    assert not scopes_overlap(['src/a'],['src/b'])


def test_changed_completed_contract_does_not_duplicate_branch(cfg):
    runner=Runner(cfg,runtime_factory=FakeRuntime,emit=lambda _:None)
    try:
        result=runner.run('demo')[0];assert result['state']=='READY_LOCAL'
        repo=Path(cfg['projects']['demo']['path'])
        p=repo/'BACKLOG.md';p.write_text(p.read_text().replace('Implement inclusive integer','Implement inclusive numeric'))
        git(repo,'add','BACKLOG.md');git(repo,'-c','user.name=Fixture','-c','user.email=f@localhost','commit','-qm','Changed authority')
        cfg['projects']['demo']['base_sha']=git(repo,'rev-parse','HEAD')
        next_run=runner.run('demo')[0]
        assert next_run['state']=='NATIVE_HANDOFF'
        assert len(runner.store.all())==1
    finally:runner.close()


def test_missing_plugin_contract_handoff(cfg):
    repo=Path(cfg['projects']['demo']['path']);p=repo/'BACKLOG.md'
    p.write_text(p.read_text().replace('"python"','"desktop-only-plugin"'))
    git(repo,'add','BACKLOG.md');git(repo,'-c','user.name=Fixture','-c','user.email=f@localhost','commit','-qm','Plugin requirement')
    cfg['projects']['demo']['base_sha']=git(repo,'rev-parse','HEAD')
    assert resolve(cfg,'demo')['state']=='NATIVE_HANDOFF'


def test_validation_infrastructure_failure_does_not_escalate(cfg):
    class MissingRunner(FakeRuntime):
        def command(self,*a,**kw):return {'exitCode':127,'stdout':'','stderr':'missing tool'}
    runner=Runner(cfg,runtime_factory=MissingRunner,emit=lambda _:None)
    try:
        r=runner.run('demo')[0]
        assert r['state']=='BLOCKED_INFRASTRUCTURE'
        assert r['data']['escalations']==0 and r['data']['repairs']==0
    finally:runner.close()


def test_dependency_must_be_merged(monkeypatch):
    gh=object.__new__(GitHub);gh.repository='owner/repo'
    gh.json=lambda *a:{'state':'CLOSED','mergedAt':None,'headRefOid':'a'}
    assert gh.dependency(1) is False
    gh.json=lambda *a:{'state':'OPEN','mergedAt':None,'headRefOid':'a'}
    assert gh.dependency(1) is False
    gh.json=lambda *a:{'state':'MERGED','mergedAt':'2026-09-26','headRefOid':'a'}
    assert gh.dependency(1) is True
