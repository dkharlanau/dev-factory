"""Faults corresponding to normal development; no model or GitHub writes."""
import json
import subprocess
import sys
from pathlib import Path
import pytest
from devfactory.policy import Stop
from devfactory.repository import git
from devfactory.runner import Runner
from devfactory.state import Store
from fakes import FakeRuntime

PASS={'verdict':'PASS','findings':[],'summary':'pass'}
REPAIR={'verdict':'REPAIR','findings':[{'file':'clamp.py','line':2,'summary':'Handle inverted bounds'}],'summary':'repair'}


def test_review_rejection_repairs_then_fresh_review(cfg):
    FakeRuntime.outcomes=[PASS,REPAIR,PASS,PASS]
    r=Runner(cfg,runtime_factory=FakeRuntime,emit=lambda _:None)
    try:
        out=r.run('demo')[0];d=out['data']
        assert out['state']=='READY_LOCAL'
        assert d['repairs']==1 and d['escalations']==0 and len(d['turns'])==4
        assert FakeRuntime.turns[2]['packet']['concrete_findings']==REPAIR['findings']
        assert FakeRuntime.turns[1]['thread']!=FakeRuntime.turns[3]['thread']
        assert r.run('demo')[0]['state']=='EXISTING_COMPLETION'
        assert len(FakeRuntime.turns)==4
    finally:r.close()


def test_completed_commit_survives_validation_transport_failure(cfg,monkeypatch):
    cfg['integration'].update(push=True,pull_request=True)
    class Failure(FakeRuntime):
        failed=False
        def command(self,*a,**kw):
            if not self.failed:
                type(self).failed=True
                raise Stop('BLOCKED_INFRASTRUCTURE','Controlled validation transport error')
            return super().command(*a,**kw)
    # Test local commit/validate/review reconciliation; never contacts GitHub.
    monkeypatch.setattr(Runner,'_integrate',lambda *_:None)
    r=Runner(cfg,runtime_factory=Failure,emit=lambda _:None)
    try:
        first=r.run('demo')[0]
        assert first['state']=='BLOCKED_INFRASTRUCTURE'
        wt=Path(first['data']['worktree']);head=git(wt,'rev-parse','HEAD')
        assert head!=first['data']['base_sha'] and git(wt,'status','--porcelain')==''
        recovered=r.resume(first['id'])
        assert recovered['state']=='READY_LOCAL'
        assert git(wt,'rev-parse','HEAD')==head
        assert len(FakeRuntime.turns)==2 # original builder plus one fresh reviewer
    finally:r.close()


def test_actual_process_death_preserves_lease_until_explicit_recovery(tmp_path):
    state=tmp_path/'state';s=Store(state)
    a=s.create('test','task-a',{});b=s.create('test','task-b',{})
    code='from devfactory.state import Store; import os,sys; s=Store(sys.argv[1]);s.claim(sys.argv[2]);os._exit(0)'
    import os
    env=dict(os.environ,PYTHONPATH=str(Path(__file__).resolve().parents[1]/'src'))
    subprocess.run([sys.executable,'-c',code,str(state),a],env=env,check=True)
    try:
        with pytest.raises(Stop,match='Resume abandoned'):s.claim(b)
        s.release_lock()
        s.claim(a,recovering=True)
        assert s.db.execute('SELECT run_id FROM lease').fetchone()[0]==a
    finally:s.release(a);s.close()


def test_receipt_active_time_excludes_pause_and_keeps_role_metrics(cfg):
    FakeRuntime.interrupt=True
    r=Runner(cfg,runtime_factory=FakeRuntime,emit=lambda _:None)
    try:
        first=r.run('demo')[0]
        assert first['state']=='PAUSED'
        assert first['data']['active_execution_complete'] is False
        data=first['data'];data['started_at']-=3600 # simulated offline hour, no real waiting
        r.store.save(first['id'],first['state'],data)
        FakeRuntime.interrupt=False
        final=r.resume(first['id']);d=final['data']
        assert final['state']=='READY_LOCAL'
        assert d['active_execution_complete'] is True
        assert d['wall_seconds']-d['active_execution_seconds']>=3599
        assert all(t['elapsed_seconds']>=0 and t['packet_utf8_bytes']>0 for t in d['turns'])
        assert d['turns'][-1]['verdict']=='PASS'
        assert d['tests'][-1]['elapsed_seconds']>=0
    finally:r.close()


def test_automatic_compaction_policy_is_explicit_and_bounded(tmp_path):
    from devfactory.config import load
    config=tmp_path/'local.toml';config.write_text('[context]\nfactory_auto_compaction = true\ncompact_after_builder_turns = 0\n')
    with pytest.raises(Stop,match='compact_after_builder_turns'):load(tmp_path,config)


def test_missing_compaction_usage_does_not_double_charge_next_role():
    from devfactory.runner import role_usage
    rows=[{'role':'build','thread_id':'a','usage':{'total':{'totalTokens':100}}},
          {'role':'compaction','thread_id':'a','usage':None},
          {'role':'repair','thread_id':'a','usage':{'total':{'totalTokens':160}}},
          {'role':'review','thread_id':'b','usage':{'total':{'totalTokens':25}}}]
    usage=role_usage(rows)
    assert usage['build']['totalTokens']==100
    assert usage['compaction']['totalTokens'] is None
    assert usage['repair']['totalTokens'] is None # unknown split across compaction/repair
    assert usage['review']['totalTokens']==25


def test_known_v31_checkpoint_matches_only_compaction_policy_migration(cfg):
    from copy import deepcopy
    from devfactory.runner import config_fingerprint,legacy_compaction_config_fingerprint
    old=deepcopy(cfg)
    old['policy_version']='3.1'
    for key in ('factory_auto_compaction','compact_after_builder_turns','compact_min_remaining_tokens'):
        old['context'].pop(key,None)
    old['context']['manual_compaction']=False
    assert legacy_compaction_config_fingerprint(cfg,'demo')==config_fingerprint(old,'demo')
    changed=deepcopy(cfg);changed['budget']['max_turns']-=1
    assert legacy_compaction_config_fingerprint(changed,'demo')!=config_fingerprint(old,'demo')
