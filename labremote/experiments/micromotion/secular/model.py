"""First-event protocol/fit ported from Task/parameteric_heating/secular_frequency_scan.py.
Acquisition and likelihood geometry are kept together; no hardware imports.
"""
import math
import numpy as np
from scipy.optimize import least_squares

CORRELATION_LABEL=0x5343
COUNT_LABEL=0x534E

def _geometry(frequency_khz, bins):
    period_ticks = 800000. / float(frequency_khz)
    stop_tick = int(math.ceil(period_ticks-1e-10))
    if int(bins) > stop_tick-1:
        raise ValueError("Phase bins exceeds the usable stopwatch ticks per period.")
    edges = np.arange(int(bins)+1, dtype=np.int64)*stop_tick//int(bins)
    phase_edges = np.minimum(edges/period_ticks*2*np.pi, 2*np.pi)
    # dt=0 is rejected by the legacy strict Sync-before-PMT condition.
    exposure = np.diff(edges).astype(float)
    exposure[0] -= 1
    if np.any(exposure <= 0):
        raise ValueError("Phase bin has no accepted stopwatch ticks; reduce Phase bins.")
    cosines, sines = [], []
    for a,b in zip(edges[:-1],edges[1:]):
        phases = np.arange(max(1,int(a)),int(b))*2*np.pi/period_ticks
        cosines.append(np.cos(phases).sum())
        sines.append(np.sin(phases).sum())
    norm = exposure.mean()
    design = np.column_stack((exposure,cosines,sines))/norm
    return stop_tick, edges, phase_edges, design


def background_m(rate_cps,frequency_khz):
    return 2*float(rate_cps)/math.hypot(float(rate_cps),2*math.pi*float(frequency_khz)*1000)


def rate_limit_cps(max_m,frequency_khz):
    return 2*math.pi*float(frequency_khz)*1000*float(max_m)/math.sqrt(4-float(max_m)**2)


