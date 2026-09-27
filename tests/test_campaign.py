import copy
import json
from pathlib import Path
from devfactory.campaign import compile_campaign
from devfactory.repository import git
from devfactory.fixture import TASK


def test_campaign_compiles_compatible_backlog_without_model_turns(cfg):
    repo=Path(cfg['projects']['demo']['path'])
    task=copy.deepcopy(TASK)
    task.update(id='second',priority=2,description='Create second local note.',
                acceptance='Create second.txt.',paths=['second.txt'])
    with (repo/'BACKLOG.md').open('a') as f:
        f.write('\n```factory-task\n'+json.dumps(task)+'\n```\n')
    git(repo,'add','BACKLOG.md')
    git(repo,'-c','user.name=Fixture','-c','user.email=f@localhost','commit','-qm','campaign task')
    cfg['projects']['demo']['base_sha']=git(repo,'rev-parse','HEAD')
    result=compile_campaign(cfg,'demo',max_tasks=2)
    assert result['state']=='COMPILED' and result['model_turns']==0
    assert result['task_count']==2 and result['batch_count']==1
    assert result['batches'][0]['task_ids']==['clamp-v1','second']
    assert Path(result['artifact']).exists()
