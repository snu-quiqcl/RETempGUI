"""Frozen, portable Queue entries for built-in experiment views."""
from copy import deepcopy
import hashlib
from uuid import uuid4


def source_job(source,filename,name,parameters,profile):
    from .workflow_loader import validate_workflow
    validate_workflow(source,filename)
    job=dict(id=uuid4().hex,name=name,filename=filename,source=source,
                sha256=hashlib.sha256(source.encode()).hexdigest(),repeat=1,on_failure='stop',
                parameters=deepcopy(parameters))
    if profile is not None:job.update(fpga_id=profile.device_id,fpga_profiles={profile.device_id:profile.document()})
    return job


def make_job(view,worker,title):
    from labremote.ui.workflow_tab import WorkflowTab
    if isinstance(view,WorkflowTab):
        return source_job(view.source.toPlainText(),view.filename or 'workflow.py',title,{},worker.profile)
    # Composite pages share one FPGA selection but freeze the active sub-page.
    if type(view).__name__ in ('MicromotionTab','EtcTab'):view=view.currentWidget()
    kind=type(view).__name__
    parameters=dict(fpga=worker.name,kind=kind)
    if kind=='MotorScanTab':
        x,y,c,z=view.request()
        parameters.update(settings=c,x=x.worker.name,y=y.worker.name,z=z.worker.name if z else None)
    elif kind=='PhaseHoldTab':
        parameters.update(settings=dict(phase_angle_deg=view.angle.value(),phase_outputs=view.names(),calibration=view.calibration.active()))
    else:
        parameters['settings']=view.value()
        for key in ('chamber','mode','kind'):
            value=getattr(view,key,None)
            if isinstance(value,str):parameters['experiment_'+key]=value
        if kind=='MicromotionPage':
            parameters['mode']=view.experiment_mode
            dac=view._dac_workers.get(view.dac.currentData())
            parameters['dac']=dac.name if dac else None
    source="def main(devices):\n    from labremote.runtime.experiment_jobs import execute\n    return execute(devices)\n"
    return source_job(source,'builtin_experiment.py',title+' · '+worker.profile.alias,parameters,worker.profile)


def execute(devices):
    p=devices.parameters;api=devices.fpga(p['fpga']);kind=p['kind'];c=p['settings']
    directory=devices.run_directory
    if kind=='MotorScanTab':
        c=dict(c,directory=directory)
        return api.start_scan(devices.motor(p['x']),devices.motor(p['y']),c,z_motor=devices.motor(p['z']) if p.get('z') else None).wait()
    if kind=='MicromotionPage':
        return api.run_micromotion(settings=c,mode=p['mode'],dac=devices.dac(p['dac']) if p.get('dac') else None,directory=directory).wait()
    if kind=='PhaseShifterTab':return api.run_phase_shifter(settings=c,directory=directory).wait()
    if kind=='PhaseRabiTab':return api.run_phase_rabi(settings=c,directory=directory).wait()
    if kind=='PhaseHoldTab':return api.hold_phase(**c).wait()
    method={'HOMTab':'run_hom','EntanglementTab':'run_entanglement','IonCheckTab':'run_ion_check',
            'FluorescenceTab':'run_fluorescence','RabiTab':'run_rabi','DecayExperimentTab':'run_decay',
            'PulseExperimentTab':'run_'+p.get('experiment_kind','ramsey')}[kind]
    args=[]
    if kind in ('FluorescenceTab','RabiTab','PulseExperimentTab','DecayExperimentTab'):args.append(p['experiment_chamber'])
    if kind=='DecayExperimentTab':args.append(p['experiment_mode'])
    return getattr(api,method)(*args,settings=c,directory=directory).wait()
