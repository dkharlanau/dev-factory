#!/usr/bin/env python3
"""Read public metadata for this evaluation's known threads; zero model turns."""
import json
from pathlib import Path
from run import ROOT,AREA,Runtime,context_metrics,atomic_json


def main():
    ids=set()
    for p in (AREA/'results').glob('*.json'):
        for t in json.loads(p.read_text()).get('turns',[]):ids.add(t['thread_id'])
    for p in [AREA/'recovery/result.json',AREA/'pr-lifecycle/result.json']:
        if p.exists():
            for t in json.loads(p.read_text()).get('turns',[]):ids.add(t['thread_id'])
    records={}
    with Runtime(ROOT) as rt:
        for tid in sorted(ids):records[tid]=context_metrics(rt,tid)
        native=rt.native
    atomic_json(AREA/'thread-observations.json',{'model_turns':0,'native_default_at_observation':native,'threads':records})
    print('Observed',len(records),'owned threads; zero model turns')

if __name__=='__main__':main()
