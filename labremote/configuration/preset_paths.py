"""Default destinations for explicit Save buttons, scoped to the selected FPGA."""
from .paths import CONFIG_ROOT

def experiment_preset_path(kind,filename):
    from labremote.devices.fpga.mapping import settings_path
    path=settings_path(CONFIG_ROOT/'operations'/kind/filename)
    path.parent.mkdir(parents=True,exist_ok=True)
    return path
