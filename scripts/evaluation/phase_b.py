#!/usr/bin/env python3
"""Explicit local paired review-deferral evaluation; no remote or product writes."""
from __future__ import annotations

import argparse
import copy
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))

from devfactory.batch import compose_reviewed_slices, review_composed_batch
from devfactory.config import load
from devfactory.fixture import TASK, prepare as fixture_prepare
from devfactory.policy import Usage, choose_model
from devfactory.repository import git, review_snapshot
from devfactory.runner import Runner, SCHEMA, WORKER_RULES
from devfactory.runtime import Runtime
from devfactory.state import atomic_json, digest

EXPERIMENT = 'phase-b-pair-3'
AREA = ROOT / '.factory' / 'evaluation' / 'experiments' / EXPERIMENT
PYTHON = str(ROOT / '.venv' / 'bin' / 'python')
CLAMP_CHECK = [PYTHON, '-m', 'unittest', '-v', 'test_clamp']
PALINDROME_CHECK = [PYTHON, '-m', 'unittest', '-v', 'test_palindrome']
FULL_CHECK = [PYTHON, '-m', 'unittest', '-v']
SYNTAX_CHECK = [PYTHON, '-m', 'py_compile', 'clamp.py', 'palindrome.py']
SECOND = dict(TASK, id='palindrome-v1', priority=2,
              description='Implement is_palindrome(text) in palindrome.py.',
              acceptance=('Return True when the Unicode letters and digits in text read the same '
                          'forwards and backwards after casefolding; ignore other characters. '
                          'An empty significant sequence is a palindrome. Do not modify tests.'),
              paths=['palindrome.py'], checks=['palindrome'])
ORACLE = '''from clamp import clamp
from palindrome import is_palindrome
assert clamp(-5, 0, 4) == 0
assert clamp(8, 0, 4) == 4
assert clamp(0, 0, 4) == 0
assert clamp(4, 0, 4) == 4
try: clamp(2, 4, 0)
except ValueError: pass
else: raise AssertionError("inverted bounds")
assert is_palindrome("A man, a plan, a canal: Panama!")
assert is_palindrome("Àbà")
assert is_palindrome("ßs")
assert is_palindrome("İ")
assert is_palindrome("!!!")
assert not is_palindrome("ab")
assert not is_palindrome("12a")
'''


def prepare():
    cfg = load(ROOT)
    cfg['state_dir'] = str(AREA / 'source-state')
    cfg = fixture_prepare(cfg, 'pair')
    repo = Path(cfg['projects']['pair']['path'])
    if not (repo / 'palindrome.py').exists():
        (repo / 'palindrome.py').write_text('def is_palindrome(text):\n    return text == text[::-1]\n')
        (repo / 'test_palindrome.py').write_text('''import unittest
from palindrome import is_palindrome
class PalindromeTests(unittest.TestCase):
    def test_simple(self): self.assertTrue(is_palindrome("radar"))
    def test_case_and_punctuation(self): self.assertTrue(is_palindrome("Madam, I'm Adam"))
    def test_casefold_expansion(self): self.assertTrue(is_palindrome("ßs"))
    def test_negative(self): self.assertFalse(is_palindrome("hello"))
''')
        (repo / 'AGENTS.md').write_text('Only change clamp.py and palindrome.py for their respective tasks. Preserve tests. No remote actions.\n')
        with (repo / 'BACKLOG.md').open('a') as out:
            out.write('\n```factory-task\n' + json.dumps(SECOND, indent=2) + '\n```\n')
        git(repo, 'add', 'AGENTS.md', 'BACKLOG.md', 'palindrome.py', 'test_palindrome.py')
        git(repo, '-c', 'user.name=DevFactory Evaluation', '-c', 'user.email=evaluation@localhost',
            'commit', '-qm', 'Frozen disjoint paired tasks')
    base = git(repo, 'rev-parse', 'HEAD')
    source = {'base_sha': base, 'backlog_hash': digest((repo / 'BACKLOG.md').read_text()),
              'case': EXPERIMENT}
    source_file = AREA / 'source.json'
    if source_file.exists() and json.loads(source_file.read_text()) != source:
        raise RuntimeError('Evaluation source drift; use a new experiment namespace')
    atomic_json(source_file, source)
    cfg['projects']['pair']['base_sha'] = base
    cfg['projects']['pair']['checks'] = {'unit': CLAMP_CHECK, 'palindrome': PALINDROME_CHECK,
                                          'syntax': SYNTAX_CHECK, 'full': FULL_CHECK}
    cfg['projects']['pair']['final_checks'] = ['syntax']
    cfg['projects']['pair']['boundary'] = 'Frozen local synthetic pair. No product or remote access.'
    cfg['batching']['enabled'] = False
    cfg['integration']['push'] = False
    cfg['integration']['pull_request'] = False
    return cfg, repo, source


def assess(worktree, base, label):
    destination = AREA / 'assessments' / label
    review_snapshot(Path(worktree), destination, base)
    suite = subprocess.run(FULL_CHECK, cwd=destination, capture_output=True, text=True, timeout=120)
    oracle = subprocess.run([PYTHON, '-c', ORACLE], cwd=destination,
                            capture_output=True, text=True, timeout=30)
    (destination / 'suite.log').write_text(suite.stdout + suite.stderr)
    (destination / 'oracle.log').write_text(oracle.stdout + oracle.stderr)
    return {'suite_exit': suite.returncode, 'oracle_exit': oracle.returncode,
            'quality': 'PASS' if suite.returncode == oracle.returncode == 0 else 'FAIL',
            'logs': str(destination)}


