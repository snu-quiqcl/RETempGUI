"""Central data configuration directory, independent of the current directory."""
from pathlib import Path
from copy import deepcopy
from functools import lru_cache

@lru_cache(maxsize=128)
def _parse_yaml_text(text):
    import yaml
    return yaml.safe_load(text)

def read_yaml_document(path):
    # Read current contents every time; cache parsing only, not the file snapshot.
    # Separate copies prevent one operation from changing another's frozen policy.
    return deepcopy(_parse_yaml_text(Path(path).read_text(encoding='utf-8')))

CONFIG_ROOT = Path(__file__).resolve().parent
from .migration import migrate
migrate(CONFIG_ROOT)
def registry_paths():
    paths = tuple(sorted(CONFIG_ROOT.glob('operations/*/parameter_registry.yml')))
    if not paths: raise FileNotFoundError(f'No parameter policies in {CONFIG_ROOT}')
    return paths
