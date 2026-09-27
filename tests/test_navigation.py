from pathlib import Path
from devfactory.navigation import repository_registry, analyze_repository, roots_related, prepare_project
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


def test_repo_prep_detects_cold_output_instruction_bloat_and_cochange(tmp_path):
    repo=tmp_path/'repo2';repo.mkdir()
    (repo/'src').mkdir();(repo/'tests').mkdir();(repo/'dist').mkdir()
    (repo/'src'/'feature.py').write_text('x=1\n')
    (repo/'tests'/'test_feature.py').write_text('x=1\n')
    (repo/'dist'/'bundle.js').write_text('generated\n')
    (repo/'AGENTS.md').write_text(('rule\n'*125)+'Before every edit read all project documentation.\n')
    git(repo,'init','-q','-b','main');git(repo,'add','.')
    git(repo,'-c','user.name=Fixture','-c','user.email=f@localhost','commit','-qm','init')
    for i in range(2):
        (repo/'src'/'feature.py').write_text(f'x={i+2}\n')
        (repo/'tests'/'test_feature.py').write_text(f'x={i+2}\n')
        git(repo,'add','src/feature.py','tests/test_feature.py')
        git(repo,'-c','user.name=Fixture','-c','user.email=f@localhost','commit','-qm',f'pair {i}')
    base=git(repo,'rev-parse','HEAD')
    profile=analyze_repository(repo,base,configured_cold_paths=['docs/archive/'])
    codes={f['code'] for f in profile['findings']}
    assert 'AGENT_INSTRUCTION_BLOAT' in codes
    assert 'TRACKED_COLD_OUTPUT' in codes
    assert 'dist/' in profile['context']['auto_cold_paths']
    assert roots_related({'src'},{'tests'},profile)


def test_prepare_project_persists_zero_model_profile(cfg):
    result=prepare_project(cfg,'demo')
    assert result['state']=='PREPARED'
    assert result['cleanup']['product_files_changed'] is False
    assert Path(result['profile_path']).exists()
    assert result['metrics']['tracked_files'] >= 4
