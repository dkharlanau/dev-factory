"""One-time recovery for the first smoke; uses the same strict three-request budget."""
import json,sys,time
from pathlib import Path
from devfactory.runtime import Runtime
from devfactory.config import load
from devfactory.policy import choose_model,check_quota,Usage
from devfactory.state import atomic_json
root=Path(__file__).resolve().parents[1]
p=root/'.factory/evidence/first-live-smoke.json'
d=json.loads(p.read_text())
if d['model_requests'] != 1 or not d.get('failure'):
    raise SystemExit('Recovery requires exactly one existing attempted builder request')
d['controller_failure_before_recovery']=d.pop('failure')
c=load(root); usage=Usage()
def save(): atomic_json(p,d)
def event(m,x):
    if m=='thread/tokenUsage/updated': usage.observe(x['threadId'],x['tokenUsage'])
try:
    with Runtime(d['fixture']) as r:
        selection=choose_model('fast',c,r.catalog,r.native)
        check_quota(r.quota(),c['budget'])
        builder=r.start(d['fixture'],selection,'Respect fixture AGENTS.md. No network, policy changes, secrets, external writes or subagents.',resume=d['builder_thread'])
        state=r.rpc('thread/read',{'threadId':builder,'includeTurns':True})['thread']
        d['reconciled_builder_status']=state['turns'][-1]['status']
        d['resume_same_thread']=builder==d['builder_thread']
        d['tests']=r.command(d['fixture'],[sys.executable,'-m','unittest','-v'],timeout=20)
        save()
        assert d['tests']['exitCode']==0
        reviewer=r.start(d['fixture'],selection,'Fresh independent fixture review. Inspect actual files and diff. No edits, secrets, network or external writes.',read_only=True)
        d['reviewer_thread']=reviewer
        d['model_requests']+=1; save()
        rr=r.turn(reviewer,'Inspect git diff, clamp.py and test_clamp.py. Acceptance: inclusive clamp and ValueError for low > high; tests unchanged. Controller executed tests with exit 0. Reply PASS or concrete defects.',selection,deadline=time.time()+90,on_event=event)
        d['review_response']=rr.pop('final',None)
        d['steps'].append({'review':rr})
        print('review',rr['status'],d['review_response'],flush=True)
        d['checkpoint']={'task':'clamp fixture','base_sha':state.get('gitInfo',{}),'verified':['tests exit 0'],'next':'manual compaction probe'}
        d['model_requests']+=1; save()
        d['compaction']=r.compact(builder,deadline=time.time()+60,checkpoint=d['checkpoint'])
        d['after_compact_thread']=r.read(builder)['thread']['id']
        d['after_compact_tests']=r.command(d['fixture'],[sys.executable,'-m','unittest'],timeout=20)['exitCode']
        print('compaction',d['compaction'],flush=True)
except BaseException as e:
    d['failure']={'type':type(e).__name__,'message':str(e)[:300]}
    raise
finally:
    d['usage_measured_review_only']=usage.aggregate()
    d['usage_complete']=False
    d['wall_seconds']=time.time()-d['started_at']
    save()
