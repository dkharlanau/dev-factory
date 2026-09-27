import copy
import json
import os
import time
from pathlib import Path
import pytest
from devfactory.state import Store,digest
from devfactory.policy import Stop
from devfactory.runner import Runner,failure_excerpt,validation_output,validation_infrastructure_failure
from devfactory.tasks import resolve,parse_contract
from devfactory.repository import git,GitHub,repository_id,snapshot
from fakes import FakeRuntime


def test_failure_diagnostics_keep_stdout_error_despite_stderr_warning_flood():
    result={'exitCode':1,'stdout':'lint passed\nApp.test.tsx: error TS2493: tuple has no element at index 0',
            'stderr':'first warning\n'+('unrelated CSS warning\n'*2000)+'last warning'}
    for limit in (1600,12000):
        text=validation_output(result,limit)
        assert 'error TS2493' in text
        assert 'first warning' in text and 'last warning' in text
        assert len(text.encode('utf-8'))<=limit
    assert failure_excerpt(result)==validation_output(result,1600)


def test_failure_diagnostics_redact_before_truncating_and_bound_unicode_bytes():
    result={'exitCode':1,'stdout':'fatal source diagnostic\n'+('Ошибка 🎙️\n'*1000)+'\npassword=private-value\nstdout end',
            'stderr':'Bearer token-hidden-from-receipts\n'+('warning\n'*1000)+'stderr end'}
    for limit in (0,1,25,1600,12000):
        text=validation_output(result,limit)
        assert len(text.encode('utf-8'))<=limit
        assert 'private-value' not in text and 'token-hidden' not in text
    text=failure_excerpt(result)
    assert 'fatal source diagnostic' in text
    assert 'stdout end' in text and 'stderr end' in text
    assert '[REDACTED]' in text
    assert failure_excerpt({'exitCode':0,**{k:v for k,v in result.items() if k!='exitCode'}}) is None


def test_failed_check_log_and_repair_packet_preserve_each_stream(cfg):
    class WarningFloodRuntime(FakeRuntime):
        def command(self,*args,**kwargs):
            return {'exitCode':1,'stdout':'App.test.tsx: error TS2493: invalid mock tuple',
                    'stderr':'first warning\n'+('unrelated warning\n'*2000)+'last warning'}
    runner=Runner(cfg,runtime_factory=WarningFloodRuntime,emit=lambda _:None)
    try:
        run=runner.run('demo')[0]
        failed=run['data']['tests'][0]
        log=Path(failed['log'])
        assert 'error TS2493' in log.read_text()
        assert log.stat().st_size<=cfg['context']['failure_log_bytes']
        assert log.stat().st_mode & 0o777==0o600
        repair=next(t['packet'] for t in FakeRuntime.turns if t['packet']['role']=='repair')
        assert 'error TS2493' in repair['validation'][0]['failure_excerpt']
    finally:runner.close()


@pytest.mark.parametrize('address',['127.0.0.1','::1'])
def test_denied_local_test_listener_stops_without_source_repair(cfg,address):
    class DeniedListenerRuntime(FakeRuntime):
        def command(self,*args,**kwargs):
            return {'exitCode':1,'stdout':'build passed',
                    'stderr':f'Error: listen EPERM: operation not permitted {address}'}
    runner=Runner(cfg,runtime_factory=DeniedListenerRuntime,emit=lambda _:None)
    try:
        run=runner.run('demo')[0]
        assert run['state']=='BLOCKED_INFRASTRUCTURE'
        assert 'loopback test listener' in run['data']['reason']
        assert run['data']['repairs']==0
        assert len(FakeRuntime.turns)==1
        assert run['data']['tests'][0]['infrastructure_reason']
    finally:runner.close()


def test_port_collision_and_nonnetwork_permission_errors_remain_source_diagnostics():
    for output in ['Error: listen EADDRINUSE: address already in use 127.0.0.1',
                   'Error: EPERM: operation not permitted, open example.txt']:
        assert validation_infrastructure_failure({'exitCode':1,'stderr':output}) is None
    assert validation_infrastructure_failure({'exitCode':0,'stderr':'Error: listen EPERM: operation not permitted 127.0.0.1'}) is None


