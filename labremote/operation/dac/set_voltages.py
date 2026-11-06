"""Map client electrode targets to a single physical-channel driver request."""

def set_voltages(worker,state,use_ldac,timing,reuse=False):
    updates=[[e.chip,e.channel,state.by_id[e.id]] for e in worker.config.electrodes]
    status=worker.raw_device.set_voltages(updates,worker.configuration_id,
        use_ldac=use_ldac,command_gap_ms=timing.command_gap_ms,
        pre_ldac_ms=timing.pre_ldac_ms,cooldown_ms=timing.cooldown_ms,
        reuse_spi_config=reuse)
    worker._description(status)
    return status
