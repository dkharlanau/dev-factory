import pytest
from devfactory.config import load
from devfactory.fixture import prepare
from fakes import reset

@pytest.fixture
def cfg(tmp_path):
    reset()
    c=load(tmp_path)
    c['state_dir']=str(tmp_path/'state')
    return prepare(c)