def test_checkpoint_git_failure_still_persists_blocked_state(cfg,monkeypatch):
    from devfactory import runner as module
    original=module.fingerprint
    broken=False
    cfg['projects']['demo']['setup_checks']=['setup']
    cfg['projects']['demo']['checks']['setup']=['fixture-setup']
    class SnapshotFailureRuntime(FakeRuntime):
        def command(self,*args,**kwargs):
            nonlocal broken
            broken=True
            return {'exitCode':1,'stdout':'fixture setup failed','stderr':''}
    def fingerprint(*args):
        if broken:raise Stop('BLOCKED_INFRASTRUCTURE','TimeoutExpired: git')
        return original(*args)
    monkeypatch.setattr(module,'fingerprint',fingerprint)
    runner=Runner(cfg,runtime_factory=SnapshotFailureRuntime,emit=lambda _:None)
    try:
        run=runner.run('demo')[0]
        assert run['state']=='BLOCKED_INFRASTRUCTURE'
        assert runner.store.get(run['id'])['state']=='BLOCKED_INFRASTRUCTURE'
        assert 'checkpoint snapshot unavailable' in run['data']['reason']
        assert run['data']['checkpoint_snapshot_error']['reason']=='TimeoutExpired: git'
        checkpoint=json.loads((Path(cfg['state_dir'])/'runs'/run['id']/'checkpoint.json').read_text())
        assert checkpoint['checkpoint_snapshot_error']
        assert not FakeRuntime.turns
        broken=False
        with pytest.raises(Stop,match='native source reconciliation'):
            runner.resume(run['id'])
    finally:runner.close()


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


@pytest.mark.parametrize('local_change',[None,'edit','delete','committed'])
def test_stale_clean_authority_uses_current_base_but_preserves_local_changes(cfg,local_change):
    repo=Path(cfg['projects']['demo']['path'])
    old=git(repo,'rev-parse','HEAD')
    guide=repo/'AGENTS.md'
    guide.write_text(guide.read_text()+'Current remote guidance.\n')
    git(repo,'add','AGENTS.md')
    git(repo,'-c','user.name=Fixture','-c','user.email=f@localhost','commit','-qm','New remote authority')
    cfg['projects']['demo']['base_sha']=git(repo,'rev-parse','HEAD')
    git(repo,'switch','--detach',old)
    if local_change in ('edit','committed'): guide.write_text('Local owner decision.\n')
    if local_change=='delete': guide.unlink()
    if local_change=='committed':
        git(repo,'add','AGENTS.md')
        git(repo,'-c','user.name=Fixture','-c','user.email=f@localhost','commit','-qm','Local authority')
    head=git(repo,'rev-parse','HEAD')
    content=guide.read_text() if guide.exists() else None
    plan=resolve(cfg,'demo')
    if local_change is None:
        assert plan['state']=='EXECUTE' and plan['dirty_authority']==[]
    else:
        assert plan['state']=='NATIVE_HANDOFF' and plan['dirty_authority']==['AGENTS.md']
    assert git(repo,'rev-parse','HEAD')==head
    assert (guide.read_text() if guide.exists() else None)==content


@pytest.mark.parametrize('blocker',['branch-policy','missing-contract'])
def test_handoff_does_not_inventory_cold_history(cfg,monkeypatch,blocker):
    repo=Path(cfg['projects']['demo']['path'])
    if blocker=='branch-policy': (repo/'AGENTS.md').write_text('Work only on main.\n')
    else: (repo/'BACKLOG.md').write_text('EXECUTE: current work without a bounded contract.\n')
    git(repo,'add','AGENTS.md','BACKLOG.md')
    git(repo,'-c','user.name=Fixture','-c','user.email=f@localhost','commit','-qm','Handoff authority')
    cfg['projects']['demo']['base_sha']=git(repo,'rev-parse','HEAD')
    monkeypatch.setattr('devfactory.tasks.ensure_profile',lambda *args:pytest.fail('Unexecutable plan must not scan history'))
    assert resolve(cfg,'demo')['state']=='NATIVE_HANDOFF'


