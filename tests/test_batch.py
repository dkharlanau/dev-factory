import copy
import json
import os
import subprocess
from pathlib import Path

import pytest

from devfactory.batch import (compose_reviewed_slices, integrate_reviewed_batch,
                              review_composed_batch, validate_reviewed_slices)
from devfactory.fixture import TASK
from devfactory.policy import Stop
from devfactory.repository import fingerprint, git, tracked_authority, trigger_snapshot
from devfactory.runner import Runner
from devfactory.state import Store, digest
from fakes import FakeRuntime


def reviewed_pair(cfg):
    repo=Path(cfg['projects']['demo']['path'])
    second=copy.deepcopy(TASK)
    second.update(id='second',priority=2,description='Create bounded independent note.',
                  acceptance='Create second.txt.',paths=['second.txt'],checks=['note'])
    with (repo/'BACKLOG.md').open('a') as out:
        out.write('\n```factory-task\n'+json.dumps(second)+'\n```\n')
    git(repo,'add','BACKLOG.md')
    git(repo,'-c','user.name=Fixture','-c','user.email=f@localhost','commit','-qm','Batch second task')
    cfg['projects']['demo']['base_sha']=git(repo,'rev-parse','HEAD')
    cfg['projects']['demo']['checks']['note']=[os.sys.executable,'-c',
        'from pathlib import Path; assert Path("second.txt").read_text()=="fixture change\\n"']
    cfg['projects']['demo']['checks']['pass']=[os.sys.executable,'-c','pass']
    cfg['projects']['demo']['final_checks']=['pass']
    # Post-review composition exercises separately reviewed slices; pre-build micro-batching is disabled here.
    cfg['batching']['enabled']=False
    runner=Runner(cfg,runtime_factory=FakeRuntime,emit=lambda _:None)
    try:
        runs=runner.run('demo',max_tasks=2)
    finally:
        runner.close()
    assert [r['state'] for r in runs]==['READY_LOCAL','READY_LOCAL']
    return runs


def deferred_pair(cfg, *, second_override=None):
    repo=Path(cfg['projects']['demo']['path'])
    second=copy.deepcopy(TASK)
    second.update(id='second',priority=2,description='Create bounded independent note.',
                  acceptance='Create second.txt.',paths=['second.txt'],checks=['note'])
    second.update(second_override or {})
    with (repo/'BACKLOG.md').open('a') as out:
        out.write('\n```factory-task\n'+json.dumps(second)+'\n```\n')
    git(repo,'add','BACKLOG.md')
    git(repo,'-c','user.name=Fixture','-c','user.email=f@localhost','commit','-qm','Deferred second task')
    cfg['projects']['demo']['base_sha']=git(repo,'rev-parse','HEAD')
    cfg['projects']['demo']['checks']['note']=[os.sys.executable,'-c',
        'from pathlib import Path; assert Path("second.txt").read_text()=="fixture change\\n"']
    cfg['projects']['demo']['checks']['pass']=[os.sys.executable,'-c','pass']
    cfg['projects']['demo']['final_checks']=['pass']
    cfg['batching']['enabled']=False
    runner=Runner(cfg,runtime_factory=FakeRuntime,emit=lambda _:None)
    try: runs=runner.run('demo',max_tasks=2,defer_review=True)
    finally: runner.close()
    return runs


