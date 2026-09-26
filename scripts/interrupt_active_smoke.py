"""One bounded active-command interrupt, after the immediate request raced completion."""
import json,time
from pathlib import Path
from devfactory.config import load
from devfactory.policy import choose_model,check_quota
from devfactory.runtime import Runtime
from devfactory.state import atomic_json
root=Path(__file__).resolve().parents[1];p=root/'.factory/evidence/interrupt-active-smoke.json'
if p.exists():raise SystemExit('Already attempted; do not spend more turns')
first=json.loads((root/'.factory/evidence/first-live-smoke.json').read_text());c=load(root)
active=[False]
def event(m,d):
    if m=='item/started':active[0]=True
with Runtime(first['fixture']) as r:
    check_quota(r.quota(),c['budget']);s=choose_model('fast',c,r.catalog,r.native)
    tid=r.start(first['fixture'],s,'Bounded interruption check. No edits, secrets, network or external actions.')
    atomic_json(p,{'model_requests':1,'state':'STARTING','thread_id':tid})
    result=r.turn(tid,"Run python3 -c 'import time; time.sleep(10)' in this fixture, then reply OK. Do not modify files.",s,deadline=time.time()+30,should_pause=lambda:active[0],on_event=event)
    result.pop('final',None)
    atomic_json(p,{'model_requests':1,'active_command_observed':active[0],'state':result['status'],'result':result})
    print('active command',active[0],result['status'],result.get('stop_state'))