def test_repair_uses_delta_packet_and_stronger_review(cfg):
    assert cfg['context']['factory_auto_compaction'] is False
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
        assert FakeRuntime.compactions==[]
        build=next(t for t in FakeRuntime.turns if t['packet']['role']=='build')['packet']
        repair=next(t for t in FakeRuntime.turns if t['packet']['role']=='repair')['packet']
        assert set(build['task'])=={'id','description','acceptance','paths'}
        assert build['guidance_files']==['AGENTS.md']
        assert 'BACKLOG.md' not in build['guidance_files']
        assert 'task' in build and 'task' not in repair and repair['task_id']=='clamp-v1'
        assert 'acceptance' not in repair # persistent builder thread already owns the immutable contract
        assert len(json.dumps(repair,separators=(',',':'))) < len(json.dumps(build,separators=(',',':')))
        build_turn=next(t for t in FakeRuntime.turns if t['packet']['role']=='build')
        repair_turn=next(t for t in FakeRuntime.turns if t['packet']['role']=='repair')
        assert build_turn['thread']==repair_turn['thread']
        assert len(FakeRuntime.history)==3 # build + two fresh reviews; repair needs no thread/resume RPC
        assert FakeRuntime.history[-1]['profile']=='deep'
        assert r['data']['efficiency']['packet_utf8_bytes_avoided'] > 0
        assert r['data']['efficiency']['thread_resume_calls_avoided']==1
    finally: runner.close()


def test_opted_in_repair_compacts_from_durable_checkpoint_and_reanchors_contract(cfg):
    FakeRuntime.outcomes=[
        {'verdict':'PASS','findings':[],'summary':'build'},
        {'verdict':'REPAIR','findings':[{'file':'clamp.py','line':1,'summary':'tighten implementation'}],'summary':'repair'},
        {'verdict':'PASS','findings':[],'summary':'repaired'},
        {'verdict':'PASS','findings':[],'summary':'reviewed'},
    ]
    assert cfg['context']['factory_auto_compaction'] is False
    cfg['context']['factory_auto_compaction']=True
    assert cfg['context']['compact_after_builder_turns']==1
    runner=Runner(cfg,runtime_factory=FakeRuntime,emit=lambda _:None)
    try:
        result=runner.run('demo')[0]; data=result['data']
        assert result['state']=='READY_LOCAL'
        assert len(FakeRuntime.compactions)==1
        compaction=FakeRuntime.compactions[0]
        checkpoint=compaction['checkpoint']
        assert compaction['thread']==data['builder_thread']
        assert checkpoint['next_action']=='repair'
        assert checkpoint['contract_hash']==data['contract_hash']
        assert checkpoint['changed_files']==['clamp.py']
        assert checkpoint['source_fingerprint']
        assert 'instructions' not in checkpoint and 'conversation' not in checkpoint
        assert data['compactions'][0]['state']=='COMPLETED'
        assert data['turns'][2]['role']=='compaction' and data['turns'][2]['usage_telemetry']=='unknown'
        repair_record=next(t for t in data['turns'] if t['role']=='repair')
        repair_packet=next(t['packet'] for t in FakeRuntime.turns if t['packet']['role']=='repair')
        assert repair_record['packet_mode']=='delta+contract'
        assert repair_packet['task']['acceptance']==data['task_contract']['acceptance']
        assert [t['packet']['role'] for t in FakeRuntime.turns]==['build','review','repair','review']
        assert FakeRuntime.turns[0]['thread']==FakeRuntime.turns[2]['thread']
        assert FakeRuntime.turns[1]['thread']!=FakeRuntime.turns[3]['thread']
        assert data['usage_by_role']['compaction']['totalTokens'] is None
        assert data['usage_by_role']['repair']['totalTokens'] is None
    finally: runner.close()


def test_auto_compaction_reserves_token_and_turn_budget(cfg):
    from devfactory.runner import compaction_due
    from devfactory.policy import Usage
    cfg['context']['compact_after_builder_turns']=1
    cfg['context']['factory_auto_compaction']=True
    data={'builder_thread':'b','turns':[{'thread_id':'b','role':'build'}],
          'remaining_turns':6,'remaining_tokens':500000}
    usage=Usage({'b':{'totalTokens':1000}})
    assert compaction_due(data,cfg['context'],usage)==(True,'repair-checkpoint')
    data['remaining_turns']=3
    assert compaction_due(data,cfg['context'],usage)==(False,'completion-turn-reserve')
    data['remaining_turns']=6;data['remaining_tokens']=1000
    assert compaction_due(data,cfg['context'],usage)==(False,'completion-token-reserve')
    assert compaction_due(data,cfg['context'],Usage())==(False,'token-usage-unknown')


