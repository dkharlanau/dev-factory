from __future__ import annotations
import copy
import json
import sys
from pathlib import Path
from .repository import git
from .state import atomic_json

TASK = {'id':'clamp-v1','description':'Implement inclusive integer clamp in clamp.py.',
        'acceptance':'Return low below the lower bound, high above the upper bound, otherwise the input; raise ValueError for low > high. Do not modify tests.',
        'paths':['clamp.py'],'category':'bug','risk':'low','complexity':'low','verification':'strong',
        'checks':['unit'],'dependencies':[],'required_capabilities':['python'],'priority':1,'state':'EXECUTE'}


def prepare(config, name='demo'):
    cfg=copy.deepcopy(config)
    root=Path(cfg['state_dir'])/'fixtures'/name
    marker=root/'fixture-identity.json'
    if not marker.exists():
        if root.exists() and any(root.iterdir()):
            raise RuntimeError('Refusing to overwrite existing fixture directory')
        root.mkdir(parents=True,exist_ok=True)
        (root/'clamp.py').write_text('def clamp(value, low, high):\n    return value\n')
        (root/'test_clamp.py').write_text('''import unittest
from clamp import clamp
class ClampTests(unittest.TestCase):
    def test_lower(self): self.assertEqual(clamp(-2,0,10),0)
    def test_upper(self): self.assertEqual(clamp(11,0,10),10)
    def test_inside(self): self.assertEqual(clamp(5,0,10),5)
    def test_endpoints(self):
        self.assertEqual(clamp(0,0,10),0)
        self.assertEqual(clamp(10,0,10),10)
    def test_inverted(self):
        with self.assertRaises(ValueError): clamp(0,10,1)
''')
        (root/'AGENTS.md').write_text('Only change clamp.py. Preserve tests. No remote actions.\n')
        (root/'BACKLOG.md').write_text('# Fixture acceptance authority\n\n```factory-task\n'+json.dumps(TASK,indent=2)+'\n```\n')
        (root/'.gitignore').write_text('__pycache__/\nfixture-identity.json\n')
        git(root,'init','-q','-b','main')
        git(root,'-c','user.name=DevFactory Fixture','-c','user.email=fixture@localhost','add','.')
        git(root,'-c','user.name=DevFactory Fixture','-c','user.email=fixture@localhost','commit','-qm','Fixture starting commit')
        atomic_json(marker,{'base_sha':git(root,'rev-parse','HEAD')})
    base=json.loads(marker.read_text())['base_sha']
    cfg['projects'][name]={'path':str(root),'fixture':True,'base_sha':base,
        'instructions':['AGENTS.md'],'backlogs':['BACKLOG.md'],'high_risk_paths':[],
        'boundary':'Synthetic fixture only. No production claims.',
        'checks':{'unit':[sys.executable,'-m','unittest','-v']},'final_checks':['unit']}
    return cfg
