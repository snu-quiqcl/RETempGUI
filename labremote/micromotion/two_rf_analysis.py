"""Intersection of independent rank-one valley fits in compensation volts."""
import numpy as np


def intersection(high, low, bounds, *, min_angle_deg=5., max_ci_v=.005):
    """Propagate both five-parameter fit covariances to the intersection.

    The local covariance assumes independent scans and the existing rank-one
    model. It does not include RF calibration error or inter-scan drift.
    """
    valleys = (high, low)
    for label, valley in zip(('High RF', 'Low RF'), valleys):
        if not valley.get('valid') or not valley.get('apply_allowed'):
            return dict(valid=False, reason=label + ': valley is not suitable for application')
    limits = np.asarray(bounds, dtype=float)
    if limits.shape != (2, 2) or not np.isfinite(limits).all() or np.any(limits[0] >= limits[1]):
        raise ValueError('Bounds must contain lower and upper L_IN/R_IN voltages')
    if not 0 < min_angle_deg <= 90 or not np.isfinite(max_ci_v) or max_ci_v <= 0:
        raise ValueError('Invalid intersection quality limits')
    params = np.array([v['parameters'] for v in valleys], dtype=float)
    covs = np.array([v['parameter_covariance'] for v in valleys], dtype=float)
    centers = np.array([v['center'] for v in valleys], dtype=float)
    if params.shape != (2, 5) or covs.shape != (2, 5, 5) or centers.shape != (2, 2):
        raise ValueError('Incomplete valley fit covariance')
    if not all(np.isfinite(a).all() for a in (params, covs, centers)):
        raise ValueError('Nonfinite valley fit')
    if any(np.linalg.eigvalsh(c).min() < -1e-12 for c in covs):
        raise ValueError('Invalid fit covariance')

    def geometry(p):
        normals = np.column_stack((np.cos(p[:, 4]), np.sin(p[:, 4])))
        u = p[:, 2:4]
        scale = np.sum(u*u, axis=1)
        if np.any(scale <= 1e-16):
            raise ValueError('Unidentifiable valley response')
        offsets = -np.sum(p[:, :2]*u, axis=1)/scale/1000
        rhs = np.sum(normals*centers, axis=1) + offsets
        return normals, rhs

    normals, rhs = geometry(params)
    angle = float(np.degrees(np.arccos(np.clip(abs(normals[0] @ normals[1]), 0, 1))))
    if angle < min_angle_deg:
        return dict(valid=False, reason='Valleys are nearly parallel', angle_deg=angle)
    point = np.linalg.solve(normals, rhs)
    jac = np.empty((2, 10))
    for k in range(10):
        step = max(1e-7, abs(params.flat[k])*1e-5)
        plus, minus = params.copy(), params.copy()
        plus.flat[k] += step
        minus.flat[k] -= step
        jac[:, k] = (np.linalg.solve(*geometry(plus))-np.linalg.solve(*geometry(minus)))/(2*step)
    covariance = sum(jac[:, i*5:(i+1)*5] @ covs[i] @ jac[:, i*5:(i+1)*5].T for i in range(2))
    ci = 1.96*np.sqrt(np.maximum(0, np.diag(covariance)))
    reasons = []
    if not np.isfinite(covariance).all():
        reasons.append('Intersection uncertainty is nonfinite')
    if np.any(point < limits[0]) or np.any(point > limits[1]):
        reasons.append('Intersection is outside the common measured rectangle')
    if np.any(ci > max_ci_v):
        reasons.append('Intersection uncertainty exceeds the configured limit')
    if np.any(point-ci < limits[0]) or np.any(point+ci > limits[1]):
        reasons.append('Intersection confidence interval extends outside the measured rectangle')
    return dict(valid=not reasons, reason='; '.join(reasons), candidate=point.tolist(),
                covariance_v2=covariance.tolist(), ci95_v=ci.tolist(), angle_deg=angle,
                uncertainty_model='Independent scans; local linearized marginal 95% intervals; conditional on rank-one model')