def test_ambiguous_compaction_preserves_repair_checkpoint_and_hands_off(cfg):
    from devfactory.policy import Stop
    FakeRuntime.outcomes=[
        {'verdict':'PASS','findings':[],'summary':'build'},
        {'verdict':'REPAIR','findings':[{'file':'clamp.py','line':1,'summary':'tighten implementation'}],'summary':'repair'},
    ]
    cfg['context']['compact_after_builder_turns']=1
    cfg['context']['factory_auto_compaction']=True
    class LostCompactionResult(FakeRuntime):
        def compact(self,tid,*,deadline,checkpoint,on_event=lambda *_:None,on_start=lambda *_:None):
            on_start({'previous_turn_ids':[]})
            raise Stop('BLOCKED_RUNTIME','connection ended after compaction dispatch')
    runner=Runner(cfg,runtime_factory=LostCompactionResult,emit=lambda _:None)
    try:
        result=runner.run('demo')[0]; data=result['data']
        assert result['state']=='NATIVE_HANDOFF'
        assert data['in_flight']['role']=='compaction'
        assert len(FakeRuntime.turns)==2
        checkpoint=Path(data['compactions'][0]['checkpoint'])
        assert checkpoint.is_file()
        saved=json.loads(checkpoint.read_text())
        assert saved['source_fingerprint'] and saved['next_action']=='repair'
        assert (Path(data['worktree'])/'clamp.py').is_file()
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
        assert [t['profile'] for t in FakeRuntime.turns]==['fast','standard','deep']
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
        assert any(h['resume'] is not None for h in FakeRuntime.history)
    finally:runner.close()


def test_explicit_handoff_revalidation_refreshes_evidence_without_resetting_repair_budget(cfg):
    FakeRuntime.fail_tests=True
    FakeRuntime.outcomes=[{'verdict':'PASS','findings':[],'summary':'built'},
                          {'verdict':'BLOCKED','findings':[],'summary':'diagnostic unavailable'}]
    runner=Runner(cfg,runtime_factory=FakeRuntime,emit=lambda _:None)
    try:
        first=runner.run('demo')[0]
        assert first['state']=='NATIVE_HANDOFF'
        assert first['data']['repairs']==1
        FakeRuntime.fail_tests=False
        resumed=runner.resume(first['id'],revalidate=True)
        assert resumed['state']=='READY_LOCAL'
        assert resumed['data']['operator_revalidations']==1
        assert resumed['data']['repairs']==first['data']['repairs']
        assert resumed['data']['failures']==first['data']['failures']
        assert [t['exit_code'] for t in resumed['data']['tests']]==[1,0]
        assert [t['packet']['role'] for t in FakeRuntime.turns]==['build','repair','review']
        with pytest.raises(Stop,match='idle validation handoff'):
            runner.resume(first['id'],revalidate=True)
    finally:runner.close()


def test_revalidation_still_rejects_foreign_source_changes(cfg):
    FakeRuntime.fail_tests=True
    FakeRuntime.outcomes=[{'verdict':'PASS','findings':[],'summary':'built'},
                          {'verdict':'BLOCKED','findings':[],'summary':'diagnostic unavailable'}]
    runner=Runner(cfg,runtime_factory=FakeRuntime,emit=lambda _:None)
    try:
        first=runner.run('demo')[0]
        Path(first['data']['worktree'],'clamp.py').write_text('foreign change')
        with pytest.raises(Stop,match='outside Factory'):
            runner.resume(first['id'],revalidate=True)
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


