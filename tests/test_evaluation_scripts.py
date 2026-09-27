"""Completed live experiments must be inspectable without re-spending or rewriting."""
import runpy
import sys
from pathlib import Path
import pytest


@pytest.mark.parametrize('script,nested',[('pr_lifecycle.py',False),('recovery.py',True)])
def test_completed_experiment_reuses_receipt_without_new_work(tmp_path,monkeypatch,script,nested):
    folder=Path(__file__).resolve().parents[1]/'scripts/evaluation'
    monkeypatch.syspath_prepend(str(folder));monkeypatch.setattr(sys,'argv',[script,'--live'])
    namespace=runpy.run_path(str(folder/script),run_name='evaluation_test')
    namespace['main'].__globals__['AREA']=tmp_path
    for name in ['load','prepare','Runner','Runtime']:
        namespace['main'].__globals__[name]=lambda *_a,**_k:pytest.fail('Completed experiment attempted new work')
    receipt=(tmp_path/'recovery' if nested else tmp_path)/'result.json'
    receipt.parent.mkdir(parents=True,exist_ok=True);receipt.write_text('{"preserve":"original result"}\n')
    namespace['main']()
    assert receipt.read_text()=='{"preserve":"original result"}\n'


def test_evaluation_experiment_namespace_is_stable_and_rejects_unsafe_names():
    folder=Path(__file__).resolve().parents[1]/'scripts/evaluation'
    monkeypatch = pytest.MonkeyPatch()
    try:
        monkeypatch.syspath_prepend(str(folder))
        namespace=runpy.run_path(str(folder/'run.py'),run_name='evaluation_namespace_test')
        slug=namespace['experiment_slug']
        area=namespace['experiment_area']
        assert slug('policy-v2-r1')=='policy-v2-r1'
        assert area('policy-v2-r1').parts[-2:]==('experiments','policy-v2-r1')
        for invalid in ('../x','Policy V2','', 'x'*65):
            with pytest.raises(ValueError): slug(invalid)
    finally:
        monkeypatch.undo()


def test_legacy_profile_benchmark_keeps_existing_run_identities(cfg,monkeypatch):
    from devfactory.benchmark import benchmark
    from devfactory.runner import Runner
    from fakes import FakeRuntime
    monkeypatch.setattr('devfactory.runner.Runner',lambda config:Runner(config,runtime_factory=FakeRuntime,emit=lambda _:None))
    first=benchmark(cfg,live=True)
    count=len(FakeRuntime.turns)
    second=benchmark(cfg,live=True)
    assert count==4 and len(FakeRuntime.turns)==count
    assert first['comparison_scope']=='model/effort routing inside Factory'
    assert [v['receipt_id'] for v in first['variants']]==[v['receipt_id'] for v in second['variants']]