def test_deferred_cohort_needs_one_fresh_combined_review(cfg):
    runs=deferred_pair(cfg)
    assert [r['state'] for r in runs]==['REVIEW_DEFERRED_LOCAL']*2
    assert [t['packet']['role'] for t in FakeRuntime.turns]==['build','build']
    assert all(r['data']['acceptance'] is None and r['data']['review'] is None for r in runs)
    ordinary=Runner(cfg,runtime_factory=FakeRuntime,emit=lambda _:None)
    try: pending=ordinary.run('demo')[0]
    finally: ordinary.close()
    assert pending['state']=='REVIEW_PENDING' and len(FakeRuntime.turns)==2
    with pytest.raises(Stop,match='Phase A'):
        compose_reviewed_slices(runs,cfg['state_dir'])
    batch=compose_reviewed_slices(runs,cfg['state_dir'],deferred=True)
    assert batch['review_mode']=='deferred' and batch['model_turns']==0
    assert all(c['review_state']=='deferred' and c['validation_checks'] for c in batch['children'])
    result=review_composed_batch(cfg,batch,runtime_factory=FakeRuntime)
    assert result['state']=='BATCH_READY_LOCAL' and result['review']=='PASS'
    assert [t['packet']['role'] for t in FakeRuntime.turns]==['build','build','review']
    assert review_composed_batch(cfg,batch,runtime_factory=FakeRuntime)==result
    assert len(FakeRuntime.turns)==3


def test_deferred_composition_refuses_mutated_or_unclean_slice(cfg):
    runs=deferred_pair(cfg)
    first=copy.deepcopy(runs[0])
    first['data']['repairs']=1
    with pytest.raises(Stop,match='clean low/low/strong'):
        compose_reviewed_slices([first,runs[1]],cfg['state_dir'],deferred=True)
    first=copy.deepcopy(runs[0]);first['data']['risk']='high'
    with pytest.raises(Stop,match='clean low/low/strong'):
        compose_reviewed_slices([first,runs[1]],cfg['state_dir'],deferred=True)
    wt=Path(runs[0]['data']['worktree'])
    (wt/'clamp.py').write_text('changed after validation\n')
    with pytest.raises(Stop,match='changed after validation'):
        compose_reviewed_slices(runs,cfg['state_dir'],deferred=True)


def test_deferred_slice_can_fall_back_to_independent_review(cfg):
    runs=deferred_pair(cfg)
    runner=Runner(cfg,runtime_factory=FakeRuntime,emit=lambda _:None)
    try: result=runner.resume(runs[0]['id'],review_deferred=True)
    finally: runner.close()
    assert result['state']=='READY_LOCAL'
    assert result['data']['review']=='PASS' and result['data']['deferred_fallback_review']
    assert len(FakeRuntime.turns)==3


@pytest.mark.parametrize('override',[
    {'complexity':'high'},
    {'paths':['clamp.py']},
    {'verification':'weak'},
])
def test_deferred_preflight_refuses_unsafe_cohort_before_model_turn(cfg,override):
    with pytest.raises(Stop,match='Deferred-review'):
        deferred_pair(cfg,second_override=override)
    assert FakeRuntime.turns==[]


def test_builder_repair_signal_forces_per_slice_review(cfg):
    FakeRuntime.outcomes=[{'verdict':'REPAIR','findings':[{'file':'clamp.py','line':1,'summary':'Check carefully'}],
                           'summary':'Build uncertain'}]
    runs=deferred_pair(cfg)
    assert len(runs)==1 and runs[0]['state']=='READY_LOCAL'
    assert runs[0]['data']['builder_repair_signal'] is True
    assert [t['packet']['role'] for t in FakeRuntime.turns]==['build','review']


def test_deferred_combined_check_failure_spends_no_review_turn(cfg):
    runs=deferred_pair(cfg)
    batch=compose_reviewed_slices(runs,cfg['state_dir'],deferred=True)
    cfg['projects']['demo']['checks']['pass']=[os.sys.executable,'-c','raise SystemExit(1)']
    result=review_composed_batch(cfg,batch,runtime_factory=FakeRuntime)
    assert result['state']=='BLOCKED_BATCH_VALIDATION' and result['model_turns']==0
    assert [t['packet']['role'] for t in FakeRuntime.turns]==['build','build']


def test_deferred_combined_review_defect_blocks_acceptance(cfg):
    runs=deferred_pair(cfg)
    batch=compose_reviewed_slices(runs,cfg['state_dir'],deferred=True)
    FakeRuntime.outcomes=[{'verdict':'REPAIR','findings':[{'file':'clamp.py','line':1,'summary':'Incorrect edge case'}],
                           'summary':'Integration defect'}]
    result=review_composed_batch(cfg,batch,runtime_factory=FakeRuntime)
    assert result['state']=='BLOCKED_BATCH_REVIEW' and result['review']=='REPAIR'
    assert result['findings'][0]['file']=='clamp.py'