def test_local_plan_resume_never_refreshes_github_or_original_checkout(cfg,monkeypatch):
    from devfactory import runner as module
    FakeRuntime.interrupt=True
    runner=Runner(cfg,runtime_factory=FakeRuntime,emit=lambda _:None)
    try:
        first=runner.run('demo')[0]
        plan_path=Path(cfg['state_dir'])/'runs'/first['id']/'plan.json'
        assert plan_path.is_file()
        original_snapshot=module.snapshot
        original_path=Path(cfg['projects']['demo']['path'])
        def local_snapshot(path,*args,**kwargs):
            assert Path(path)!=original_path, 'Original checkout must not be replanned'
            return original_snapshot(path,*args,**kwargs)
        def unavailable(*args,**kwargs):raise AssertionError('Remote planning must not run')
        monkeypatch.setattr(module,'snapshot',local_snapshot)
        monkeypatch.setattr(GitHub,'refresh',unavailable)
        monkeypatch.setattr('devfactory.tasks.tracked_authority',
                            lambda *_:pytest.fail('Local resume must use the pinned worktree authority'))
        runner.planner=unavailable
        FakeRuntime.interrupt=False
        result=runner.resume(first['id'],local_plan=plan_path)
        assert result['state']=='READY_LOCAL'
        assert result['data']['authority_mode']=='local_snapshot'
        assert result['data']['remote_freshness']=='not_refreshed'
        assert result['data']['review']=='PASS'
        assert result['data']['remaining_turns']==first['data']['remaining_turns']
        assert FakeRuntime.history[-1]['resume'] is None
    finally:runner.close()


@pytest.mark.parametrize('change',['contract','checks','aggregate','authority','base','foreign','config','integration'])
def test_local_resume_keeps_contract_authority_source_and_integration_gates(cfg,change):
    FakeRuntime.interrupt=True
    runner=Runner(cfg,runtime_factory=FakeRuntime,emit=lambda _:None)
    try:
        first=runner.run('demo')[0]
        path=Path(cfg['state_dir'])/'runs'/first['id']/'plan.json'
        plan=json.loads(path.read_text())
        if change=='contract':plan['tasks'][0]['acceptance']='Skip required checks'
        elif change=='checks':plan['tasks'][0]['checks']=[]
        elif change=='aggregate':plan['task']['paths']=['.']
        elif change=='authority':plan['authority']=[]
        elif change=='base':plan['base_sha']='0'*40
        elif change=='foreign':Path(first['data']['worktree'],'clamp.py').write_text('foreign work')
        elif change=='config':cfg['projects']['demo']['checks']['new']=['true']
        elif change=='integration':
            # A matching checkpoint must still refuse network integration in local mode.
            from devfactory.runner import config_fingerprint
            cfg['integration']['push']=True
            first['data']['config_hash']=config_fingerprint(cfg,'demo')
            runner.store.save(first['id'],first['state'],first['data'])
        path.write_text(json.dumps(plan))
        before=len(FakeRuntime.turns)
        with pytest.raises(Stop):runner.resume(first['id'],local_plan=path)
        assert len(FakeRuntime.turns)==before
    finally:runner.close()


def test_local_plan_revalidation_preserves_budgets_and_runs_fresh_review(cfg):
    FakeRuntime.fail_tests=True
    FakeRuntime.outcomes=[{'verdict':'PASS','findings':[],'summary':'built'},
                          {'verdict':'BLOCKED','findings':[],'summary':'environment missing'}]
    runner=Runner(cfg,runtime_factory=FakeRuntime,emit=lambda _:None)
    try:
        first=runner.run('demo')[0]
        path=Path(cfg['state_dir'])/'runs'/first['id']/'plan.json'
        FakeRuntime.fail_tests=False
        runner.planner=lambda *a,**kw:pytest.fail('Local revalidation called remote planner')
        result=runner.resume(first['id'],local_plan=path,revalidate=True)
        assert result['state']=='READY_LOCAL'
        assert result['data']['repairs']==first['data']['repairs']
        assert result['data']['failures']==first['data']['failures']
        assert [t['exit_code'] for t in result['data']['tests']]==[1,0]
        assert [t['packet']['role'] for t in FakeRuntime.turns]==['build','repair','review']
    finally:runner.close()


def test_owner_network_grant_resumes_exact_run_and_is_receipted(cfg):
    from devfactory.runner import config_fingerprint
    cfg['projects']['demo']['network_access']=False
    FakeRuntime.interrupt=True
    runner=Runner(cfg,runtime_factory=FakeRuntime,emit=lambda _:None)
    try:
        first=runner.run('demo')[0]
        assert first['data']['sandbox_permissions']=={'network_access':False}
        plan=Path(cfg['state_dir'])/'runs'/first['id']/'plan.json'
        before=config_fingerprint(cfg,'demo')
        cfg['projects']['demo']['network_access']=True
        assert config_fingerprint(cfg,'demo')==before
        FakeRuntime.interrupt=False
        result=runner.resume(first['id'],local_plan=plan)
        assert result['state']=='READY_LOCAL'
        assert result['data']['sandbox_permissions']=={'network_access':True}
        changes=result['data']['sandbox_permission_changes']
        assert len(changes)==1
        assert {k:v for k,v in changes[0].items() if k!='at'}=={
            'capability':'network_access','from':False,'to':True,
            'source':'owner project configuration'}
        assert changes[0]['at']>0
        assert FakeRuntime.sandbox_permissions[-1]['network_access'] is True
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


