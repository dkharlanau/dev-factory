"""Explicit first smoke: <=3 model-producing requests, fixture only. No retry."""
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from devfactory.config import load
from devfactory.policy import choose_model, check_quota, Usage
from devfactory.runtime import Runtime

root = Path(__file__).resolve().parents[1]
output = root / '.factory/evidence/first-live-smoke.json'
if output.exists():
    raise SystemExit('First smoke already has a receipt. Use factory doctor --live for another explicit check.')
fixture = Path(tempfile.mkdtemp(prefix='devfactory-live-'))
(fixture / 'clamp.py').write_text('def clamp(value, low, high):\n    return value\n')
(fixture / 'test_clamp.py').write_text('''import unittest
from clamp import clamp
class Tests(unittest.TestCase):
    def test_bounds(self):
        self.assertEqual(clamp(-1,0,10),0)
        self.assertEqual(clamp(20,0,10),10)
        self.assertEqual(clamp(4,0,10),4)
    def test_inverted(self):
        with self.assertRaises(ValueError): clamp(0,10,1)
''')
(fixture / 'AGENTS.md').write_text('Edit only clamp.py. Do not change tests. Validate with python3 -m unittest. No commits or remote actions.\n')
for args in [['init','-q'],['add','.'],['-c','user.name=DevFactory Fixture','-c','user.email=fixture@localhost','commit','-qm','fixture']]:
    subprocess.run(['git','-C',str(fixture),*args],check=True)
config = load(root)
receipt = {'fixture': str(fixture), 'started_at': time.time(), 'model_requests': 0, 'real_codex': True,
           'steps': [], 'parent_chat_usage': None, 'efficiency_claim': None}
usage = Usage()
def save():
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(receipt,indent=2))
def collect(method,data):
    if method == 'thread/tokenUsage/updated':
        usage.observe(data['threadId'],data['tokenUsage'])
        receipt['usage'] = usage.aggregate()
        save()
try:
    with Runtime(fixture) as runtime:
        receipt['inventory'] = runtime.inventory()
        check_quota(runtime.quota(),config['budget'])
        selection = choose_model('fast',config,runtime.catalog,runtime.native)
        receipt['selection'] = selection.dict()
        instructions = 'One bounded fixture task. Respect AGENTS.md. No network, plugins, subagents, authentication files, external writes or policy changes.'
        builder = runtime.start(fixture,selection,instructions)
        receipt['builder_thread'] = builder
        receipt['model_requests'] += 1
        save()
        result = runtime.turn(builder,'Implement clamp(value, low, high). Clamp inclusively; raise ValueError if low > high. Only change clamp.py, inspect test_clamp.py, and run its tests. Reply briefly.',selection,deadline=time.time()+120,on_event=collect)
        result.pop('final',None)
        receipt['steps'].append({'build':result})
        print('build',result['status'],flush=True)
        if result['status'] != 'completed':
            raise RuntimeError('Build did not complete')
        test = runtime.command(fixture,[sys.executable,'-m','unittest','-v'],timeout=20)
        receipt['steps'].append({'validation':test})
        save()
        if test['exitCode']:
            raise RuntimeError('Fixture acceptance failed')
        reviewer = runtime.start(fixture,selection,instructions,read_only=True)
        receipt['reviewer_thread'] = reviewer
        assert reviewer != builder
        receipt['model_requests'] += 1
        save()
        review = runtime.turn(reviewer,'Fresh review. Independently inspect git diff and clamp.py and test_clamp.py. Acceptance: inclusive clamp and ValueError for low > high, tests untouched. Tests were run by the controller with exit 0. Report PASS or concrete defects. Do not edit.',selection,deadline=time.time()+120,on_event=collect)
        receipt['review_response'] = review.pop('final',None)
        receipt['steps'].append({'review':review})
        print('review',review['status'],flush=True)
        resumed = runtime.start(fixture,selection,instructions,resume=builder)
        receipt['resume_same_thread'] = resumed == builder
        receipt['checkpoint'] = {'task':'clamp fixture','tests_exit':test['exitCode'],'next':'manual compaction lifecycle probe','changed_files':['clamp.py']}
        save()
        # Conservatively charge compaction as the third model-producing request.
        receipt['model_requests'] += 1
        save()
        compact = runtime.compact(builder,deadline=time.time()+90,checkpoint=receipt['checkpoint'],on_event=collect)
        receipt['steps'].append({'compaction':compact})
        receipt['after_compact_thread'] = runtime.read(builder)['thread']['id']
        receipt['after_compact_tests'] = runtime.command(fixture,[sys.executable,'-m','unittest'],timeout=20)['exitCode']
        print('compaction',compact,flush=True)
except BaseException as e:
    receipt['failure'] = {'type':type(e).__name__,'message':str(e)[:300]}
    raise
finally:
    receipt['wall_seconds'] = time.time()-receipt['started_at']
    receipt['usage'] = usage.aggregate()
    save()
    print(output,flush=True)
