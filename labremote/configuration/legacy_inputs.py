"""Read old per-device experiment keys without changing their files or units."""
def experiment_prefix(view,device):
    base='device/fpga/'+device+'/'
    name=type(view).__name__
    if name=='FluorescenceTab':return base+'daily_tab/experiments/'+view.chamber
    if name=='RabiTab':return base+'daily_tab/rabi_experiments/'+view.chamber
    if name=='PulseExperimentTab':return base+'daily_tab/pulse_experiments/'+str((view.kind,view.chamber))
    if name=='DecayExperimentTab':return base+'decay_tab/experiments/'+str((view.chamber,view.mode))
    if name=='MotorScanTab':return base+'scan_tabs/'+str(view.number-1)
    attr={'HOMTab':'hom_tab','EntanglementTab':'entanglement_tab','IonCheckTab':'ion_check_tab','MicromotionTab':'micromotion_tab'}.get(name)
    return base+attr if attr else None
