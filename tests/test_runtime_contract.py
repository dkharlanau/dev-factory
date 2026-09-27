import inspect
import json
from pathlib import Path
import pytest
from devfactory.runtime import Runtime,SDK_VERSION,RUNTIME_VERSION,verify_versions,ALLOWED_METHODS,BASE_OVERRIDES
from devfactory.cli import parser,main
from devfactory.benchmark import benchmark
from devfactory.repository import review_snapshot,fingerprint,git
from devfactory.policy import Stop


def test_installed_sdk_public_contract():
    from openai_codex.client import CodexClient
    from openai_codex.generated.v2_all import TurnStartParams,CommandExecParams
    assert verify_versions()=={'sdk':SDK_VERSION,'runtime_package':RUNTIME_VERSION}
    assert callable(CodexClient.turn_start) and callable(CodexClient.next_turn_notification)
    assert 'tool_output' in TurnStartParams.model_fields
    assert 'sandbox_policy' in CommandExecParams.model_fields
    assert 'timeout_ms' in CommandExecParams.model_fields
    assert 'max_tokens' not in TurnStartParams.model_fields
    assert 'account/rateLimitResetCredit/consume' not in ALLOWED_METHODS
    assert 'thread/shellCommand' not in ALLOWED_METHODS


def test_version_mismatch(monkeypatch):
    monkeypatch.setattr('devfactory.runtime.versions',lambda:{'sdk':'999','runtime_package':'999'})
    with pytest.raises(Stop):verify_versions()


def test_worker_config_scoped_disables_and_no_private_sdk_fields():
    r=object.__new__(Runtime);r.disabled_servers=['unsafe'];r.plugins=['example@marketplace']
    c=r.worker_config()
    assert c['features.hooks'] is False and c['features.apps'] is False
    assert c['mcp_servers.unsafe.enabled'] is False
    assert c['plugins.example@marketplace.enabled'] is False
    source=inspect.getsource(Runtime)
    assert '.client._' not in source
    assert 'experimental_api=False' in source
    assert 'sandbox_workspace_write.network_access' in source


def test_manifest_and_skill():
    root=Path(__file__).resolve().parents[1]
    manifest=json.loads((root/'plugins/factory/.codex-plugin/plugin.json').read_text())
    assert manifest['name']=='factory'
    assert (root/'plugins/factory'/manifest['skills']).is_dir()
    skill=root/'.agents/skills/factory/SKILL.md'
    assert skill.resolve().is_file()
    assert 'name: factory' in skill.read_text()

@pytest.mark.parametrize('argv',[['doctor'],['doctor','--live'],['models'],['plan','voice-lab'],
 ['run','demo','--max-tasks','1'],['batch','a','b'],['batch-review','0123456789abcdef'],
 ['status'],['pause','id'],['resume','id'],['report'],['benchmark'],['benchmark','--live']])
def test_cli_schema(argv): assert parser().parse_args(argv).command==argv[0]


def test_offline_benchmark_never_calls_runtime(cfg,monkeypatch):
    monkeypatch.setattr(Runtime,'__enter__',lambda *_:pytest.fail('Model/runtime used by offline benchmark'))
    r=benchmark(cfg)
    assert r['passed'] and r['sample_size']==0 and r['efficiency_claim'] is None


def test_review_environment_is_isolated(cfg,tmp_path):
    src=Path(cfg['projects']['demo']['path']);base=cfg['projects']['demo']['base_sha']
    (src/'clamp.py').write_text('def clamp(*args): return 42\n')
    review=review_snapshot(src,tmp_path/'review',base)
    assert fingerprint(src,base)==fingerprint(review,base)
    (review/'clamp.py').write_text('changed independently')
    assert (src/'clamp.py').read_text()=='def clamp(*args): return 42\n'


def test_skill_copies_are_identical():
    root=Path(__file__).resolve().parents[1]
    for name in ('SKILL.md','scripts/dispatch.py'):
        assert (root/'.agents/skills/factory'/name).read_bytes()==(root/'plugins/factory/skills/factory'/name).read_bytes()