def test_compose_reviewed_slices_is_exact_and_idempotent(cfg):
    runs=reviewed_pair(cfg)
    turns=len(FakeRuntime.turns)
    batch=compose_reviewed_slices(runs,cfg['state_dir'])
    assert batch['state']=='COMPOSED_LOCAL' and batch['model_turns']==0
    assert batch['combined_files']==['clamp.py','second.txt']
    wt=Path(batch['worktree'])
    assert (wt/'second.txt').read_text()=='fixture change\n'
    assert git(wt,'rev-parse','HEAD')==batch['head_sha']
    assert git(wt,'status','--porcelain')==''
    check=subprocess.run([os.sys.executable,'-m','unittest','-v'],cwd=wt,capture_output=True,text=True)
    assert check.returncode==0,check.stderr
    repeat=compose_reviewed_slices(runs,cfg['state_dir'])
    assert repeat==batch and len(FakeRuntime.turns)==turns


class BatchGitHub:
    prs={}
    creates=0
    def __init__(self,repository,allowed):
        assert repository=='fixture/demo' and allowed
    def find_pr(self,branch):
        return self.prs.get(branch)
    def ensure_pr(self,branch,base,body_file,title,cwd):
        if branch not in self.prs:
            type(self).creates+=1
            self.prs[branch]={'number':1,'url':'https://github.com/fixture/demo/pull/1',
                              'state':'OPEN','isDraft':True,'baseRefName':base,
                              'headRefOid':git(cwd,'rev-parse','HEAD')}
        return self.prs[branch]


def reviewed_remote_batch(cfg,tmp_path):
    runs=reviewed_pair(cfg)
    batch=compose_reviewed_slices(runs,cfg['state_dir'])
    review=review_composed_batch(cfg,batch,runtime_factory=FakeRuntime)
    assert review['state']=='BATCH_READY_LOCAL'
    repo=Path(cfg['projects']['demo']['path'])
    remote=tmp_path/'remote.git'
    subprocess.run(['git','init','--bare','-q',str(remote)],check=True)
    git(repo,'remote','add','origin',str(remote))
    git(repo,'push','origin','main')
    adapter=cfg['projects']['demo']
    adapter.update(repository='fixture/demo',allow_gh=True)
    authority=tracked_authority(repo,batch['base_sha'],adapter['instructions'])
    adapter['batch_integration_approvals']={batch['batch_id']:{
        'batch_fingerprint':batch['combined_fingerprint'],'base_sha':batch['base_sha'],
        'trigger_hash':trigger_snapshot(batch['worktree'])['hash'],
        'authority_hash':digest([{'path':row['path'],'sha256':row['sha256']} for row in authority]),
        'triggers_reviewed':True,'spend_reviewed':True,'owner_restrictions_reviewed':True}}
    cfg['integration'].update(push=True,pull_request=True)
    BatchGitHub.prs={};BatchGitHub.creates=0
    return batch,remote


def test_batch_remote_integration_opens_one_draft_pr_and_reuses_receipt(cfg,tmp_path):
    batch,remote=reviewed_remote_batch(cfg,tmp_path)
    turns=len(FakeRuntime.turns)
    result=integrate_reviewed_batch(cfg,batch,github_factory=BatchGitHub)
    assert result['state']=='BATCH_PR_OPENED' and result['model_turns']==0
    assert result['pr']['isDraft'] and result['pr']['headRefOid']==batch['head_sha']
    assert git(remote,'rev-parse','refs/heads/'+batch['branch'])==batch['head_sha']
    assert result['children'] and result['final_checks'] and result['review']=='PASS'
    repeat=integrate_reviewed_batch(cfg,batch,github_factory=BatchGitHub)
    assert repeat['state']=='BATCH_PR_OPENED' and BatchGitHub.creates==1
    assert len(FakeRuntime.turns)==turns


