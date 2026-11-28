"""Resolve saved Workflow imports to the single current implementation.

Only historical module names are handled. New application code imports
labremote.experiments directly; aliases do not wrap execution or copy state.
"""
from importlib import import_module
from importlib.abc import Loader, MetaPathFinder
from importlib.util import spec_from_loader
from types import ModuleType
import sys

ALIASES = {
    "labremote.decay.config": "labremote.experiments.decay.config",
    "labremote.decay.plotting": "labremote.experiments.decay.plotting",
    "labremote.decay.runner": "labremote.experiments.decay.runner",
    "labremote.decay.sequence": "labremote.experiments.decay.sequence",
    "labremote.decay.storage": "labremote.experiments.decay.storage",
    "labremote.decay": "labremote.experiments.decay",
    "labremote.hom.acquisition": "labremote.experiments.hom.acquisition",
    "labremote.hom.config": "labremote.experiments.hom.config",
    "labremote.hom.plotting": "labremote.experiments.hom.plotting",
    "labremote.hom.runner": "labremote.experiments.hom.runner",
    "labremote.hom.sequence": "labremote.experiments.hom.sequence",
    "labremote.hom.storage": "labremote.experiments.hom.storage",
    "labremote.hom": "labremote.experiments.hom",
    "labremote.entanglement.acquisition": "labremote.experiments.entanglement.acquisition",
    "labremote.entanglement.config": "labremote.experiments.entanglement.config",
    "labremote.entanglement.plotting": "labremote.experiments.entanglement.plotting",
    "labremote.entanglement.runner": "labremote.experiments.entanglement.runner",
    "labremote.entanglement.sequence": "labremote.experiments.entanglement.sequence",
    "labremote.entanglement.storage": "labremote.experiments.entanglement.storage",
    "labremote.entanglement": "labremote.experiments.entanglement",
    "labremote.ion_check.acquisition": "labremote.experiments.ion_check.acquisition",
    "labremote.ion_check.config": "labremote.experiments.ion_check.config",
    "labremote.ion_check.runner": "labremote.experiments.ion_check.runner",
    "labremote.ion_check.sequence": "labremote.experiments.ion_check.sequence",
    "labremote.ion_check": "labremote.experiments.ion_check",
    "labremote.micromotion.acquisition": "labremote.experiments.micromotion.acquisition",
    "labremote.micromotion.analysis": "labremote.experiments.micromotion.analysis",
    "labremote.micromotion.config": "labremote.experiments.micromotion.config",
    "labremote.micromotion.plotting": "labremote.experiments.micromotion.plotting",
    "labremote.micromotion.runner": "labremote.experiments.micromotion.runner",
    "labremote.micromotion.sequence": "labremote.experiments.micromotion.sequence",
    "labremote.micromotion.two_rf": "labremote.experiments.micromotion.two_rf",
    "labremote.micromotion.two_rf_analysis": "labremote.experiments.micromotion.two_rf_analysis",
    "labremote.micromotion": "labremote.experiments.micromotion",
    "labremote.micromotion.secular.acquisition": "labremote.experiments.micromotion.secular.acquisition",
    "labremote.micromotion.secular.config": "labremote.experiments.micromotion.secular.config",
    "labremote.micromotion.secular.model": "labremote.experiments.micromotion.secular.model",
    "labremote.micromotion.secular.plotting": "labremote.experiments.micromotion.secular.plotting",
    "labremote.micromotion.secular.runner": "labremote.experiments.micromotion.secular.runner",
    "labremote.micromotion.secular.sequence": "labremote.experiments.micromotion.secular.sequence",
    "labremote.micromotion.secular": "labremote.experiments.micromotion.secular",
    "labremote.phase_shifter.acquisition": "labremote.experiments.phase_shifter.acquisition",
    "labremote.phase_shifter.calibration": "labremote.experiments.phase_shifter.calibration",
    "labremote.phase_shifter.config": "labremote.experiments.phase_shifter.config",
    "labremote.phase_shifter.halfpi": "labremote.experiments.phase_shifter.halfpi",
    "labremote.phase_shifter.halfpi_tab": "labremote.experiments.phase_shifter.halfpi_tab",
    "labremote.phase_shifter.hold": "labremote.experiments.phase_shifter.hold",
    "labremote.phase_shifter.hold_tab": "labremote.experiments.phase_shifter.hold_tab",
    "labremote.phase_shifter.interpolation": "labremote.experiments.phase_shifter.interpolation",
    "labremote.phase_shifter.rabi": "labremote.experiments.phase_shifter.rabi",
    "labremote.phase_shifter.rabi_runner": "labremote.experiments.phase_shifter.rabi_runner",
    "labremote.phase_shifter.rabi_sequence": "labremote.experiments.phase_shifter.rabi_sequence",
    "labremote.phase_shifter.rabi_tab": "labremote.experiments.phase_shifter.rabi_tab",
    "labremote.phase_shifter.runner": "labremote.experiments.phase_shifter.runner",
    "labremote.phase_shifter.selectors": "labremote.experiments.phase_shifter.selectors",
    "labremote.phase_shifter.sequence": "labremote.experiments.phase_shifter.sequence",
    "labremote.phase_shifter.tab": "labremote.experiments.phase_shifter.tab",
    "labremote.phase_shifter": "labremote.experiments.phase_shifter",
    "labremote.characterization": "labremote.experiments.characterization",
    "labremote.characterization.config": "labremote.experiments.characterization.shared.config",
    "labremote.characterization.archive": "labremote.experiments.characterization.shared.archive",
    "labremote.characterization.fluorescence": "labremote.experiments.characterization.fluorescence.model",
    "labremote.characterization.runner": "labremote.experiments.characterization.fluorescence.runner",
    "labremote.characterization.rabi": "labremote.experiments.characterization.rabi.model",
    "labremote.characterization.rabi_sequence": "labremote.experiments.characterization.rabi.sequence",
    "labremote.characterization.rabi_runner": "labremote.experiments.characterization.rabi.runner",
    "labremote.characterization.rabi_live": "labremote.experiments.characterization.rabi.live",
    "labremote.characterization.pulse_experiment": "labremote.experiments.characterization.shared.pulse_model",
    "labremote.characterization.pulse_runner": "labremote.experiments.characterization.shared.pulse_runner",
    "labremote.characterization.live_pulse": "labremote.experiments.characterization.shared.live_pulse",
    "labremote.characterization.initialization_sequence": "labremote.experiments.characterization.initialization.sequence",
    "labremote.characterization.initialization_analysis": "labremote.experiments.characterization.initialization.analysis",
    "labremote.characterization.ramsey_sequence": "labremote.experiments.characterization.ramsey.sequence",
    "labremote.characterization.ramsey_fit": "labremote.experiments.characterization.ramsey.analysis",
    "labremote.characterization.spin_echo_sequence": "labremote.experiments.characterization.spin_echo.sequence",
    "labremote.characterization.spin_echo_analysis": "labremote.experiments.characterization.spin_echo.analysis",
    "labremote.characterization.spam_sequence": "labremote.experiments.characterization.spam.sequence",
    "labremote.characterization.spam_scan": "labremote.experiments.characterization.spam_scan.model",
    "labremote.characterization.spam_scan_runner": "labremote.experiments.characterization.spam_scan.runner",
    "labremote.ui.daily_characterization": "labremote.experiments.characterization.tab",
    "labremote.ui.rabi_tab": "labremote.experiments.characterization.rabi.tab",
    "labremote.ui.pulse_experiment_tab": "labremote.experiments.characterization.shared.pulse_tab",
    "labremote.ui.pulse_controls": "labremote.experiments.characterization.shared.pulse_controls",
    "labremote.ui.spam_scan_tab": "labremote.experiments.characterization.spam_scan.tab",
    "labremote.ui.spam_parameters": "labremote.experiments.characterization.spam.parameters",
    "labremote.ui.decay_tab": "labremote.experiments.decay.tab",
    "labremote.ui.hom_tab": "labremote.experiments.hom.tab",
    "labremote.ui.entanglement_tab": "labremote.experiments.entanglement.tab",
    "labremote.ui.entanglement_view": "labremote.experiments.entanglement.view",
    "labremote.ui.ion_check_tab": "labremote.experiments.ion_check.tab",
    "labremote.ui.micromotion_tab": "labremote.experiments.micromotion.tab",
    "labremote.ui.secular_scan_tab": "labremote.experiments.micromotion.secular.tab",
    "labremote.ui.two_rf_compensation_tab": "labremote.experiments.micromotion.two_rf_tab",
    "labremote.ui.phase_hold_parameters": "labremote.experiments.phase_shifter.hold_parameters",
    "labremote.ui.motor_scan_tab": "labremote.experiments.motor_scan.tab",
    "labremote.operation.fpga.rabi": "labremote.experiments.characterization.rabi.acquisition",
    "labremote.operation.fpga.fluorescence": "labremote.experiments.characterization.fluorescence.acquisition",
    "labremote.operation.fpga.pulse_experiment": "labremote.experiments.characterization.shared.pulse_acquisition",
    "labremote.operation.fpga.decay": "labremote.experiments.decay.acquisition",
    "labremote.runtime.motor_scan_runner": "labremote.experiments.motor_scan.runner",
    "labremote.devices.fpga.scan_model": "labremote.experiments.motor_scan.model"
}
PACKAGES = frozenset([
    "labremote.characterization",
    "labremote.decay",
    "labremote.entanglement",
    "labremote.hom",
    "labremote.ion_check",
    "labremote.micromotion",
    "labremote.micromotion.secular",
    "labremote.phase_shifter"
])


class _AliasLoader(Loader):
    def __init__(self, name, target):
        self.name, self.target = name, target

    def create_module(self, spec):
        if self.name in PACKAGES:
            # Separate package namespaces keep old "from ... import rabi"
            # pointing to rabi.model, while the new rabi package stays intact.
            module = ModuleType(self.name)
            module.__path__ = []
            module.__package__ = self.name
            def attribute(name):
                child = self.name + '.' + name
                if child in ALIASES:
                    return import_module(child)
                return getattr(import_module(self.target), name)
            module.__getattr__ = attribute
            return module
        module = import_module(self.target)
        self.target_spec = module.__spec__
        return module

    def exec_module(self, module):
        if self.name not in PACKAGES:
            # importlib assigns the alias spec after create_module; keep the
            # canonical module's identity and reload behavior unchanged.
            module.__spec__ = self.target_spec


class _LegacyExperimentFinder(MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        destination = ALIASES.get(fullname)
        if destination is None:
            return None
        return spec_from_loader(fullname, _AliasLoader(fullname, destination),
                                is_package=fullname in PACKAGES)


def install():
    if not any(isinstance(finder, _LegacyExperimentFinder) for finder in sys.meta_path):
        sys.meta_path.insert(0, _LegacyExperimentFinder())
