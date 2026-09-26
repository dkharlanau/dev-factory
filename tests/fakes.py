"""Offline-only adapters. Tokens and account activity below are synthetic test data."""
import json
import subprocess
import time
from pathlib import Path

CATALOG=[{'model':'fixture-model','isDefault':True,'inputModalities':['text'],
          'defaultReasoningEffort':'medium','supportedReasoningEfforts':[{'reasoningEffort':x} for x in ['low','medium','high']]}]
QUOTA={'ordinaryUsageAllowed':True,'rateLimitsByLimitId':{'codex':{'limitId':'codex','primary':{'usedPercent':10,'resetsAt':2000000000}}}}

class FakeRuntime:
    history=[]
    turns=[]
    outcomes=[]
    fail_tests=False
    interrupt=False
    def __init__(self,cwd,**kw):
        self.cwd=Path(cwd); self.catalog=CATALOG; self.native={'model':'fixture-model','model_reasoning_effort':'high'}
    def __enter__(self): return self
    def __exit__(self,*_): pass
    def quota(self): return QUOTA
    def inventory(self): return {'versions':{'runtime':'FAKE'}}
    def start(self,cwd,selection,instructions,read_only=False,resume=None):
        tid=resume or 'thread-'+str(len(self.history)+1)
        self.history.append({'id':tid,'read_only':read_only,'resume':resume,'instructions':instructions,
                             'profile':selection.profile,'requested_model':selection.requested_model,
                             'requested_effort':selection.requested_effort})
        return tid
    def turn(self,tid,text,selection,*,on_start,on_event,**kwargs):
        packet=json.loads(text); role=packet['role']
        self.turns.append({'thread':tid,'packet':packet})
        turn='turn-'+str(len(self.turns)); on_start(tid,turn)
        if role!='review':
            (self.cwd/'clamp.py').write_text('def clamp(value, low, high):\n    if low > high: raise ValueError("bounds")\n    return max(low,min(value,high))\n')
        usage={'total':{'inputTokens':100,'cachedInputTokens':20,'outputTokens':30,'reasoningOutputTokens':10,'totalTokens':130},'modelContextWindow':1000}
        on_event('thread/tokenUsage/updated',{'threadId':tid,'tokenUsage':usage})
        verdict=self.outcomes.pop(0) if self.outcomes else {'verdict':'PASS','findings':[],'summary':'fixture'}
        return {'status':'interrupted' if self.interrupt else 'completed','thread_id':tid,'turn_id':turn,
                'final':json.dumps(verdict),'usage':usage,'effective_model':None,'resolved_model':'fixture-model',
                **({'stop_state':'PAUSED'} if self.interrupt else {})}
    def command(self,cwd,argv,**kwargs):
        if self.fail_tests: return {'exitCode':1,'stdout':'fixture assertion failed','stderr':''}
        r=subprocess.run(argv,cwd=cwd,capture_output=True,text=True)
        return {'exitCode':r.returncode,'stdout':r.stdout,'stderr':r.stderr}
    def rpc(self,method,params):
        return {'thread':{'status':{'type':'idle'},'turns':[]}}
    def read(self,tid): return self.rpc('',{})


def reset():
    FakeRuntime.history=[]; FakeRuntime.turns=[]; FakeRuntime.outcomes=[]
    FakeRuntime.fail_tests=False; FakeRuntime.interrupt=False
