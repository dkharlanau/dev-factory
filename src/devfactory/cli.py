from __future__ import annotations
import argparse
import json
import os
import sys
from pathlib import Path
from .config import load
from .policy import Stop
from .state import Store, TERMINAL


def default_root():
    if os.environ.get('FACTORY_ROOT'):
        return Path(os.environ['FACTORY_ROOT']).expanduser()
    for parent in Path(__file__).resolve().parents:
        if (parent/'factory').is_file() and (parent/'pyproject.toml').is_file():
            return parent
    return None


def parser():
    p=argparse.ArgumentParser(prog='factory',description='Bounded foreground control over official Codex; no background scheduler.')
    p.add_argument('--root',type=Path,default=default_root())
    p.add_argument('--config',type=Path)
    sub=p.add_subparsers(dest='command',required=True)
    doctor=sub.add_parser('doctor'); doctor.add_argument('--live',action='store_true')
    sub.add_parser('models')
    for name in ('prep','plan','run','compile'):
        cmd=sub.add_parser(name); cmd.add_argument('project')
        if name=='run': cmd.add_argument('--max-tasks',type=int,default=1)
        if name=='compile': cmd.add_argument('--max-tasks',type=int,default=50)
    sub.add_parser('status')
    report=sub.add_parser('report')
    report.add_argument('run_id',nargs='?')
    report.add_argument('--summary',action='store_true',help='Show compact receipt fields without turn histories')
    for name in ('pause','resume'):
        cmd=sub.add_parser(name)
        cmd.add_argument('run_id')
        if name=='resume':
            cmd.add_argument('--revalidate',action='store_true',help='Refresh failed validation before repairing a preserved handoff')
            cmd.add_argument('--local-plan',type=Path,help='Resume the exact saved contract/base without GitHub refresh; local-only execution')
    batch=sub.add_parser('batch'); batch.add_argument('run_ids',nargs='+')
    sub.add_parser('batch-review').add_argument('batch_id')
    sub.add_parser('batch-integrate').add_argument('batch_id')
    bench=sub.add_parser('benchmark'); bench.add_argument('--live',action='store_true')
    sub.add_parser('schema')
    return p


def summarize_run(run):
    data=run['data']
    checks={}
    failed=[]
    for check in data.get('tests',[]):
        name=check.get('check')
        if not name: continue
        checks[name]={'exit_code':check.get('exit_code'),'stage':check.get('stage')}
        if check.get('exit_code') not in (None,0) and name not in failed:
            failed.append(name)
    return {
        'run_id':run['id'],
        'project':run['project'],
        'state':run['state'],
        'task_id':data.get('task_id'),
        'base_sha':data.get('base_sha'),
        'head_sha':data.get('head_sha'),
        'changed_file_count':len(data.get('changed_files',[])),
        'latest_checks':checks,
        'failed_checks_seen':failed,
        'review':data.get('review'),
        'disposition':data.get('disposition'),
        'reason':data.get('reason'),
        'next_step':data.get('next_step'),
        'reviewed_sha':data.get('reviewed_sha'),
        'validated_fingerprint':data.get('validated_fingerprint'),
        'reviewed_fingerprint':data.get('reviewed_fingerprint'),
        'wall_seconds':data.get('wall_seconds'),
        'usage':data.get('usage'),
        'worktree':data.get('worktree'),
    }