def test_public_turn_subscription_handles_realistic_events():
    from types import SimpleNamespace
    from pydantic import RootModel
    from devfactory.policy import Selection,Usage
    import time
    notifications=[('thread/tokenUsage/updated',{'threadId':'thread','turnId':'turn','tokenUsage':{'total':{'totalTokens':9}}}),
        ('thread/tokenUsage/updated',{'threadId':'thread','turnId':'turn','tokenUsage':{'total':{'totalTokens':9}}}),
        ('item/completed',{'threadId':'thread','turnId':'turn','item':{'type':'agentMessage','phase':'final_answer','text':'PASS'}}),
        ('turn/completed',{'threadId':'thread','turn':{'id':'turn','status':'completed'}})]
    class Client:
        def turn_start(self,tid,items,params):
            assert items==[] and params['toolOutput']['name']=='factory_task'
            assert params['approvalPolicy']=='never'
            return SimpleNamespace(turn=SimpleNamespace(id='turn'))
        def next_turn_notification(self,turn):
            method,data=notifications.pop(0)
            return SimpleNamespace(method=method,payload=RootModel[dict](data))
        def unregister_turn_notifications(self,turn): pass
    r=object.__new__(Runtime);r.client=Client();r.thread_settings={}
    u=Usage()
    result=r.turn('thread','untrusted task',Selection('fast','m','low','test','1'),deadline=time.time()+5,
                  external=True,on_event=lambda _,p:u.observe(p['threadId'],p['tokenUsage']))
    assert result['status']=='completed' and result['final']=='PASS'
    assert result['effective_model'] is None and u.aggregate()['totalTokens']==9


def test_rpc_method_allowlist():
    r=object.__new__(Runtime)
    with pytest.raises(Stop,match='Non-allowlisted'):
        r.rpc('process/spawn',{'command':['sh']})


def test_ordinary_quota_denial_overrides_positive_percentage(cfg):
    from devfactory.policy import check_quota
    with pytest.raises(Stop):
        check_quota({'ordinaryUsageAllowed':False,'rateLimitsByLimitId':{'codex':{'primary':{'usedPercent':1}}}},cfg['budget'])


def test_console_root_does_not_follow_product_cwd(tmp_path,monkeypatch):
    from devfactory.cli import default_root
    monkeypatch.delenv('FACTORY_ROOT',raising=False)
    monkeypatch.chdir(tmp_path)
    assert default_root()==Path(__file__).resolve().parents[1]


def test_compaction_timeout_is_not_success(monkeypatch):
    import time
    r=object.__new__(Runtime)
    r.read=lambda tid:{'thread':{'status':{'type':'idle'}}}
    r.rpc=lambda method,params:{'thread':{'turns':[]}} if method=='thread/read' else {}
    r.interrupt=lambda *_:None
    result=r.compact('t',deadline=time.time()-.1,checkpoint={'task':'t'})
    assert result['state']=='TIMEOUT' and result['usage'] is None
    with pytest.raises(Stop,match='checkpoint'):r.compact('t',deadline=0,checkpoint=None)


def test_compaction_refuses_active_turn():
    r=object.__new__(Runtime);r.read=lambda tid:{'thread':{'status':{'type':'active'}}}
    import time
    with pytest.raises(Stop,match='idle'):r.compact('t',deadline=time.time()+1,checkpoint={'task':'t'})


def test_permissions_never_auto_approved():
    from devfactory.runtime import deny_approval
    assert deny_approval('item/commandExecution/requestApproval',{})['decision']=='decline'
    assert deny_approval('item/permissions/requestApproval',{})['permissions']=={}
    assert deny_approval('mcpServer/elicitation/request',{})['action']=='decline'


def test_uninstall_preserves_foreign_and_requires_marker(tmp_path,monkeypatch):
    import runpy,shutil
    root=Path(__file__).resolve().parents[1]
    (tmp_path/'scripts').mkdir();script=tmp_path/'scripts/uninstall.py';shutil.copy2(root/'scripts/uninstall.py',script)
    venv=tmp_path/'.venv';venv.mkdir();(tmp_path/'foreign.txt').write_text('keep')
    with pytest.raises(SystemExit,match='No owned'):runpy.run_path(str(script),run_name='__main__')
    assert venv.exists()
    (venv/'.devfactory-owner').write_text('devfactory-owned-environment-v1\n')
    runpy.run_path(str(script),run_name='__main__')
    assert not venv.exists() and (tmp_path/'foreign.txt').read_text()=='keep'