def test_batch_remote_integration_refuses_unreviewed_or_changed_authority(cfg,tmp_path):
    runs=reviewed_pair(cfg)
    batch=compose_reviewed_slices(runs,cfg['state_dir'])
    cfg['integration'].update(push=True,pull_request=True)
    with pytest.raises(Stop,match='review is missing'):
        integrate_reviewed_batch(cfg,batch,github_factory=BatchGitHub)
    assert not (Path(cfg['state_dir'])/'batches'/batch['batch_id']/'batch-remote.json').exists()


def test_batch_remote_integration_reconciles_lost_push_ack(cfg,tmp_path,monkeypatch):
    batch,remote=reviewed_remote_batch(cfg,tmp_path)
    from devfactory import batch as module
    original=module.command
    failed=False
    def lost_ack(argv,**kwargs):
        nonlocal failed
        result=original(argv,**kwargs)
        if argv[-3:]==['--set-upstream','origin',batch['branch']] and not failed:
            failed=True
            raise Stop('BLOCKED_INFRASTRUCTURE','Injected lost push acknowledgement')
        return result
    monkeypatch.setattr(module,'command',lost_ack)
    result=integrate_reviewed_batch(cfg,batch,github_factory=BatchGitHub)
    assert failed and result['state']=='BATCH_PR_OPENED'
    assert git(remote,'rev-parse','refs/heads/'+batch['branch'])==batch['head_sha']
    assert BatchGitHub.creates==1


def test_batch_remote_integration_recovers_existing_pr_after_lost_ack(cfg,tmp_path):
    batch,remote=reviewed_remote_batch(cfg,tmp_path)
    class LostPrAck(BatchGitHub):
        failed=False
        def ensure_pr(self,*args):
            pr=super().ensure_pr(*args)
            if not type(self).failed:
                type(self).failed=True
                raise Stop('BLOCKED_GITHUB','Injected lost PR acknowledgement')
            return pr
    with pytest.raises(Stop,match='lost PR acknowledgement'):
        integrate_reviewed_batch(cfg,batch,github_factory=LostPrAck)
    assert LostPrAck.creates==1
    assert git(remote,'rev-parse','refs/heads/'+batch['branch'])==batch['head_sha']
    recovered=integrate_reviewed_batch(cfg,batch,github_factory=LostPrAck)
    assert recovered['state']=='BATCH_PR_OPENED' and LostPrAck.creates==1


def test_batch_remote_integration_refuses_changed_remote_base(cfg,tmp_path):
    batch,remote=reviewed_remote_batch(cfg,tmp_path)
    git(remote,'symbolic-ref','HEAD','refs/heads/main')
    repo=Path(cfg['projects']['demo']['path'])
    (repo/'after.txt').write_text('new base\n')
    git(repo,'add','after.txt')
    git(repo,'-c','user.name=Fixture','-c','user.email=f@localhost','commit','-qm','Move base')
    git(repo,'push','origin','main')
    with pytest.raises(Stop,match='Remote base changed'):
        integrate_reviewed_batch(cfg,batch,github_factory=BatchGitHub)
    assert git(remote,'show-ref','--verify','refs/heads/'+batch['branch'],check=False)==''


def test_batch_remote_integration_requires_exact_approval(cfg,tmp_path):
    batch,remote=reviewed_remote_batch(cfg,tmp_path)
    cfg['projects']['demo']['batch_integration_approvals'][batch['batch_id']]['trigger_hash']='wrong'
    with pytest.raises(Stop,match='exact reviewed composition'):
        integrate_reviewed_batch(cfg,batch,github_factory=BatchGitHub)
    assert git(remote,'show-ref','--verify','refs/heads/'+batch['branch'],check=False)==''


