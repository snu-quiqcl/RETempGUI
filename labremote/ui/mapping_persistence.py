"""Local settings ownership for all experiment mapping tables."""
from copy import deepcopy
from PyQt5 import QtCore
from labremote.configuration.paths import CONFIG_ROOT
from labremote.configuration.experiment_settings import read,save,mapping_block
from labremote.devices.fpga.mapping import scope,editing_settings,settings_path
from labremote.devices.fpga import routing
from .experiment_mapping import MappingEditor

def destination(view):
    name=type(view).__name__;ch=getattr(view,'chamber',None)
    ch=ch.currentText() if hasattr(ch,'currentText') else ch
    if name=='FluorescenceTab':rel=f'characterization/fluorescence_{ch}.json'
    elif name=='RabiTab':rel=f'characterization/rabi_{ch}.json'
    elif name=='PulseExperimentTab':rel=f'characterization/{view.kind}_{ch}.json'
    elif name=='SpamScanTab':rel=f'characterization/spam_2d_{ch}.json'
    elif name=='DecayExperimentTab':rel=f'decay/{ch}_{view.mode}.json'
    elif name=='HOMTab':rel='hom/hom.json'
    elif name=='EntanglementTab':rel='entanglement/entanglement.json'
    elif name=='IonCheckTab':rel='ion_check/ion_check.json'
    elif name in ('MicromotionPage','TwoRFCompensationPage'):rel=f"micromotion/{ch}.{('two_rf' if name=='TwoRFCompensationPage' else view.experiment_mode)}.json"
    elif name=='SecularScanPage':rel=f'micromotion/{ch}.secular.json'
    elif name in ('PhaseShifterTab','HalfPiRamseyTab','PhaseRabiTab','PhaseHoldTab'):
        filename={'PhaseShifterTab':'ramsey','HalfPiRamseyTab':'ramsey_calibrated','PhaseRabiTab':'rabi','PhaseHoldTab':'hold'}[name]
        rel=f'phase_shifter/{filename}.json'
    elif name=='MotorScanTab':rel=f'motor_scan/scan_{view.number}.json'
    else:return None
    return settings_path(CONFIG_ROOT/'operations'/rel)

def snapshot(view):
    if type(view).__name__=='MotorScanTab':
        return dict(view.scales,**{k:v.value() for k,v in view.fields.items()},pmt=view.channel.route(),scan=view.number,directory=view.directory.text(),x_motor=view.x_motor.currentText(),y_motor=view.y_motor.currentText(),z_motor=view.z_motor.currentText() if view.z_enabled.isChecked() else None)
    if type(view).__name__=='PhaseHoldTab':
        return dict(phase_angle_deg=view.angle.value(),phase_outputs=view.names(),calibration=view.calibration.active())
    return view.value()

def persist(view):
    if not getattr(view,'_mapping_ready',False):return
    with scope(view.worker.profile),editing_settings():
        path=destination(view)
        if path is None:return
        c=snapshot(view)
        if c==getattr(view,'_mapping_last_snapshot',None):return
        current=path.read_bytes() if path.exists() else None
        revisions=view.__dict__.setdefault('_mapping_revisions',{})
        if path in revisions and current!=revisions[path]:
            disk=read(path) if current is not None else None
            if isinstance(disk,dict) and disk.get('document_type')=='entanglement_settings':disk=disk['settings']
            if disk!=c:raise ValueError('실험 설정이 다른 창 또는 외부에서 변경되었습니다. 다시 불러오세요. 원본을 유지했습니다.')
        save(path,c,getattr(view,'kind',None))
        revisions[path]=path.read_bytes();view._mapping_last_snapshot=deepcopy(c)

def bind(view):
    if getattr(view,'_mapping_ready',False) or not hasattr(view,'worker'):return
    tables=view.findChildren(MappingEditor)
    if not tables:return
    with scope(view.worker.profile),editing_settings():
        path=destination(view)
        if path is None:return
        if path.exists():
            c=read(path)
            if c.get('document_type')=='entanglement_settings':c=c['settings']
            if type(view).__name__=='SpamScanTab':c=c['spam']
            for table in tables:
                if not any(spec.path[0] in c for spec in routing.routes(table.experiment,c,table.mode,all_fields=True)):continue
                normalized=routing.normalize(c,table.experiment,table.mode,view.worker.profile)
                table._settings=deepcopy(normalized)
                for route,box in table.choices.items():box.setCurrentText(routing.get(normalized,route))
    view._mapping_loaded_path=path
    view._mapping_revisions={path:path.read_bytes() if path.exists() else None}
    try:
        with scope(view.worker.profile),editing_settings():view._mapping_last_snapshot=deepcopy(snapshot(view))
    except (ValueError,TypeError,KeyError):view._mapping_last_snapshot=None
    view._mapping_ready=True
    timer=QtCore.QTimer(view);timer.setSingleShot(True);timer.setInterval(300)
    view._mapping_timer=timer
    def checkpoint():
        try:persist(view)
        except (ValueError,TypeError,OSError,KeyError) as exc:
            label=getattr(view,'status',None)
            if label is not None:label.setText('매핑 저장 확인: '+str(exc))
    timer.timeout.connect(checkpoint)
    for table in tables:table.changed.connect(lambda:timer.start())
    # App shutdown and tab changes also call persist through InputState.

