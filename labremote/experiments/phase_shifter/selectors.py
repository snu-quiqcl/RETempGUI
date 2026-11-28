"""Phase experiments use the shared mapping table, with common nicknames."""
from types import SimpleNamespace
from PyQt5 import QtCore
from labremote.devices.fpga.mapping import CURRENT
from labremote.devices.fpga import routing
from labremote.ui.experiment_mapping import MappingEditor

class PhaseShifterEtcTab(MappingEditor):
    selection_changed=QtCore.pyqtSignal()
    def __init__(self,hd,parent=None):
        state=CURRENT.get()
        if state is None:raise ValueError('Select an FPGA before creating its mapping editor')
        self.hd=hd
        super().__init__(SimpleNamespace(profile=state[0]),'phase_shifter',
                         dict(outputs={},phase_outputs=[None]*12,detector_nickname=None),parent=parent)
        self.output_selectors={p[-1]:b for p,b in self.choices.items() if p[0]=='outputs'}
        self.phase_selectors=[self.choices[('phase_outputs',i)] for i in range(12)]
        self.detector_selector=self.choices[('detector_nickname',)]
        self.changed.connect(self.selection_changed)
    def set_hardware_definition(self,hd):
        self.hd=hd
        for box in self.choices.values():box.refresh()
    def selection(self):
        result=self.apply({})
        from labremote.devices.fpga.mapping import EDITING
        if EDITING.get():return result
        routing.validate(result,'phase_shifter')
        pins=[self.worker.profile.resolve(name) for name in [*result['outputs'].values(),*result['phase_outputs']]]
        if len(pins)!=len(set(pins)):raise ValueError('동일한 실제 출력을 여러 역할에 중복 지정할 수 없습니다.')
        return result
    def apply_to(self,parameters):
        result=dict(parameters);result.update(self.selection());return result
