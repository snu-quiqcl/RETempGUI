"""Normalize a SPAM Workflow's single parameter set; preserve legacy imports."""
from copy import deepcopy
from contextlib import nullcontext
from labremote.devices.fpga.mapping import CURRENT,scope
from labremote.configuration.experiment_settings import unpack
from labremote.experiments.characterization.shared import pulse_model as model
from labremote.experiments.characterization.rabi.model import validate_frequency


def paired(parameters):
    settings=parameters.get('settings') if isinstance(parameters,dict) else None
    return isinstance(settings,dict) and set(settings)=={'EA','EC'}


def parameters(value, *, legacy_chamber=None):
    if not isinstance(value,dict):raise ValueError('Parameters must be an object')
    result=deepcopy(value)
    name=result.get('fpga','fpga_local')
    if not isinstance(name,str) or not name.strip():raise ValueError('FPGA 장비 이름을 입력하세요.')
    settings=result.get('settings')
    selected=legacy_chamber or result.get('chamber')
    if paired(result):
        if selected not in ('EA','EC'):
            raise ValueError('기존 Queue의 EA 또는 EC 설정 하나를 가져오세요.')
        settings=settings[selected]
        if settings.get('chamber')!=selected:raise ValueError('SPAM chamber/settings mismatch')
    if not isinstance(settings,dict):raise ValueError('SPAM 설정 한 세트가 필요합니다.')
    settings=unpack(settings)
    selected=selected or settings.get('chamber')
    # Old chamber identity is import metadata, never an execution selector.
    settings.pop('chamber',None)
    state=CURRENT.get()
    with scope(state[0],'spam') if state is not None else nullcontext():
        result['settings']=model.validate('spam',settings)
    result.pop('chamber',None)
    frequency=result.get('frequency_hz')
    if isinstance(frequency,dict):
        if selected not in ('EA','EC'):
            raise ValueError('frequency_hz는 이번 측정의 숫자 한 개로 입력하세요.')
        frequency=frequency.get(selected)
        result['frequency_hz']=frequency
    validate_frequency(frequency)
    return result