def factory_variant(cfg, source, variant):
    local_cfg = copy.deepcopy(cfg)
    local_cfg['state_dir'] = str(AREA / variant / 'state')
    started = time.monotonic()
    runner = Runner(local_cfg, emit=lambda event: print(event, flush=True))
    try:
        runs = runner.run('pair', max_tasks=2, defer_review=(variant == 'deferred'))
    finally:
        runner.close()
    expected = 'REVIEW_DEFERRED_LOCAL' if variant == 'deferred' else 'READY_LOCAL'
    result = {'variant': variant, 'slice_states': [r['state'] for r in runs],
              'slice_ids': [r.get('id') for r in runs], 'state': 'INCOMPLETE',
              'review_findings': [], 'model_turns': sum(len(r.get('data', {}).get('turns', [])) for r in runs)}
    if len(runs) == 2 and all(r['state'] == expected for r in runs):
        batch = compose_reviewed_slices(runs, local_cfg['state_dir'], deferred=(variant == 'deferred'))
        local_cfg['projects']['pair']['final_checks'] = ['full']
        review = review_composed_batch(local_cfg, batch)
        result.update(state=review['state'], batch_id=batch['batch_id'],
                      review=review.get('review'), review_findings=review.get('findings', []),
                      model_turns=result['model_turns'] + review.get('model_turns', 0),
                      assessment=assess(batch['worktree'], source['base_sha'], variant))
    result['workflow_seconds'] = time.monotonic() - started
    result['slice_usage'] = [r.get('data', {}).get('usage') for r in runs]
    result['batch_usage'] = review.get('usage') if result.get('batch_id') else None
    return result


def native_variant(cfg, repo, source):
    worktree = AREA / 'native' / 'worktree'
    if worktree.exists():
        raise RuntimeError('Native worktree exists without a receipt; reconcile before redispatch')
    worktree.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(['git', 'clone', '--quiet', '--no-hardlinks', str(repo), str(worktree)], check=True)
    started = time.monotonic()
    usage = Usage()
    turns = []
    checks = []
    with Runtime(worktree) as runtime:
        selection = choose_model('fast', cfg, runtime.catalog, runtime.native, baseline=True)
        instructions = WORKER_RULES.replace('DevFactory runs one bounded local task;',
                                            'Run two bounded local development tasks;')
        thread = runtime.start(worktree, selection, instructions +
                               '\nImplement both tasks, run their tests, and self-review the combined diff. Do not commit.\n')
        payload = json.dumps({'tasks': [TASK, SECOND], 'validation_commands': [FULL_CHECK]},
                             separators=(',', ':'))
        state = 'INCOMPLETE'
        for attempt in range(3):
            response = runtime.turn(thread, payload, selection, output_schema=SCHEMA,
                                    deadline=time.time() + cfg['budget']['deadline_seconds'])
            if response.get('usage'):
                usage.observe(thread, response['usage'])
            turns.append({k: response.get(k) for k in ('turn_id', 'status', 'usage', 'effective_model')})
            check = runtime.command(worktree, FULL_CHECK, timeout=120)
            checks.append({'exit_code': check.get('exitCode')})
            if response['status'] != 'completed':
                state = 'BLOCKED_RUNTIME'
                break
            if check.get('exitCode') == 0:
                state = 'COMPLETE_SELF_REVIEWED'
                break
            payload = ('The full test suite failed. Diagnose and repair within the two task scopes.\n' +
                       check.get('stdout', '')[-4000:] + check.get('stderr', '')[-4000:])
    return {'variant': 'native', 'state': state, 'model_turns': len(turns),
            'turns': turns, 'usage': usage.aggregate(), 'checks': checks,
            'workflow_seconds': time.monotonic() - started,
            'assessment': assess(worktree, source['base_sha'], 'native')}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--audit-existing', action='store_true',
                        help='Rerun the current independent oracle on preserved assessment snapshots')
    parser.add_argument('--variant', choices=['phase-a', 'deferred', 'native'])
    args = parser.parse_args()
    cfg, repo, source = prepare()
    if args.audit_existing:
        rows = {}
        for variant in ('phase-a', 'deferred', 'native'):
            snapshot = AREA / 'assessments' / variant
            if not snapshot.exists():
                continue
            checked = subprocess.run([PYTHON, '-c', ORACLE], cwd=snapshot,
                                     capture_output=True, text=True, timeout=30)
            rows[variant] = {'oracle_exit': checked.returncode,
                             'failure_excerpt': (checked.stderr or checked.stdout)[-1000:]}
        report = {'experiment': EXPERIMENT, 'source': source,
                  'oracle_hash': digest(ORACLE), 'results': rows}
        atomic_json(AREA / 'results' / 'posthoc-oracle.json', report)
        print(json.dumps(report, indent=2))
        return
    if not args.live:
        print(json.dumps({'source': str(repo), **source}, indent=2))
        return
    if not args.variant:
        parser.error('--live requires one explicit --variant')
    receipt = AREA / 'results' / (args.variant + '.json')
    if receipt.exists():
        print('EXISTING_EVALUATION', receipt)
        return
    print('START', args.variant, source, flush=True)
    result = native_variant(cfg, repo, source) if args.variant == 'native' else factory_variant(cfg, source, args.variant)
    result.update(experiment=EXPERIMENT, source=source,
                  factory_revision=git(ROOT, 'rev-parse', 'HEAD'), runtime='0.157.1')
    atomic_json(receipt, result)
    print('RESULT', json.dumps({'variant': args.variant, 'state': result['state'],
                                'model_turns': result['model_turns'], 'assessment': result.get('assessment'),
                                'receipt': str(receipt)}), flush=True)


if __name__ == '__main__':
    main()
