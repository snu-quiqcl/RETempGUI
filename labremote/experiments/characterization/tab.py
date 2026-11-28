from labremote.ui.responsive import FlowLayout
from labremote.ui.pin_selector import PinSelector
from labremote.devices.fpga.mapping import settings_path
from labremote.devices.fpga.mapping import bound_methods
"""Daily experiment views share the existing FPGA worker and workflow API."""
from pathlib import Path
from labremote.data_paths import characterization_directory
import numpy as np
from PyQt5 import QtCore, QtWidgets
from labremote.api.devices import device_api
from labremote.experiments.characterization.shared import config
from labremote.experiments.characterization.fluorescence.model import draw


from labremote.experiments.characterization.fluorescence.tab import FluorescenceTab

class DailyCharacterization(QtWidgets.QTabWidget):
    def __init__(self,worker,bindings,parent=None):
        super().__init__(parent)
        from labremote.ui.workflow_tab import WorkflowTab
        self.workflow=WorkflowTab(bindings,self);self.addTab(self.workflow,'Workflow')
        template=self.workflow.workflow_root/'daily_fluorescence.py'
        if worker.profile.device_id != 'fpga_local':
            destination=self.workflow.workflow_root/'local'/worker.profile.device_id/'daily_fluorescence.py'
            if not destination.exists():
                destination.parent.mkdir(parents=True,exist_ok=True)
                if template.exists():
                    source=template.read_text(encoding='utf-8')
                else:
                    # The editable workflow directory is private/ignored and
                    # need not exist on another computer or a clean checkout.
                    source=("def main(devices):\n"
                            "    fpga = devices.fpga('fpga_local')\n"
                            "    ea = fpga.run_fluorescence('EA').wait()\n"
                            "    ec = fpga.run_fluorescence('EC').wait()\n"
                            "    return {'EA': ea, 'EC': ec}\n")
                source=source.replace("'fpga_local'",repr(worker.profile.device_id))
                destination.write_text(source,encoding='utf-8')
            template=destination
        self.workflow.load_path(str(template),check_unsaved=False)
        self.experiments={c:FluorescenceTab(worker,c,self) for c in ('EA','EC')}
        for c,tab in self.experiments.items():self.addTab(tab,c+' Fluorescence')
        from labremote.experiments.characterization.rabi.tab import RabiTab
        self.rabi_experiments={c:RabiTab(worker,c,bindings,self) for c in ('EA','EC')}
        for c,tab in self.rabi_experiments.items():self.addTab(tab,c+' Rabi')
        from labremote.experiments.characterization.shared.pulse_tab import PulseExperimentTab
        self.pulse_experiments={(kind,c):PulseExperimentTab(worker,kind,c,bindings,self) for kind in ('initialization','ramsey','spin_echo','spam') for c in ('EA','EC')}
        for (kind,c),tab in self.pulse_experiments.items():self.addTab(tab,c+' '+{'spin_echo':'Spin Echo','initialization':'Initialization','ramsey':'Ramsey','spam':'SPAM'}[kind])
        self.setCurrentWidget(self.experiments['EA'])

    def shutdown(self):
        self.workflow.shutdown()
        for tab in (*self.experiments.values(),*self.rabi_experiments.values(),*self.pulse_experiments.values()):tab.timer.stop()

    def still_running(self):return self.workflow.still_running()
