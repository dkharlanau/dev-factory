from devfactory.navigation import repository_registry
from devfactory.repository import git


def test_repository_registry_is_task_local_and_cold_by_default(tmp_path):
    repo=tmp_path/'repo';repo.mkdir()
    (repo/'src').mkdir();(repo/'src'/'feature.py').write_text('x=1\n');(repo/'src'/'neighbor.py').write_text('x=2\n')
    (repo/'docs').mkdir();(repo/'docs'/'archive').mkdir();(repo/'docs'/'archive'/'old.md').write_text('old\n')
    (repo/'AGENTS.md').write_text('guide\n')
    git(repo,'init','-q','-b','main');git(repo,'add','.')
    git(repo,'-c','user.name=Fixture','-c','user.email=f@localhost','commit','-qm','init')
    base=git(repo,'rev-parse','HEAD')
    registry,nav=repository_registry(repo,base,['src/feature.py'],guidance_files=['AGENTS.md'],
                                     cold_paths=['docs/archive/'],max_files=10)
    assert 'src/feature.py' in nav['files'] and 'src/neighbor.py' in nav['files']
    assert 'AGENTS.md' in nav['files'] and 'docs/archive/old.md' not in nav['files']
    assert registry['cold_excluded']==1 and registry['file_count']==4
