import sys,io,tarfile,subprocess,json
from pathlib import Path
sys.path.insert(0,'scripts/evaluation')
from run import AREA,CASES,PYTHON
refs={'small':'def2dabea858b6ecb84ee0c52e6e07929f2c409c','medium':'141f38bcf6a027b36f9a59f66f704cdb930ace19','debug':'752799b5c88e0823f1bd93e073edab0a6a7e5648','refactor':'237388cc3220bdc7cfacc6f766304a49b42fb8e7','long':'fbb9a98d8c7b914fcc952afd4976c1bc8deebe87'}
results=[]
for c in CASES:
 dest=AREA/'references'/c['id'];dest.mkdir(parents=True,exist_ok=True)
 data=subprocess.check_output(['git','-C',str(AREA/'upstream'),'archive',refs[c['id']]])
 with tarfile.open(fileobj=io.BytesIO(data)) as a:a.extractall(dest,filter='data')
 cmd=[PYTHON,'-c','import sys,runpy;sys.path.insert(0,".");sys.argv=["oracle",'+repr(c['id'])+'];runpy.run_path('+repr(str(Path('scripts/evaluation/oracle.py').resolve()))+',run_name="__main__")']
 r=subprocess.run(cmd,cwd=dest,capture_output=True,text=True,timeout=90)
 results.append({'case':c['id'],'reference':subprocess.check_output(['git','-C',str(AREA/'upstream'),'rev-parse',refs[c['id']]],text=True).strip(),'exit':r.returncode,'output':r.stdout+r.stderr})
 print(c['id'],r.returncode,flush=True)
(AREA/'oracle-reference.json').write_text(json.dumps(results,indent=2))