def _decode_correlation(records,bins,attempt_limit,event_limit):
    a=np.asarray(records)
    padded=((bins+2)//3)*3
    if a.shape!=(padded//3+1,4) or not np.issubdtype(a.dtype,np.integer):
        raise ValueError("Malformed correlation FIFO shape/type.")
    if np.any((a<0)|(a>65535)) or np.any(a[:,3]!=CORRELATION_LABEL):
        raise ValueError("Invalid correlation FIFO word or label.")
    h=a[:-1,:3].reshape(-1)
    attempts,events,width=map(int,a[-1,:3])
    if width!=bins or np.any(h[bins:]!=0) or int(h[:bins].sum())!=events:
        raise ValueError("Correlation FIFO histogram/summary mismatch.")
    if not 1<=attempts<=attempt_limit or not 0<=events<=min(attempts,event_limit):
        raise ValueError("Correlation FIFO counters exceed block bounds.")
    if attempts!=attempt_limit and events!=event_limit:
        raise ValueError("Correlation block ended before either termination condition.")
    return h[:bins].astype(np.int64),attempts,events


def _decode_count(records,exposure_us):
    segments=[100]*(exposure_us//100)+([exposure_us%100] if exposure_us%100 else [])
    a=np.asarray(records)
    if a.shape!=(len(segments),4) or not np.issubdtype(a.dtype,np.integer):
        raise ValueError("Malformed count FIFO shape/type.")
    if np.any((a<0)|(a>65535)) or np.any(a[:,3]!=COUNT_LABEL):
        raise ValueError("Invalid count FIFO word or label.")
    if not np.array_equal(a[:,1],np.asarray(segments)*100) or not np.array_equal(a[:,2],np.arange(len(segments))):
        raise ValueError("Count FIFO exposure/segment index mismatch.")
    # 100-MHz counter sampling bounds count by live clocks; segments stay <65536 clocks.
    if np.any(a[:,0]>a[:,1]):
        raise ValueError("Count exceeds physical counter-clock bound.")
    return a[:,:3].astype(np.int64)


def _first_event_probabilities(frequency_khz, bins, rate, ab):
    """Conditional bin probabilities for accepted timestamp differences.

    Tick-cell approximation: difference k represents [k, k+1) / 800 MHz.
    The first timestamp difference zero is rejected; k < ceil(T/tick).
    PMT and Sync are armed together. For a Poisson stream, conditioning on
    no PMT before the first Sync multiplies all later times by the same
    survival factor, which cancels in this accepted-event distribution.
    Timestamp quantisation, PMT dead time and non-Poisson correlations can
    still limit the model on hardware; these are not corrected here.
    """
    end, edges, _, _ = _geometry(frequency_khz, bins)
    bounds = np.maximum(edges, 1).astype(float) / 800e6
    omega = 2*np.pi*float(frequency_khz)*1000
    a,b = ab
    # Cumulative hazard relative to the beginning of the accepted interval.
    phase = omega*bounds
    hazard = rate*((bounds-bounds[0]) + a*(np.sin(phase)-np.sin(phase[0]))/omega
                  + b*(np.cos(phase[0])-np.cos(phase))/omega)
    increments = np.diff(hazard)
    mass = np.exp(-hazard[:-1]) * (-np.expm1(-increments))
    return mass/mass.sum()


def _fit_first_event(histogram, frequency_khz, rate, rate_sem=np.nan):
    """Conditional multinomial fit of a,b, fixing R to the measured rate.

    Error propagation includes a,b covariance and independent rate SEM via
    local implicit differentiation. Missing SEM gives conditional errors only.
    Compatibility coefficients are C=N/bins, C*a, C*b; they describe the
    reconstructed rate, NOT the first-event count distribution.
    """
    y=np.asarray(histogram,float); n=y.sum(); bins=len(y)
    invalid=dict(coefficients=np.full(3,np.nan),covariance=np.full((3,3),np.nan),
        values=np.full(5,np.nan),errors=np.full(5,np.nan),prediction=np.full(y.shape,np.nan),
        valid=False,phase_valid=False,deviance=np.nan,rate_error_included=False)
    if n<max(20,bins) or not np.isfinite(rate) or rate<=0:
        return invalid
    _, edges, _, _ = _geometry(frequency_khz,bins)
    bounds=np.maximum(edges,1)/800e6
    omega=2*np.pi*frequency_khz*1000
    widths=np.diff(bounds)
    # Hazard inversion seed; exact bin-averaged cosine/sine basis.
    event_mass=-np.expm1(-rate*(bounds[-1]-bounds[0]))
    survival=1-event_mass*np.r_[0,np.cumsum(y)/n]
    recovered=-np.diff(np.log(np.maximum(survival,1e-15)))/widths
    basis=np.column_stack((np.diff(np.sin(omega*bounds))/(omega*widths),
                           -np.diff(np.cos(omega*bounds))/(omega*widths)))
    initial=np.linalg.lstsq(basis,recovered/rate-1,rcond=None)[0]
    length=np.linalg.norm(initial)
    if length>.8: initial*=.8/length
    # Smooth mapping enforces a^2+b^2<1 throughout optimisation.
    def unpack(q): return q/np.sqrt(1+q@q)
    def residual(q):
        mu=n*_first_event_probabilities(frequency_khz,bins,rate,unpack(q))
        mu=np.maximum(mu,1e-300)
        term=mu-y
        mask=y>0
        term[mask]+=y[mask]*np.log(y[mask]/mu[mask])
        return np.sign(mu-y)*np.sqrt(np.maximum(0,2*term))
    try:
        candidates=[least_squares(residual,seed,max_nfev=300,
                    ftol=1e-10,xtol=1e-10,gtol=1e-10) for seed in
                    (initial/np.sqrt(1-initial@initial),np.zeros(2))]
        candidates=[r for r in candidates if r.success and np.all(np.isfinite(r.x))]
        if not candidates: return invalid
        result=min(candidates,key=lambda r: np.sum(r.fun**2))
        ab=unpack(result.x); M=float(np.linalg.norm(ab))
        if M>=.999: return invalid
        prob=_first_event_probabilities(frequency_khz,bins,rate,ab)
        eps=1e-5
        dp=np.column_stack([(_first_event_probabilities(frequency_khz,bins,rate,ab+eps*np.eye(2)[j])
                            -_first_event_probabilities(frequency_khz,bins,rate,ab-eps*np.eye(2)[j]))/(2*eps)
                            for j in range(2)])
        covab=np.linalg.inv(n*dp.T@(dp/prob[:,None]))
        included=bool(np.isfinite(rate_sem) and rate_sem>=0)
        if included:
            dr=max(rate*1e-4,1e-6)
            pr=(_first_event_probabilities(frequency_khz,bins,rate+dr,ab)
                -_first_event_probabilities(frequency_khz,bins,rate-dr,ab))/(2*dr)
            sensitivity=-covab@(n*dp.T@(pr/prob))
            covab+=np.outer(sensitivity,sensitivity)*rate_sem**2
        a,b=ab; C=n/bins
        # C is a fixed display normalization for this conditional fit.
        transform=np.array([[0.,0.],[C,0.],[0.,C]])
        covariance=transform@covab@transform.T
        errors=np.full(5,np.nan)
        errors[1:3]=np.sqrt(np.maximum(0,np.diag(covab)))
        theta=np.nan; phase_valid=False
        if M>1e-12:
            grad=ab/M; grad_phase=np.array([-b,a])/M**2
            errors[3]=np.sqrt(max(0,float(grad@covab@grad)))
            errors[0]=C*errors[3]
            phase_valid=bool(M>2*errors[3])
            if phase_valid:
                theta=math.atan2(b,a)
                errors[4]=np.sqrt(max(0,float(grad_phase@covab@grad_phase)))
        return dict(coefficients=C*np.r_[1.,ab],covariance=covariance,
            values=np.array([C*M,a,b,M,theta]),errors=errors,prediction=n*prob,
            valid=True,phase_valid=phase_valid,deviance=float(result.fun@result.fun),
            rate_error_included=included)
    except (ValueError,OverflowError,FloatingPointError,np.linalg.LinAlgError):
        return invalid