def test_microbatch_runs_two_compatible_tasks_once(cfg):
    repo=Path(cfg['projects']['demo']['path'])
    from devfactory.fixture import TASK
    task=copy.deepcopy(TASK);task.update(id='second',priority=2,description='Create bounded independent note.',
                                       acceptance='Create second.txt.',paths=['second.txt'],checks=['note'])
    with (repo/'BACKLOG.md').open('a') as f:f.write('\n```factory-task\n'+json.dumps(task)+'\n```\n')
    git(repo,'add','BACKLOG.md');git(repo,'-c','user.name=Fixture','-c','user.email=f@localhost','commit','-qm','Second compatible task')
    cfg['projects']['demo']['base_sha']=git(repo,'rev-parse','HEAD')
    cfg['projects']['demo']['checks']['note']=[os.sys.executable,'-c',
        'from pathlib import Path; assert Path("second.txt").read_text()=="fixture change\\n"']
    cfg['projects']['demo']['checks']['pass']=[os.sys.executable,'-c','pass']
    cfg['projects']['demo']['final_checks']=['pass']
    runner=Runner(cfg,runtime_factory=FakeRuntime,emit=lambda _:None)
    try:
        results=runner.run('demo',max_tasks=2)
        assert len(results)==1 and results[0]['state']=='READY_LOCAL'
        d=results[0]['data']
        assert d['task_ids']==['clamp-v1','second']
        assert len(FakeRuntime.turns)==2
        assert Path(d['worktree'],'second.txt').read_text()=='fixture change\n'
        assert [x['check'] for x in d['tests']]==['unit','note','pass']
        assert all(x['log'] is None for x in d['tests'])
        turns=len(FakeRuntime.turns)
        again=runner.run('demo',max_tasks=1)
        assert again[0]['state']=='EXISTING_COMPLETION'
        assert len(FakeRuntime.turns)==turns
    finally:runner.close()

def test_new_run_skips_existing_completion_and_continues_backlog(cfg):
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
    runner=Runner(cfg,runtime_factory=FakeRuntime,emit=lambda _:None)
    try:
        first=runner.run('demo',max_tasks=1)
        assert first[-1]['state']=='READY_LOCAL'
        turns=len(FakeRuntime.turns)
        second=runner.run('demo',max_tasks=1)
        assert [x['state'] for x in second]==['EXISTING_COMPLETION','READY_LOCAL']
        assert len(FakeRuntime.turns)==turns+2
    finally: runner.close()


def test_related_overlap_is_batched_instead_of_split(cfg):
    repo=Path(cfg['projects']['demo']['path'])
    from devfactory.fixture import TASK
    task=copy.deepcopy(TASK);task['id']='overlap';task['priority']=2
    with (repo/'BACKLOG.md').open('a') as f:f.write('\n```factory-task\n'+json.dumps(task)+'\n```\n')
    git(repo,'add','BACKLOG.md');git(repo,'-c','user.name=Fixture','-c','user.email=f@localhost','commit','-qm','Overlapping compatible task')
    cfg['projects']['demo']['base_sha']=git(repo,'rev-parse','HEAD')
    runner=Runner(cfg,runtime_factory=FakeRuntime,emit=lambda _:None)
    try:
        results=runner.run('demo',max_tasks=2)
        assert len(results)==1 and results[0]['state']=='READY_LOCAL'
        assert results[0]['data']['task_ids']==['clamp-v1','overlap']
        assert len(FakeRuntime.turns)==2
        assert [x['check'] for x in results[0]['data']['tests']]==['unit']
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


