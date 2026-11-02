from labremote.runtime.io import Context

def read_spectrum(p):
    ctx=Context()
    ctx.assign(p.sweep_mode,'SINGLE')
    ctx.assign(p.clear_status,True)
    ctx.assign(p.sweep_start,True)
    ctx.assign(p.data_format,'ASCII')
    value=dict(ctx.acquire(p.spectrum))
    # Runs in the acquisition worker, never in a Qt paint/progress callback.
    # Both the OSA display and PID consume this same result.
    from labremote.runtime.pid_runner import estimate_peak, InvalidSpectrum
    try:
        value['_peak_analysis']=estimate_peak(value,False,0.,include_curve=True,diagnostic_fit=True)
    except InvalidSpectrum as exc:
        value['_peak_analysis_error']=str(exc)
    return value
