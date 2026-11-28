"""FIFO v3 readout and CCD-preserving cleanup for RE without flip mirror."""
from types import SimpleNamespace
from labremote.devices.fpga.mapping import CURRENT, scope
from labremote.devices.fpga.routing import settings_profile
from labremote.experiments.entanglement.acquisition import run as acquire, _cleanup
from .config import CLEANUP_LEVELS, nominal_trials
from .sequence import build_program

def cleanup(controller,c):
    state=CURRENT.get()
    if state is None:return _cleanup(controller,c,CLEANUP_LEVELS)
    with scope(settings_profile(state[0],'entanglement_no_mirror',c),'entanglement_no_mirror'):
        return _cleanup(controller,c,CLEANUP_LEVELS)

def decode(rows, c):
    if len(rows) != 164 or any(not isinstance(r,(list,tuple)) or len(r)!=4 or
            any(type(v) is not int or not 0<=v<=65535 for v in r) for r in rows):
        raise ValueError('Incomplete or malformed entanglement FIFO')
    if [r[3] for r in rows] != [100]*163+[101]:
        raise ValueError('Unexpected entanglement FIFO tags')
    if list(rows[-1][1:3]) != [3,0] or rows[-1][0] not in (0,1):
        raise ValueError('Unknown entanglement FIFO version')
    if rows[-1][0]:
        raise OverflowError('16-bit histogram saturated; reduce attempts per batch')
    flat = [v for row in rows[:163] for v in row[:3]]
    a, b, coin = flat[:120], flat[120:240], flat[240:480]
    ea1,ea2,ec1,ec2,group,loop,herald,inner,reserved = flat[480:]
    if reserved:raise ValueError("Invalid readout reserved word")
    ea,ec=ea1+ea2,ec1+ec2
    if herald not in (0,1):
        raise ValueError('Invalid herald flag')
    if herald:
        if not (group<c['groups_per_loop'] and loop<c['fpga_loops'] and inner<c['inner_trials']):
            raise ValueError('Invalid attempt indices')
        attempts=(loop*c['groups_per_loop']+group)*c['inner_trials']+inner+1
    else:
        if [ea,ec,group,loop,inner] != [0,0,0,c['fpga_loops'],0]:
            raise ValueError('Invalid exhausted-batch counters')
        attempts=nominal_trials(c)
    accepted=sum(coin[120-c['coincidence_half_window_bins']:120+c['coincidence_half_window_bins']])
    if accepted != herald or sum(a)>attempts or sum(b)>attempts or sum(coin)>min(sum(a),sum(b)):
        raise ValueError('Inconsistent histogram / herald counts')
    return dict(a=a,c=b,coincidence=coin,attempts=attempts,heralded=bool(herald),
        outcome='heralded' if herald else 'max_attempts_reached',
        state_counts=dict(ea=ea,ec=ec) if herald else None,
        state_counts_by_pmt=dict(ea=dict(PMT1=ea1,PMT2=ea2),ec=dict(PMT1=ec1,PMT2=ec2)) if herald else None,
        readout_order=['ea','ec'],state_count_rule='PMT1 + PMT2',
        state_label=(str(int(ea>c['threshold_ea']))+str(int(ec>c['threshold_ec']))) if herald else None,
        indices=dict(group=group,fpga_loop=loop,inner_trial=inner),state_words=flat[480:])


def run(controller,c,cancelled,on_rows,on_batch,on_cleanup=lambda status:None,on_event=lambda event:None):
    backend=SimpleNamespace(expected_rows=164,build_program=build_program,cleanup=cleanup,decode=decode)
    return acquire(controller,c,cancelled,on_rows,on_batch,on_cleanup,on_event,backend=backend)
