"""Test the actual persisted-state adapter rather than an unused event simulation."""
import time
import pytest
from devfactory.runtime import Runtime


def adapter(status='completed',items=None):
    r=object.__new__(Runtime);calls=[]
    r.read=lambda _: {'thread':{'status':{'type':'idle'}}}
    old={'id':'old','status':'completed','items':[{'id':'old-item','type':'contextCompaction'}]}
    current={'id':'new','status':status,'items':items or []}
    dispatched=False
    def rpc(method,params):
        nonlocal dispatched
        calls.append(method)
        if method=='thread/compact/start': dispatched=True;return {}
        return {'thread':{'turns':[old]+([current] if dispatched else [])}}
    r.rpc=rpc;r.interrupt=lambda *a:calls.append(('interrupt',*a))
    return r,calls


@pytest.mark.parametrize('status,items,expected',[
    ('completed',[{'type':'contextCompaction','id':'c'}],'COMPLETED'),
    ('completed',[],'NO_OP'),('failed',[],'FAILED'),('interrupted',[],'INTERRUPTED')])
def test_actual_compaction_persisted_outcomes(status,items,expected):
    r,calls=adapter(status,items)
    result=r.compact('t',deadline=time.time()+1,checkpoint={'task':'x'})
    assert result['state']==expected and result['turn_id']=='new'
    assert result['usage'] is None
    assert calls.count('thread/compact/start')==1
    assert 'old-item' not in result['items']


def test_expired_compaction_does_not_dispatch():
    r,calls=adapter()
    result=r.compact('t',deadline=time.time()-1,checkpoint={'task':'x'})
    assert result['state']=='TIMEOUT'
    assert 'thread/compact/start' not in calls


def test_deadline_expires_during_compaction_preflight():
    r,calls=adapter()
    def slow_read(_):
        time.sleep(.025)
        return {'thread':{'status':{'type':'idle'}}}
    r.read=slow_read
    result=r.compact('t',deadline=time.time()+.01,checkpoint={'task':'x'})
    assert result['state']=='TIMEOUT'
    assert 'thread/compact/start' not in calls


def test_compaction_timeout_interrupts_observed_new_turn():
    r,calls=adapter('inProgress')
    result=r.compact('t',deadline=time.time()+.02,checkpoint={'task':'x'})
    assert result['state']=='TIMEOUT' and result['turn_id']=='new'
    assert ('interrupt','t','new') in calls
