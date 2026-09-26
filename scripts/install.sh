#!/bin/sh
set -eu
FACTORY_INSTALL_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$FACTORY_INSTALL_ROOT"
FACTORY_PYTHON=${FACTORY_PYTHON:-python3}
"$FACTORY_PYTHON" -c 'import sys; assert sys.version_info >= (3,11), "Factory requires Python >=3.11; set FACTORY_PYTHON"'
if [ ! -d .venv ]; then "$FACTORY_PYTHON" -m venv .venv; fi
.venv/bin/python -m pip install -r requirements.lock
.venv/bin/python -m pip install . --no-deps
.venv/bin/python -c 'import devfactory; print("DevFactory", devfactory.__version__)'
printf '%s\n' 'devfactory-owned-environment-v1' > .venv/.devfactory-owner
./factory schema
printf '%s\n' 'Installed locally. No global Codex config or plugins changed.' 'Run: ./factory doctor' 'Repository skill: $factory doctor (open a new Codex chat if needed).'