def test_integrated_batch_runs_combined_checks_and_one_fresh_review(cfg):
    runs=reviewed_pair(cfg)
    batch=compose_reviewed_slices(runs,cfg['state_dir'])
    cfg['projects']['demo']['final_checks']=['unit','note']
    turns=len(FakeRuntime.turns)
    result=review_composed_batch(cfg,batch,runtime_factory=FakeRuntime)
    assert result['state']=='BATCH_READY_LOCAL' and result['review']=='PASS'
    assert [x['check'] for x in result['final_checks']]==['unit','note']
    assert len(FakeRuntime.turns)==turns+1 and result['model_turns']==1
    packet=FakeRuntime.turns[-1]['packet']
    assert packet['batch']==batch['batch_id'] and len(packet['tasks'])==2
    repeat=review_composed_batch(cfg,batch,runtime_factory=FakeRuntime)
    assert repeat==result and len(FakeRuntime.turns)==turns+1


def test_integrated_batch_validation_failure_spends_no_review_turn(cfg):
    runs=reviewed_pair(cfg)
    batch=compose_reviewed_slices(runs,cfg['state_dir'])
    cfg['projects']['demo']['checks']['fail']=[os.sys.executable,'-c','raise SystemExit(2)']
    cfg['projects']['demo']['final_checks']=['fail']
    turns=len(FakeRuntime.turns)
    result=review_composed_batch(cfg,batch,runtime_factory=FakeRuntime)
    assert result['state']=='BLOCKED_BATCH_VALIDATION' and result['model_turns']==0
    assert len(FakeRuntime.turns)==turns
    assert review_composed_batch(cfg,batch,runtime_factory=FakeRuntime)==result


def test_integrated_batch_review_repair_is_blocked_not_auto_repaired(cfg):
    runs=reviewed_pair(cfg)
    batch=compose_reviewed_slices(runs,cfg['state_dir'])
    FakeRuntime.outcomes=[{'verdict':'REPAIR','findings':[{'file':'clamp.py','line':1,'summary':'interaction defect'}],
                           'summary':'needs repair'}]
    result=review_composed_batch(cfg,batch,runtime_factory=FakeRuntime)
    assert result['state']=='BLOCKED_BATCH_REVIEW' and result['review']=='REPAIR'
    assert result['model_turns']==1


def test_batch_refuses_overlap(cfg):
    runs=reviewed_pair(cfg)
    duplicate=copy.deepcopy(runs[0]);duplicate['id']='duplicate-reviewed-run'
    duplicate['data']['task_id']='duplicate'
    with pytest.raises(Stop,match='scopes overlap'):
        validate_reviewed_slices([runs[0],duplicate])


def test_batch_refuses_parent_child_scope_overlap(cfg):
    runs=reviewed_pair(cfg)
    parent=copy.deepcopy(runs[0]);parent['id']='a-parent'
    child=copy.deepcopy(runs[1]);child['id']='b-child';child['data']['subsystem']=['clamp.py/nested']
    with pytest.raises(Stop,match='scopes overlap'):
        validate_reviewed_slices([parent,child])


def test_batch_refuses_reviewed_symlink_and_preserves_binary_bytes(cfg):
    runs=reviewed_pair(cfg)
    second=Path(runs[1]['data']['worktree'])/'second.txt'
    second.unlink();second.symlink_to('clamp.py')
    runs[1]['data']['reviewed_fingerprint']=fingerprint(second.parent,runs[1]['data']['base_sha'])
    with pytest.raises(Stop,match='symlink changes'):
        validate_reviewed_slices(runs)
    second.unlink();second.write_bytes(b'\x00\xff\x10 reviewed bytes')
    runs[1]['data']['reviewed_fingerprint']=fingerprint(second.parent,runs[1]['data']['base_sha'])
    batch=compose_reviewed_slices(runs,cfg['state_dir'])
    assert (Path(batch['worktree'])/'second.txt').read_bytes()==second.read_bytes()
    assert git(batch['worktree'],'status','--porcelain')==''


