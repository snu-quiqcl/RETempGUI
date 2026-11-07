"""Declarative setup rows; dispatch through the existing device APIs, never raw I/O."""
from copy import deepcopy
import math
from dataclasses import dataclass,replace
from labremote.runtime.parameters import ParameterRegistry
from labremote.config.paths import registry_paths


@dataclass(frozen=True)
class Setting:
    path: str
    spec: object
    method: str
    channel: object = None
    prefix: tuple = ()


def catalogue(family):
    policy=ParameterRegistry(registry_paths());result={}
    def add(path,method,channel=None,prefix=(),choices=None):
        spec=policy.get(family,path)
        if not spec.writable:return
        if choices is not None:spec=replace(spec,choices=choices)
        result[path]=Setting(path,spec,method,channel,prefix)
    if family=='fpga':
        from labremote.devices.fpga.controller import OUTPUTS
        for name in OUTPUTS:add('outputs.'+name,'set_output',prefix=(name,))
    elif family=='flip':add('position','move',choices=(1,2))
    elif family=='windfreak':
        for ch in ('A','B'):
            for path,method in [('frequency_hz','set_frequency'),('power_dbm','set_power'),('phase_deg','set_phase'),('output_enabled','set_output')]:add('channel_'+ch+'.'+path,method,ch)
    elif family=='sg384':
        add('frequency','set_frequency');add('phase','set_phase')
        for port in ('BNC','N'):
            add(port.lower()+'_power_dbm','set_power',port);add(port.lower()+'_output','on_off',port)
    elif family=='anapico':
        add('frequency','set_frequency');add('phase','set_phase');add('output','on_off')
    elif family=='dds4':
        for ch in range(1,5):
            for path,method in [('frequency_hz','set_frequency'),('phase_deg','set_phase'),('vva_level','set_vva'),('output_enabled','on_off')]:add(f'ch{ch}.'+path,method,ch)
    elif family=='thermotek':add('temperature_setpoint','set_target')
    elif family=='mdt':
        for axis in ('x','y','z'):add(axis+'.voltage','set_voltage',prefix=(axis,))
        add('master_scan_enabled','set_master_scan')
    elif family=='keithley':
        for ch in range(1,4):
            for path,method in [('target_voltage','set_voltage'),('target_current','set_current'),('voltage_limit','set_voltage_limit'),('voltage_limit_state','set_voltage_limit_enabled'),('output','on_off')]:add(f'ch{ch}.'+path,method,ch)
    return result


def validate(parameters,allow_empty=False):
    p=deepcopy(parameters)
    if not isinstance(p,dict) or set(p)!={'schema_version','steps','settle_s'} or p['schema_version']!=1 or type(p['schema_version']) is not int:raise ValueError('Invalid setup settings schema')
    rows=p['steps']
    if not isinstance(rows,list) or len(rows)>1000 or (not rows and not allow_empty):raise ValueError('설정 항목을 1개 이상 추가하세요 (최대 1000개).')
    if type(p['settle_s']) not in (int,float) or not math.isfinite(p['settle_s']) or not 0<=p['settle_s']<=3600:raise ValueError('전체 설정 후 대기는 0..3600 s입니다.')
    catalogs={}
    for index,row in enumerate(rows,1):
        try:
            if not isinstance(row,dict) or set(row)!={'family','device','parameter','value'}:raise ValueError('Invalid setup row')
            if any(not isinstance(row[k],str) or not row[k].strip() for k in ('family','device','parameter')):raise ValueError('장비와 파라미터를 선택하세요.')
            if row['family'] not in catalogs:catalogs[row['family']]=catalogue(row['family'])
            setting=catalogs[row['family']].get(row['parameter'])
            if setting is None:raise ValueError('지원하지 않는 설정: '+row['family']+'.'+row['parameter'])
            setting.spec.validate(row['value'],request=True)
        except Exception as exc:raise ValueError(f'설정 {index}: {exc}') from exc
    return p


def migrate_legacy(name,parameters):
    """Explicit one-time conversion of the former setup wrappers, not defaults for setup."""
    p=parameters;fpga=p.get('fpga','fpga_local')
    def row(family,device,parameter,value):return dict(family=family,device=device,parameter=parameter,value=value)
    if name=='re_setup.py':
        names=dict(EC_MIRA='EC_MIRA',EA_MIRA='EA_MIRA',ec_pmt='EC_PMT',ea_pmt='EA_PMT');names.update(p.get('flippers',{}))
        rows=[row('fpga',fpga,'outputs.CCD_EC',False),row('fpga',fpga,'outputs.CCD_EA',True)]
        rows += [row('flip',names[k],'position',v) for k,v in [('EC_MIRA',1),('EA_MIRA',1),('ec_pmt',1),('ea_pmt',2)]]
    elif name=='spam_setup.py':rows=[row('fpga',fpga,'outputs.CCD_EA',False),row('fpga',fpga,'outputs.CCD_EC',True)]
    else:raise ValueError('Not a legacy setup workflow')
    if set(p)-{'fpga','flippers','settle_s'}:raise ValueError('기존 Setup에 사용자 변수가 있습니다. 새 setup.py 항목에서 설정을 확인해 주세요.')
    return validate(dict(schema_version=1,steps=rows,settle_s=p.get('settle_s',1.)))


def execute(devices):
    from labremote.api.devices import device_api
    from labremote.runtime.workflow_result import WorkflowResult
    from labremote.runtime.errors import OperationCancelled
    p=validate(devices.parameters);prepared=[];completed=[];current=None
    # Resolve only listed devices before writing. This is not a global busy check.
    for row in p['steps']:
        worker=devices._resolve_worker(row['family'],row['device'])
        if worker.ps is None or worker.connection_error or worker._closing:raise ConnectionError('Setup device disconnected: '+row['device'])
        setting=catalogue(row['family'])[row['parameter']]
        prepared.append((row,setting,worker))
    try:
        for index,(row,setting,worker) in enumerate(prepared,1):
            current=dict(index=index,**row);devices.wait(0)
            api=device_api(worker,channel=setting.channel,group=devices.group)
            if setting.method=='on_off':handle=(api.on if row['value'] else api.off)()
            else:handle=getattr(api,setting.method)(*setting.prefix,row['value'])
            handle.wait();completed.append(dict(current,status='completed'))
        current=None;devices.wait(p['settle_s'])
    except OperationCancelled:raise
    except Exception as exc:
        label=f"{current['index']}: {current['device']} / {current['parameter']}" if current else 'settle'
        return WorkflowResult(status='failed',reason=f'Setup {label}: {exc}',continue_allowed=False,cleanup_status='not_required',value={'completed':completed,'failed':current,'error':str(exc)})
    return WorkflowResult(reason=f'{len(completed)} setup settings completed',cleanup_status='not_required',value={'completed':completed,'settle_s':p['settle_s']})
