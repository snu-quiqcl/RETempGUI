"""Quadrature covariance propagation and an uncertainty-weighted rank-one valley fit.

Fits q = q0 + u*(n dot (voltage-center)); never fits wrapped phase or selects
the lowest noisy cell. Confidence bands are local linearized 95% intervals.
"""
import numpy as np
from scipy.optimize import least_squares
from .config import fit_indices


def phase_statistics(fit):
    """TRG-relative phase and local 1-SE error (radians), also for v1 archives."""
    q=np.asarray(fit['q'],dtype=float);cov=np.asarray(fit['covariance'],dtype=float)
    if q.shape!=(2,) or cov.shape!=(2,2) or not np.isfinite(q).all() or not np.isfinite(cov).all():
        raise ValueError('Invalid quadrature covariance for phase')
    norm2=float(q@q)
    phi=float((np.arctan2(-q[1],q[0])+np.pi)%(2*np.pi)-np.pi)
    if norm2<=1e-24:return dict(phase=phi,phase_se=None,phase_reliable=False)
    gradient=np.array([q[1],-q[0]])/norm2
    phase_se=float(np.sqrt(max(0.,float(gradient@cov@gradient))))
    radial_se=float(np.sqrt(max(0.,q@cov@q/norm2)))
    reliable=bool(np.sqrt(norm2)>3*radial_se and phase_se<np.pi/3)
    return dict(phase=phi,phase_se=phase_se,phase_reliable=reliable)


def fit_histogram(histogram, c):
    h = np.asarray(histogram, dtype=float)
    idx = fit_indices(c)
    if len(h) <= idx[-1] or np.any(h < 0) or not np.isfinite(h).all() or h[idx].sum() < 10:
        raise ValueError('Insufficient/invalid photon histogram')
    phase = 2*np.pi*c['rf_mhz']*idx*1.25/1000
    X = np.column_stack((np.cos(phase), np.sin(phase), np.ones(len(idx))))
    # Iteratively reweighted Poisson approximation; preserve all bins in archive.
    variance = np.maximum(h[idx], 1.)
    for _ in range(8):
        normal = X.T @ (X/variance[:, None])
        cov = np.linalg.inv(normal)
        beta = cov @ (X.T @ (h[idx]/variance))
        variance = np.maximum(X @ beta, 1.)
    A, B, C = beta
    if C <= 0 or np.any(X @ beta <= 0):
        raise ValueError('Nonphysical harmonic fit; inspect histogram/count rate')
    q = beta[:2]/C
    jac = np.array([[1/C, 0, -A/C**2], [0, 1/C, -B/C**2]])
    qc = jac @ cov @ jac.T
    visibility = float(np.linalg.norm(q))
    error = float(np.sqrt(q @ qc @ q)/visibility) if visibility > 1e-12 else float(np.sqrt(np.trace(qc)))
    result=dict(coefficients=beta.tolist(), q=q.tolist(), covariance=qc.tolist(),
                visibility=visibility, visibility_se=error, phase=float(np.arctan2(-B,A)),
                reduced_chi2=float(np.sum((h[idx]-X@beta)**2/variance)/max(1,len(idx)-3)),
                fit_bins=idx.tolist(), phase_reliable=visibility > 3*error)
    result.update(phase_statistics(result))
    return result