def approved_authority(cfg):
    from devfactory.repository import tracked_authority
    repo=Path(cfg['projects']['demo']['path'])
    (repo/'AGENTS.md').write_text('Work only on `main`. Preserve tests.\n')
    git(repo,'add','AGENTS.md')
    git(repo,'-c','user.name=Fixture','-c','user.email=f@localhost','commit','-qm','Branch authority')
    adapter=cfg['projects']['demo']
    adapter['base_sha']=git(repo,'rev-parse','HEAD')
    (repo/'AGENTS.md').write_text('Local instructions to preserve.\n')
    initial=resolve(cfg,'demo')
    assert initial['state']=='NATIVE_HANDOFF'
    task=parse_contract((repo/'BACKLOG.md').read_text())[0]
    task['source']={'kind':'file','path':'BACKLOG.md','base_sha':adapter['base_sha']}
    adapter['authority_approval']={'base_sha':adapter['base_sha'],
        'authority_hash':digest(initial['authority']),'task_ids':[task['id']],
        'contract_hashes':[digest(task)],'isolated_branch':True,'remote_authority':True}
    return repo


def test_exact_owner_authority_exception_is_applied_and_recorded(cfg):
    repo=approved_authority(cfg)
    runner=Runner(cfg,runtime_factory=FakeRuntime,emit=lambda _:None)
    try:
        outcome=runner.run('demo')[0]
        assert outcome['state']=='READY_LOCAL',outcome
        assert outcome['data']['authority_approval']=={'isolated_branch':True,'remote_authority':True}
        assert all('Explicit owner exception' in h['instructions'] for h in FakeRuntime.history)
        assert (repo/'AGENTS.md').read_text()=='Local instructions to preserve.\n'
    finally:runner.close()


@pytest.mark.parametrize('field,value',[
    ('base_sha','stale'),('authority_hash','stale'),('task_ids',['other']),
    ('contract_hashes',['stale']),('isolated_branch','true'),('remote_authority',False),
])
def test_stale_or_incomplete_owner_exception_does_not_bypass_authority(cfg,field,value):
    approved_authority(cfg)
    cfg['projects']['demo']['authority_approval'][field]=value
    assert resolve(cfg,'demo')['state']=='NATIVE_HANDOFF'
    assert FakeRuntime.turns==[]


def test_task_cannot_supply_authority_exception():
    from devfactory.fixture import TASK
    task=dict(TASK,authority_approval={'isolated_branch':True})
    with pytest.raises(Stop,match='unsupported fields'):
        parse_contract('```factory-task\n'+json.dumps(task)+'\n```')


def test_setup_failure_spends_no_turn_and_can_resume_same_worktree(cfg):
    import sys
    adapter=cfg['projects']['demo']
    adapter['setup_checks']=['prepare']
    adapter['checks']['prepare']=[sys.executable,'-c','pass']
    class SetupRuntime(FakeRuntime):
        blocked=True
        setup_calls=0
        def command(self,cwd,argv,**kw):
            if argv==adapter['checks']['prepare']:
                self.__class__.setup_calls+=1
                if self.blocked:return {'exitCode':1,'stdout':'missing cached dependency','stderr':''}
            return super().command(cwd,argv,**kw)
    runner=Runner(cfg,runtime_factory=SetupRuntime,emit=lambda _:None)
    try:
        first=runner.run('demo')[0]
        assert first['state']=='BLOCKED_SETUP' and FakeRuntime.turns==[]
        assert first['data']['setup'][0]['failure_excerpt']=='missing cached dependency'
        SetupRuntime.blocked=False
        second=runner.resume(first['id'])
        assert second['state']=='READY_LOCAL',second
        assert first['data']['worktree']==second['data']['worktree']
        assert second['data']['setup_completed']==['prepare']
        assert SetupRuntime.setup_calls==2
    finally:runner.close()


def test_setup_cannot_silently_modify_source(cfg):
    import sys
    adapter=cfg['projects']['demo']
    adapter['setup_checks']=['prepare']
    adapter['checks']['prepare']=[sys.executable,'-c','from pathlib import Path; Path("clamp.py").write_text("changed")']
    runner=Runner(cfg,runtime_factory=FakeRuntime,emit=lambda _:None)
    try:
        result=runner.run('demo')[0]
        assert result['state']=='BLOCKED_SETUP' and FakeRuntime.turns==[]
        assert 'changed source' in result['data']['reason']
    finally:runner.close()


def test_setup_requires_owner_command_allowlist(cfg):
    cfg['projects']['demo']['setup_checks']=['unconfigured']
    assert resolve(cfg,'demo')['state']=='NATIVE_HANDOFF'