def main(argv=None):
    args=parser().parse_args(argv)
    try:
        if args.root is None:
            raise Stop('NATIVE_HANDOFF','Factory installation root unknown; set FACTORY_ROOT or --root explicitly')
        config=load(args.root,args.config)
        if args.command=='schema':
            result={'version':'2','commands':['doctor [--live]','models','prep <project>','plan <project>',
                    'compile <project> [--max-tasks N]','run <project> [--max-tasks N]',
                    'batch <run-id> <run-id> [...]','batch-review <batch-id>','batch-integrate <batch-id>',
                    'status','pause <run-id>','resume <run-id> [--revalidate] [--local-plan PATH]','report [run-id] [--summary]','benchmark [--live]'],
                    'model_profiles':list(config['profiles']),
                    'global_worker_limit':1,'merge':False,'deploy':False,'background':False}
        elif args.command in ('doctor','models'):
            from .diagnostics import doctor
            result=doctor(config)
            if args.command=='models': result={k:result[k] for k in ('models','profiles','native','parent_model')}
            elif args.live:
                from .fixture import prepare
                from .runner import Runner
                config=prepare(config,'smoke')
                runner=Runner(config,emit=lambda s:print(s,file=sys.stderr,flush=True))
                try: result['live']=runner.run('smoke',max_tasks=1)
                finally: runner.close()
        elif args.command in ('prep','plan','run','compile'):
            if args.project=='demo':
                from .fixture import prepare
                config=prepare(config)
            if args.command=='prep':
                from .navigation import prepare_project
                result=prepare_project(config,args.project)
            elif args.command=='compile':
                from .campaign import compile_campaign
                result=compile_campaign(config,args.project,max_tasks=args.max_tasks)
            elif args.command=='plan':
                from .tasks import resolve
                result=resolve(config,args.project)
            else:
                from .runner import Runner
                runner=Runner(config,emit=lambda s:print(s,file=sys.stderr,flush=True))
                try: result=runner.run(args.project,max_tasks=args.max_tasks)
                finally: runner.close()
        elif args.command=='resume':
            from .runner import Runner
            # Reconstruct fixture adapter from stable fixture identity, not a saved prompt.
            store=Store(config['state_dir'])
            try:
                saved=store.get(args.run_id)
                project=saved['project']
            finally: store.close()
            if project in ('demo','smoke'):
                from .fixture import prepare
                config=prepare(config,project)
            if saved['data'].get('operation')=='batch-review':
                if args.local_plan:raise Stop('BLOCKED_RECONCILIATION','Local plans apply only to ordinary preserved runs')
                if args.revalidate:raise Stop('BLOCKED_RECONCILIATION','Revalidation applies only to ordinary validation handoffs')
                from .batch import load_composition,review_composed_batch
                result=review_composed_batch(config,load_composition(config['state_dir'],saved['data']['batch_id']))
            elif saved['data'].get('operation')=='batch-integrate':
                if args.local_plan or args.revalidate:
                    raise Stop('BLOCKED_RECONCILIATION','Batch remote reconciliation does not accept local plans or revalidation')
                from .batch import integrate_reviewed_batch,load_composition
                result=integrate_reviewed_batch(config,load_composition(config['state_dir'],saved['data']['batch_id']))
            elif saved['data'].get('operation')=='batch':
                if args.local_plan:raise Stop('BLOCKED_RECONCILIATION','Local plans apply only to ordinary preserved runs')
                if args.revalidate:raise Stop('BLOCKED_RECONCILIATION','Revalidation applies only to ordinary validation handoffs')
                from .batch import compose_reviewed_slices
                store=Store(config['state_dir'])
                try: runs=[store.get(rid) for rid in saved['data']['run_ids']]
                finally: store.close()
                result=compose_reviewed_slices(runs,config['state_dir'])
            else:
                runner=Runner(config,emit=lambda s:print(s,file=sys.stderr,flush=True))
                try: result=runner.resume(args.run_id,revalidate=args.revalidate,local_plan=args.local_plan)
                finally: runner.close()
        elif args.command=='batch':
            if len(args.run_ids)<2:
                raise Stop('BLOCKED_BATCH','batch requires at least two run ids')
            store=Store(config['state_dir'])
            try: runs=[store.get(rid) for rid in args.run_ids]
            finally: store.close()
            from .batch import compose_reviewed_slices
            result=compose_reviewed_slices(runs,config['state_dir'])
        elif args.command=='batch-review':
            from .batch import load_composition,review_composed_batch
            composition=load_composition(config['state_dir'],args.batch_id)
            project=composition['project']
            if project in ('demo','smoke'):
                from .fixture import prepare
                config=prepare(config,project)
            result=review_composed_batch(config,composition)
        elif args.command=='batch-integrate':
            from .batch import integrate_reviewed_batch,load_composition
            result=integrate_reviewed_batch(config,load_composition(config['state_dir'],args.batch_id))
        elif args.command=='benchmark':
            from .benchmark import benchmark
            result=benchmark(config,live=args.live)
        else:
            store=Store(config['state_dir'])
            try:
                if args.command=='pause':
                    r=store.pause(args.run_id); result={'run_id':r['id'],'state':r['state'],'pause_requested':r['state'] not in TERMINAL}
                elif args.command=='report':
                    result=store.get(args.run_id) if args.run_id else store.all()
                    if args.summary:
                        rows=result if isinstance(result,list) else [result]
                        summaries=[summarize_run(row) for row in rows]
                        result=summaries if isinstance(result,list) else summaries[0]
                else:
                    result=[{'run_id':r['id'],'project':r['project'],'state':r['state'],'updated':r['updated'],
                             'worktree':r['data'].get('worktree'),'phase':r['data'].get('phase')} for r in store.all()]
            finally: store.close()
        print(json.dumps(result,indent=2,default=str))
        if args.command in ('run','resume','batch-review','batch-integrate') or (args.command=='doctor' and args.live):
            values=result.get('live',[]) if args.command=='doctor' else (result if isinstance(result,list) else [result])
            if any(x.get('state') not in ('READY_LOCAL','COMPOSED_LOCAL','BATCH_READY_LOCAL','BATCH_PR_OPENED','PR_OPENED','PR_READY','EXISTING_COMPLETION','IDLE') for x in values):
                return 2
        return 0
    except Stop as e:
        print(json.dumps({'state':e.state,'reason':e.reason},indent=2))
        return 2
    except (OSError,ValueError) as e:
        print(json.dumps({'state':'BLOCKED_LOCAL','reason':type(e).__name__}),file=sys.stderr)
        return 2


if __name__=='__main__':
    sys.exit(main())