def fit_valley(points):
    if len(points) < 9:
        return dict(valid=False, reason='Need at least 9 fitted points spanning both axes')
    xy = np.array([[p['left'], p['right']] for p in points])
    q = np.array([p['fit']['q'] for p in points])
    center = xy.mean(axis=0)
    z = (xy-center)*1000  # mV: stable numeric conditioning
    if np.linalg.matrix_rank(np.column_stack((np.ones(len(z)), z))) < 3:
        return dict(valid=False, reason='Need data spanning both voltage axes')
    if min(len(np.unique(xy[:, k])) for k in (0, 1)) < 3:
        return dict(valid=False, reason='Need at least three measured values per axis')
    covs = np.array([p['fit']['covariance'] for p in points])
    W = np.array([np.linalg.inv(np.linalg.cholesky(c+np.eye(2)*1e-14)) for c in covs])
    affine = np.linalg.lstsq(np.column_stack((np.ones(len(z)), z)), q, rcond=None)[0]
    left, singular, right = np.linalg.svd(affine[1:].T)
    n = right[0]
    initial = np.r_[affine[0], left[:,0]*singular[0], np.arctan2(n[1], n[0])]

    def predicted(p, coordinates=z):
        normal = np.array([np.cos(p[4]), np.sin(p[4])])
        return p[:2]+np.outer(coordinates@normal, p[2:4])

    def residual(p):
        return np.einsum('nij,nj->ni', W, predicted(p)-q).ravel()

    result = least_squares(residual, initial, max_nfev=400, x_scale='jac')
    p = result.x
    u = p[2:4]
    norm = float(np.linalg.norm(u))
    if not result.success or norm < 1e-8 or np.linalg.matrix_rank(result.jac) < 5:
        return dict(valid=False, reason='Valley direction is not identifiable')
    chi2 = float(np.sum(result.fun**2)/max(1,2*len(points)-5))
    pc = np.linalg.pinv(result.jac.T @ result.jac)*max(1., chi2)

    def geometry(params):
        un = params[2:4]
        return np.array([np.cos(params[4]), np.sin(params[4])]), -float(params[:2]@un/(un@un))

    normal, offset = geometry(p)
    # Keep a reproducible sign for line display and direction coordinates.
    if normal[1] < 0:
        normal = -normal
        offset = -offset
    floor = float(np.linalg.norm(p[:2]-u*(p[:2]@u)/(u@u)))
    distance = z@normal-offset
    base = center+normal*offset/1000
    tangent = np.array([-normal[1],normal[0]])
    limits = np.array([xy.min(axis=0),xy.max(axis=0)])
    intersections = []
    for axis in (0,1):
        if abs(tangent[axis]) < 1e-10:
            continue
        for bound in limits[:,axis]:
            pt = base+tangent*((bound-base[axis])/tangent[axis])
            if np.all(pt >= limits[0]-1e-10) and np.all(pt <= limits[1]+1e-10):
                intersections.append(pt)
    if len(intersections) < 2:
        return dict(valid=False, reason='Fitted valley lies outside measured voltage range')
    intersections = np.unique(np.round(intersections,12),axis=0)
    if len(intersections) < 2:
        return dict(valid=False, reason='Valley only touches a scan boundary')
    order = np.argsort(intersections @ tangent)
    ends = intersections[order[[0,-1]]]
    line = np.linspace(ends[0],ends[1],60)
    # Uncertainty of the implicit line in its normal direction (mV).
    def line_res(params):
        nn, dd = geometry(params)
        return ((line-center)*1000)@nn-dd
    J = []
    for k in range(5):
        step = max(1e-7,abs(p[k])*1e-5)
        plus, minus = p.copy(),p.copy();plus[k]+=step;minus[k]-=step
        J.append((line_res(plus)-line_res(minus))/(2*step))
    J = np.array(J).T
    band = 1.96*np.sqrt(np.maximum(0,np.einsum('ni,ij,nj->n',J,pc,J)))/1000
    warnings = []
    if chi2 > 3:
        warnings.append('Rank-one valley model has large residuals: curvature, drift or a second response may be present')
    if float(np.max(band)) > .25*float(np.min(np.ptp(xy,axis=0))):
        warnings.append('Valley location is poorly constrained; acquire more counts or a wider scan')
    slices = slice_minima(points)
    return dict(valid=True, center=center.tolist(), normal=normal.tolist(), offset_mv=offset,
                floor=floor, slope_per_mv=norm, reduced_chi2=chi2,
                affine_singular_values=singular.tolist(), parameters=p.tolist(),
                parameter_covariance=pc.tolist(), line=line.tolist(), ci95_v=band.tolist(),
                distance_mv=distance.tolist(), along_mv=(z@tangent).tolist(),
                slices=slices, warnings=warnings, apply_allowed=not warnings,
                ci_method='Local linearized 95% normal interval, conditional on rank-one model')


def slice_minima(points):
    """Independent weighted quadrature fits per fixed L_IN, excluding edge minima."""
    rows = []
    for x in sorted({p['left'] for p in points}):
        group = [p for p in points if p['left']==x]
        if len(group)<4:
            continue
        y = np.array([p['right'] for p in group]); cy = float(y.mean()); t=(y-cy)*1000
        obs = np.array([p['fit']['q'] for p in group])
        W = np.array([np.linalg.inv(np.linalg.cholesky(np.array(p['fit']['covariance'])+np.eye(2)*1e-14)) for p in group])
        def residual(p):return np.einsum('nij,nj->ni',W,p[:2]+t[:,None]*p[2:]-obs).ravel()
        initial = np.linalg.lstsq(np.column_stack((np.ones(len(t)),t)),obs,rcond=None)[0].ravel()
        fit=least_squares(residual,initial)
        def minimum(p):return -float(p[:2]@p[2:]/(p[2:]@p[2:]))
        if np.linalg.norm(fit.x[2:])<1e-8:continue
        t0=minimum(fit.x); y0=cy+t0/1000
        if not y.min()<y0<y.max():continue
        cov=np.linalg.pinv(fit.jac.T@fit.jac)*max(1,float(fit.fun@fit.fun/max(1,len(fit.fun)-4)))
        grad=[]
        for k in range(4):
            a,b=fit.x.copy(),fit.x.copy();a[k]+=1e-7;b[k]-=1e-7
            grad.append((minimum(a)-minimum(b))/2e-7)
        se=float(np.sqrt(max(0,np.array(grad)@cov@grad)))/1000
        def floor_at(p):return float(np.linalg.norm(p[:2]+p[2:]*minimum(p)))
        fg=[]
        for k in range(4):
            a,b=fit.x.copy(),fit.x.copy();a[k]+=1e-7;b[k]-=1e-7
            fg.append((floor_at(a)-floor_at(b))/2e-7)
        floor_se=float(np.sqrt(max(0,np.array(fg)@cov@fg)))
        rows.append(dict(left=x,right=y0,right_se=se,floor=floor_at(fit.x),floor_se=floor_se))
    return rows


def nearest_candidate(valley, voltage):
    if not valley.get('valid'):
        raise ValueError('No fitted compensation line')
    ends = np.array(valley['line'])[[0,-1]]
    d=ends[1]-ends[0]
    t=np.clip((np.array(voltage)-ends[0])@d/(d@d),0,1)
    return (ends[0]+t*d).tolist()
