"""Physical partial/full writes; server guards configuration and sequence ownership."""
def set_voltages(worker,state,use_ldac,timing,reuse=False,electrode_ids=None,expected_revision=None):
    selected=set(electrode_ids) if electrode_ids is not None else None
    updates=[[e.chip,e.channel,state.by_id[e.id]] for e in worker.config.electrodes
             if selected is None or e.id in selected]
    if not updates:return worker.description
    kwargs={}
    if (worker.description or {}).get('shared_control_version',0)>=1:
        kwargs=dict(control_token=worker.control_token,expected_revision=expected_revision)
    elif selected is not None or worker.control_token:
        raise ValueError('Update DAC server driver for shared partial-channel control')
    status=worker.raw_device.set_voltages(updates,worker.configuration_id,
        use_ldac=use_ldac,command_gap_ms=timing.command_gap_ms,
        pre_ldac_ms=timing.pre_ldac_ms,cooldown_ms=timing.cooldown_ms,
        reuse_spi_config=reuse,**kwargs)
    worker._description(status)
    return status
