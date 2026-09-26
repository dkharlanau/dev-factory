#!/usr/bin/env python3
"""One explicit long-task interruption, persisted compaction, same-thread recovery."""
import argparse
import copy
import json
import time
from pathlib import Path
from run import ROOT,AREA,CASES,prepare,MeasuredRuntime,Runtime,Runner,atomic_json,fingerprint,assess
from devfactory.policy import choose_model, check_budget, check_quota
from devfactory.runner import WORKER_RULES


def main():
    p=argparse.ArgumentParser();p.add_argument('--live',action='store_true');args=p.parse_args()
    if not args.live:p.error('--live required; spends allowance including compaction')
    if (AREA/'recovery'/'result.json').exists():
        print('EXISTING_EVALUATION',AREA/'recovery'/'result.json');return
    case=next(c for c in CASES if c['id']=='long');cfg,meta=prepare(case)
    cfg['state_dir']=str(AREA/'recovery')
    # A separate, prospectively bounded recovery experiment, based on the primary
    # real-task observations. Production defaults and primary receipts stay fixed.
    cfg['budget']['soft_tokens']=500000
    marker=AREA/'recovery'/'interruption.json'
    class InterruptAfterEdit(MeasuredRuntime):
        def turn(self,tid,text,selection,**kw):
            packet=json.loads(text);paused=kw.get('should_pause',lambda:False)
            original=fingerprint(self.cwd,meta['snapshot_sha']); requested=False
            def interrupt():
                nonlocal requested
                if requested:return True
                if paused():return True
                if packet['role']!='review' and not marker.exists() and fingerprint(self.cwd,meta['snapshot_sha'])!=original:
                    requested=True
                    atomic_json(marker,{'thread_id':tid,'fingerprint':fingerprint(self.cwd,meta['snapshot_sha']),'reason':'Injected after first durable source edit'})
                    return True
                return False
            kw['should_pause']=interrupt
            return super().turn(tid,text,selection,**kw)
    r=Runner(cfg,runtime_factory=InterruptAfterEdit)
    try:
        old=r.store.by_task('long','long')
        first=r.store.get(old['id']) if old else r.run('long')[0]
        d=first['data'];wt=Path(d['worktree']);before=fingerprint(wt,meta['snapshot_sha'])
        paused_checkpoint=AREA/'recovery'/'paused-checkpoint.json'
        if first['state']=='PAUSED' and not paused_checkpoint.exists():
            atomic_json(paused_checkpoint,json.loads((AREA/'recovery'/'runs'/first['id']/'checkpoint.json').read_text()))
        compact_file=AREA/'recovery'/'compaction.json'
        if not compact_file.exists() and first['state']=='PAUSED':
            with Runtime(wt) as rt:
                check_budget(cfg['budget'],deadline=time.time()+180,turns=len(d['turns']),tokens=d['usage'].get('totalTokens'))
                check_quota(rt.quota(),cfg['budget'])
                sel=choose_model(d['profile'],cfg,rt.catalog,rt.native)
                tid=rt.start(wt,sel,WORKER_RULES,resume=d['builder_thread'])
                compaction=rt.compact(tid,deadline=time.time()+180,checkpoint=json.loads((AREA/'recovery'/'runs'/first['id']/'checkpoint.json').read_text()))
                atomic_json(compact_file,compaction)
        # Compaction is an additional model-producing request: charge it to this run.
        if compact_file.exists() and not any(t['role']=='compaction' for t in d['turns']):
            compaction=json.loads(compact_file.read_text())
            d['turns'].append({'role':'compaction','thread_id':d['builder_thread'],'turn_id':compaction.get('turn_id'),
                'status':compaction['state'],'usage':None,'effective_model':None,'requested_model':None,'requested_effort':None})
            d['compaction_usage']=None
            r.store.save(first['id'],first['state'],d)
        compact_fingerprint=fingerprint(wt,meta['snapshot_sha'])
        r.close();r=Runner(cfg,runtime_factory=MeasuredRuntime)
        result=r.resume(first['id']);repeat=r.run('long')[0]
        d=result['data']
        with Runtime(wt) as rt:evaluation=assess(wt,meta['snapshot_sha'],case,rt,'recovery-long')
        summary={'first_state':first['state'],'final_state':result['state'],'reason':d.get('reason'),
            'first_thread':first['data']['builder_thread'],'final_thread':d['builder_thread'],
            'source_unchanged_by_compaction':before==compact_fingerprint,
            'compaction':json.loads(compact_file.read_text()) if compact_file.exists() else None,
            'turns':d['turns'],'usage':d['usage'],'usage_complete':False,'repeat':repeat,
            'assessment':evaluation,'review':d.get('review'),'run_id':result['id'],'human_interventions':0,
            'checkpoint_bytes':(AREA/'recovery'/'runs'/result['id']/'checkpoint.json').stat().st_size,
            'receipt_bytes':(AREA/'recovery'/'runs'/result['id']/'receipt.json').stat().st_size,
            'measurements':MeasuredRuntime.measurements}
        atomic_json(AREA/'recovery'/'result.json',summary);print(json.dumps(summary,indent=2))
    finally:r.close()

if __name__=='__main__':main()
