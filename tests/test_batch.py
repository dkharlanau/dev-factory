import copy
import json
import os
import subprocess
from pathlib import Path

import pytest

from devfactory.batch import compose_reviewed_slices, review_composed_batch, validate_reviewed_slices
from devfactory.fixture import TASK
from devfactory.policy import Stop
from devfactory.repository import git
from devfactory.runner import Runner
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
    runner=Runner(cfg,runtime_factory=FakeRuntime,emit=lambda _:None)
    try:
        runs=runner.run('demo',max_tasks=2)
    finally:
        runner.close()
    assert [r['state'] for r in runs]==['READY_LOCAL','READY_LOCAL']
    return runs


def test_compose_reviewed_slices_is_exact_and_idempotent(cfg):
    runs=reviewed_pair(cfg)
    turns=len(FakeRuntime.turns)
    batch=compose_reviewed_slices(runs,cfg['state_dir'])
    assert batch['state']=='COMPOSED_LOCAL' and batch['model_turns']==0
    assert batch['combined_files']==['clamp.py','second.txt']
    wt=Path(batch['worktree'])
    assert (wt/'second.txt').read_text()=='fixture change\n'
    check=subprocess.run([os.sys.executable,'-m','unittest','-v'],cwd=wt,capture_output=True,text=True)
    assert check.returncode==0,check.stderr
    repeat=compose_reviewed_slices(runs,cfg['state_dir'])
    assert repeat==batch and len(FakeRuntime.turns)==turns


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
        def turn(self,tid,text,selection,**kwargs):
            packet=json.loads(text)
            if packet['role']=='review':
                (self.cwd/'clamp.py').write_text('tampered by reviewer\n')
            return super().turn(tid,text,selection,**kwargs)
    with pytest.raises(Stop,match='modified its isolated snapshot'):
        review_composed_batch(cfg,batch,runtime_factory=EditingReviewer)


def test_batch_refuses_reviewed_worktree_drift(cfg):
    runs=reviewed_pair(cfg)
    Path(runs[0]['data']['worktree'],'clamp.py').write_text('foreign drift\n')
    with pytest.raises(Stop,match='changed after review'):
        compose_reviewed_slices(runs,cfg['state_dir'])
