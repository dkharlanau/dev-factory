"""One explicitly invoked tiny interruption check; no production repository."""
import json,time
from pathlib import Path
from devfactory.config import load
from devfactory.policy import choose_model,check_quota
from devfactory.runtime import Runtime
from devfactory.state import atomic_json
root=Path(__file__).resolve().parents[1]
p=root/'.factory/evidence/interrupt-smoke.json'
if p.exists(): raise SystemExit('Existing interruption receipt; no repeated model turn')
first=json.loads((root/'.factory/evidence/first-live-smoke.json').read_text())
c=load(root)
with Runtime(first['fixture']) as r:
    check_quota(r.quota(),c['budget'])
    s=choose_model('fast',c,r.catalog,r.native)
    tid=r.start(first['fixture'],s,'Bounded interruption probe. Do not access network, secrets, or modify files.',read_only=True)
    atomic_json(p,{'model_requests':1,'state':'STARTING','thread_id':tid})
    result=r.turn(tid,'Reply OK.',s,deadline=time.time()+20,should_pause=lambda:True)
    result.pop('final',None)
    atomic_json(p,{'model_requests':1,'state':result['status'],'result':result})
    print(result['status'],result.get('stop_state'))
