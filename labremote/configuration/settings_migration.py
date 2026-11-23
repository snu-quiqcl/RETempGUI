"""Idempotent original-byte backups for settings imported from earlier layouts."""
import hashlib
from pathlib import Path
from .paths import CONFIG_ROOT,PROJECT_ROOT
def backup_file(path):
    path=Path(path);raw=path.read_bytes()
    digest=hashlib.sha256(raw).hexdigest()[:16]
    try:relative=path.relative_to(CONFIG_ROOT)
    except ValueError:relative=Path(path.name)
    target=PROJECT_ROOT/'labremote/data/config_backups/fpga_mapping'/digest/relative
    if not target.exists():
        target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw)
    return target
