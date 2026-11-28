from labremote.experiments.entanglement.runner import EntanglementRunner
from . import config

class EntanglementNoMirrorRunner(EntanglementRunner):
    config_module=config
    experiment='entanglement_no_mirror'
    mapping_experiment='entanglement_no_mirror'
