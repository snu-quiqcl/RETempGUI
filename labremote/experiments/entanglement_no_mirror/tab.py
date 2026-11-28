from pathlib import Path
from labremote.devices.fpga.mapping import bound_methods
from labremote.experiments.entanglement.tab import EntanglementTab
from . import config

@bound_methods('entanglement_no_mirror',editor=True)
class EntanglementNoMirrorTab(EntanglementTab):
    config_module=config
    experiment='entanglement_no_mirror'
    mapping_experiment='entanglement_no_mirror'
    title='RE without flip mirror'
    workflow_path=Path(__file__).with_name('workflow.py')
    settings_tags={'experiment':'entanglement_no_mirror'}
    mapping_note='EA → EC 순차 측정 · 동일한 PMT 1·2 사용\n각 챔버 PMT1 + PMT2 > 임계값이면 bright.\nEA/EC detection time·임계값 개별 설정.\nCCD 출력은 시작·측정·중단·종료 모두 변경하지 않습니다.\nAOMB/AOMM은 측정 중 OFF, 종료 후 기존 cooling 복구.'

    def __init__(self,worker,parent=None):
        super().__init__(worker,parent)