def test_batch_refuses_base_mismatch(cfg):
    runs=reviewed_pair(cfg)
    other=copy.deepcopy(runs[1]);other['data']['base_sha']='0'*40
    with pytest.raises(Stop,match='share project, base SHA'):
        validate_reviewed_slices([runs[0],other])


def test_integration_receipt_rejects_changed_gate_config(cfg):
    runs=reviewed_pair(cfg)
    batch=compose_reviewed_slices(runs,cfg['state_dir'])
    result=review_composed_batch(cfg,batch,runtime_factory=FakeRuntime)
    assert result['state']=='BATCH_READY_LOCAL'
    cfg['projects']['demo']['checks']['other']=[os.sys.executable,'-c','pass']
    cfg['projects']['demo']['final_checks']=['other']
    with pytest.raises(Stop,match='policy/check configuration changed'):
        review_composed_batch(cfg,batch,runtime_factory=FakeRuntime)


def test_batch_reviewer_cannot_modify_review_snapshot(cfg):
    runs=reviewed_pair(cfg)
    batch=compose_reviewed_slices(runs,cfg['state_dir'])
    class EditingReviewer(FakeRuntime):
        def start(self,cwd,selection,instructions,read_only=False,resume=None):
            self.review_cwd=Path(cwd)
            return super().start(cwd,selection,instructions,read_only=read_only,resume=resume)
        def turn(self,tid,text,selection,**kwargs):
            packet=json.loads(text)
            if packet['role']=='review':
                (self.review_cwd/'clamp.py').write_text('tampered by reviewer\n')
            return super().turn(tid,text,selection,**kwargs)
    with pytest.raises(Stop,match='modified its isolated snapshot'):
        review_composed_batch(cfg,batch,runtime_factory=EditingReviewer)


def test_batch_refuses_reviewed_worktree_drift(cfg):
    runs=reviewed_pair(cfg)
    Path(runs[0]['data']['worktree'],'clamp.py').write_text('foreign drift\n')
    with pytest.raises(Stop,match='changed after review'):
        compose_reviewed_slices(runs,cfg['state_dir'])


def test_batch_operations_share_global_worker_lock(cfg):
    runs=reviewed_pair(cfg)
    batch=compose_reviewed_slices(runs,cfg['state_dir'])
    owner=Store(cfg['state_dir'])
    rid=owner.create('demo','live-owner',{})
    owner.claim(rid)
    turns=len(FakeRuntime.turns)
    try:
        with pytest.raises(Stop,match='global local lock'):
            compose_reviewed_slices(runs,cfg['state_dir'])
        with pytest.raises(Stop,match='global local lock'):
            review_composed_batch(cfg,batch,runtime_factory=FakeRuntime)
        assert len(FakeRuntime.turns)==turns
    finally:
        owner.release(rid);owner.close()


def test_batch_review_refuses_live_lease_even_without_flock(cfg):
    runs=reviewed_pair(cfg)
    batch=compose_reviewed_slices(runs,cfg['state_dir'])
    owner=Store(cfg['state_dir'])
    rid=owner.create('demo','live-owner',{})
    owner.claim(rid);owner.release_lock()
    try:
        with pytest.raises(Stop,match='live process'):
            review_composed_batch(cfg,batch,runtime_factory=FakeRuntime)
    finally:
        owner.release(rid);owner.close()


def test_batch_review_holds_lock_during_checks_and_turn(cfg):
    runs=reviewed_pair(cfg)
    batch=compose_reviewed_slices(runs,cfg['state_dir'])
    class ContendingRuntime(FakeRuntime):
        def contender(self):
            other=Store(cfg['state_dir'])
            try:
                with pytest.raises(Stop,match='global local lock'): other.acquire_lock()
                lease=other.db.execute('SELECT run_id FROM lease').fetchone()
                assert other.get(lease[0])['data']['operation']=='batch-review'
            finally: other.close()
        def command(self,*args,**kwargs):
            self.contender()
            return super().command(*args,**kwargs)
        def turn(self,*args,**kwargs):
            self.contender()
            return super().turn(*args,**kwargs)
    result=review_composed_batch(cfg,batch,runtime_factory=ContendingRuntime)
    assert result['state']=='BATCH_READY_LOCAL'
    store=Store(cfg['state_dir'])
    try:
        assert store.db.execute('SELECT * FROM lease').fetchone() is None
        assert store.get(result['run_id'])['state']=='BATCH_READY_LOCAL'
    finally: store.close()