def views(roots):
    """Explicit child-page identities, independent of tab indexes."""
    found={}
    def walk(view,prefix):
        if getattr(view,'_mapping_ready',False):found.setdefault(id(view),(prefix,view))
        for attr in ('experiments','ramsey','hold','rabi','halfpi_ramsey'):
            child=getattr(view,attr,None)
            if isinstance(child,dict):
                for key,page in child.items():
                    if hasattr(page,'findChildren'):walk(page,prefix+'/'+attr+'/'+str(key))
            elif hasattr(child,'findChildren'):walk(child,prefix+'/'+attr)
    for prefix,root in sorted(roots.items(),key=lambda pair:(not pair[0].startswith('experiment/'),-len(pair[0]))):
        walk(root,prefix)
    return list(found.values())

def restore_legacy(state):
    for prefix,view in views(state.roots()):
        try:_restore_view(state,prefix,view)
        except (OSError,ValueError,TypeError,KeyError) as exc:
            state.report(prefix+': 매핑 이전 보류; 원본 유지: '+str(exc))

def _restore_view(state,prefix,view):
    import json
    from labremote.configuration.legacy_inputs import experiment_prefix
    from labremote.configuration.settings_migration import backup_file
    from labremote.devices.fpga.mapping import PINS
    with scope(view.worker.profile),editing_settings():
        path=destination(view)
        # InputState restores comboboxes without signals. If it changed EA/EC,
        # restore that chamber's mapping before accepting the UI draft.
        if path!=getattr(view,'_mapping_loaded_path',None):
            view._mapping_ui_imported=False
            if path.exists():selected=read(path)
            elif hasattr(view,'saved_settings'):selected=view.saved_settings(view.chamber.currentText())
            else:selected=None
            if selected is not None:
                for table in view.findChildren(MappingEditor):table.set_settings(selected)
            view._mapping_loaded_path=path
        if getattr(view,'_mapping_ui_imported',False):return
        raw=json.loads(path.read_text(encoding='utf-8-sig')) if path.exists() else {}
        if (mapping_block(raw) or {}).get('ui_state_imported'):
            view._mapping_ui_imported=True;return
        c=snapshot(view);applied=[]
        old=experiment_prefix(view,view.worker.name)
        for table in view.findChildren(MappingEditor):
            target=c['spam'] if type(view).__name__=='SpamScanTab' else c
            for spec in routing.routes(table.experiment,target,table.mode,all_fields=True):
                path_parts=spec.path;head=path_parts[0]
                suffix='/'.join(map(str,path_parts))
                if table.experiment in ('micromotion','secular'):suffix='fields/'+suffix
                elif type(view).__name__=='MotorScanTab':suffix='channel'
                elif head=='mapping':suffix='mapping_fields/'+str(path_parts[-1])
                elif table.experiment=='phase_shifter':
                    if head=='outputs':suffix='mapping/output_selectors/'+str(path_parts[-1])
                    elif head=='phase_outputs':suffix=('selectors/' if type(view).__name__=='PhaseHoldTab' else 'mapping/phase_selectors/')+str(path_parts[-1])
                    else:suffix='mapping/detector_selector'
                elif head=='fpga_mapping':continue
                candidates=[prefix+'/'+suffix]+([old+'/'+suffix] if old else [])
                key=next((k for k in candidates if k in state.saved),None)
                if key is None:continue
                saved=state.saved[key];value=saved.get('value');identity=saved.get('identity')
                token=value if isinstance(value,str) and value.startswith('signal:') else identity if isinstance(identity,str) else value
                if token in PINS:token='signal:'+view.worker.profile.document()['pins'][token]
                if token in ('','사용 안 함') or token is None:token=None
                try:token=routing.direct(token,table.experiment,view.worker.profile)
                except ValueError:pass
                routing.put(target,spec.path,token);applied.append(key)
            table.set_settings(target)
            if hasattr(view,'roles') and table.experiment in ('rabi','ramsey','spin_echo','spam','initialization','fluorescence'):
                view.roles={p[-1]:box for p,box in table.choices.items() if p[0]=='roles'}
            if type(view).__name__=='MotorScanTab':view.channel=table.choices[('pmt',)]
            if table.experiment=='phase_shifter':
                if hasattr(table,'output_selectors'):
                    table.output_selectors={p[-1]:b for p,b in table.choices.items() if p[0]=='outputs'}
                    table.phase_selectors=[table.choices[('phase_outputs',i)] for i in range(12)]
                    table.detector_selector=table.choices[('detector_nickname',)]
                if type(view).__name__=='PhaseHoldTab':view.selectors=[table.choices[('phase_outputs',i)] for i in range(12)]
        # Back up the source UI documents before retiring their mapping keys.
        if state.store is not None:
            sources={state.store.locations.get(('inputs',key)) for key in applied}
            for source in sources:
                if source is not None:backup_file(source)
        elif applied and state.path.exists():backup_file(state.path)
        save(path,c,getattr(view,'kind',None))
        view.__dict__.setdefault('_mapping_revisions',{})[path]=path.read_bytes()
        view._mapping_last_snapshot=deepcopy(c)
        for key in applied:
            state.saved.pop(key,None)
            if state.store is not None:
                source=state.store.locations.pop(('inputs',key),None)
                if source is not None:state.store.documents[source]['inputs'].pop(key,None)
        view._mapping_ui_imported=True