class LostReviewResult(FakeRuntime):
    persisted={}
    active=False
    def turn(self,*args,**kwargs):
        result=super().turn(*args,**kwargs)
        self.persisted[result['thread_id']]={'id':result['turn_id'],'status':'completed',
            'items':[{'type':'agentMessage','phase':'final_answer','text':result['final']}]}
        raise Stop('BLOCKED_RUNTIME','Injected lost review response')
    def rpc(self,method,params):
        return {'thread':{'status':{'type':'active' if self.active else 'idle'},
                          'turns':[self.persisted[params['threadId']]]}}


def test_batch_review_recovers_lost_result_without_another_turn(cfg):
    runs=reviewed_pair(cfg)
    batch=compose_reviewed_slices(runs,cfg['state_dir'])
    turns=len(FakeRuntime.turns)
    with pytest.raises(Stop,match='Injected lost'):
        review_composed_batch(cfg,batch,runtime_factory=LostReviewResult)
    path=Path(cfg['state_dir'])/'batches'/batch['batch_id']/'integration.json'
    saved=json.loads(path.read_text())
    assert saved['turn_id'] and saved['thread_id'] and saved['usage']['totalTokens']==130
    assert saved['model_turns']==1 and saved['usage_complete'] is False
    result=review_composed_batch(cfg,batch,runtime_factory=LostReviewResult)
    assert result['state']=='BATCH_READY_LOCAL' and result['recovered']
    assert result['model_turns']==1 and result['usage']['totalTokens']==130
    assert result['usage_complete'] is False and len(FakeRuntime.turns)==turns+1


def test_batch_review_does_not_redispatch_active_native_turn(cfg):
    runs=reviewed_pair(cfg)
    batch=compose_reviewed_slices(runs,cfg['state_dir'])
    with pytest.raises(Stop): review_composed_batch(cfg,batch,runtime_factory=LostReviewResult)
    turns=len(FakeRuntime.turns)
    class ActiveReview(LostReviewResult): active=True
    with pytest.raises(Stop,match='still active'):
        review_composed_batch(cfg,batch,runtime_factory=ActiveReview)
    assert len(FakeRuntime.turns)==turns


def test_batch_review_unknown_dispatch_acknowledgement_is_preserved(cfg):
    runs=reviewed_pair(cfg)
    batch=compose_reviewed_slices(runs,cfg['state_dir'])
    class MissingAcknowledgement(FakeRuntime):
        calls=0
        def turn(self,*args,**kwargs):
            type(self).calls+=1
            raise Stop('BLOCKED_RUNTIME','No acknowledgement')
    with pytest.raises(Stop): review_composed_batch(cfg,batch,runtime_factory=MissingAcknowledgement)
    with pytest.raises(Stop,match='acknowledgement is unknown'):
        review_composed_batch(cfg,batch,runtime_factory=MissingAcknowledgement)
    saved=json.loads((Path(cfg['state_dir'])/'batches'/batch['batch_id']/'integration.json').read_text())
    assert saved['model_turns'] is None and saved['dispatch_attempts']==1
    assert MissingAcknowledgement.calls==1


def test_batch_review_recovers_result_saved_before_final_receipt(cfg,monkeypatch):
    import devfactory.batch as module
    runs=reviewed_pair(cfg)
    batch=compose_reviewed_slices(runs,cfg['state_dir'])
    finish=module._finish_review
    def fail(*args): raise OSError('Injected receipt failure')
    monkeypatch.setattr(module,'_finish_review',fail)
    with pytest.raises(OSError): review_composed_batch(cfg,batch,runtime_factory=FakeRuntime)
    turns=len(FakeRuntime.turns)
    monkeypatch.setattr(module,'_finish_review',finish)
    def no_runtime(*args): pytest.fail('Persisted result needs no native execution')
    result=review_composed_batch(cfg,batch,runtime_factory=no_runtime)
    assert result['state']=='BATCH_READY_LOCAL' and len(FakeRuntime.turns)==turns


def test_batch_review_pause_before_dispatch_spends_no_turn(cfg):
    runs=reviewed_pair(cfg)
    batch=compose_reviewed_slices(runs,cfg['state_dir'])
    class PausingRuntime(FakeRuntime):
        def command(self,*args,**kwargs):
            result=super().command(*args,**kwargs)
            store=Store(cfg['state_dir'])
            try:
                rid=store.db.execute('SELECT run_id FROM lease').fetchone()[0]
                store.pause(rid)
                assert kwargs['should_pause']()
            finally: store.close()
            return result
    turns=len(FakeRuntime.turns)
    with pytest.raises(Stop,match='requested batch pause'):
        review_composed_batch(cfg,batch,runtime_factory=PausingRuntime)
    assert len(FakeRuntime.turns)==turns


def test_batch_review_expired_deadline_spends_no_turn(cfg,monkeypatch):
    import devfactory.batch as module
    runs=reviewed_pair(cfg)
    batch=compose_reviewed_slices(runs,cfg['state_dir'])
    clock=[module.time.time()]
    monkeypatch.setattr(module.time,'time',lambda:clock[0])
    class SlowValidation(FakeRuntime):
        def command(self,*args,**kwargs):
            result=super().command(*args,**kwargs)
            clock[0]+=cfg['budget']['deadline_seconds']+1
            return result
    turns=len(FakeRuntime.turns)
    with pytest.raises(Stop,match='deadline reached'):
        review_composed_batch(cfg,batch,runtime_factory=SlowValidation)
    assert len(FakeRuntime.turns)==turns


def test_batch_review_does_not_redispatch_interrupted_turn(cfg):
    runs=reviewed_pair(cfg)
    batch=compose_reviewed_slices(runs,cfg['state_dir'])
    FakeRuntime.interrupt=True
    with pytest.raises(Stop,match='attempt preserved'):
        review_composed_batch(cfg,batch,runtime_factory=FakeRuntime)
    turns=len(FakeRuntime.turns)
    FakeRuntime.interrupt=False
    with pytest.raises(Stop,match='attempt preserved'):
        review_composed_batch(cfg,batch,runtime_factory=FakeRuntime)
    assert len(FakeRuntime.turns)==turns


def test_batch_review_resume_recovers_dead_owner_without_redispatch(cfg,monkeypatch,capsys):
    import devfactory.batch as module
    from devfactory.cli import main
    runs=reviewed_pair(cfg)
    batch=compose_reviewed_slices(runs,cfg['state_dir'])
    with pytest.raises(Stop): review_composed_batch(cfg,batch,runtime_factory=LostReviewResult)
    path=Path(cfg['state_dir'])/'batches'/batch['batch_id']/'integration.json'
    saved=json.loads(path.read_text())
    # A dead process can leave its durable lease after the OS releases its flock.
    owner=Store(cfg['state_dir'])
    owner.claim(saved['run_id'])
    with owner.db:
        owner.db.execute('UPDATE lease SET pid=-1,identity=?',('dead-fixture-owner',))
    owner.close()
    review=module.review_composed_batch
    monkeypatch.setattr(module,'review_composed_batch',lambda c,b:review(c,b,runtime_factory=LostReviewResult))
    monkeypatch.setattr('devfactory.cli.load',lambda *args:cfg)
    monkeypatch.setattr('devfactory.fixture.prepare',lambda c,*args:c)
    turns=len(FakeRuntime.turns)
    assert main(['resume',saved['run_id']])==0
    assert json.loads(capsys.readouterr().out)['state']=='BATCH_READY_LOCAL'
    assert len(FakeRuntime.turns)==turns
