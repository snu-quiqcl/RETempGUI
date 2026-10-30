"""Pure scan geometry and Gaussian coupling-profile fits (coordinates in µm)."""
import warnings
import numpy as np
from scipy.optimize import curve_fit, OptimizeWarning


def axis_points(start, stop, step):
    if not all(np.isfinite(v) for v in (start, stop, step)) or step <= 0 or stop <= start:
        raise ValueError('축 범위는 start < stop, step > 0이어야 합니다.')
    intervals = (stop - start) / step
    if not np.isclose(intervals, round(intervals), rtol=0, atol=1e-6):
        raise ValueError('범위 길이가 step의 정수배여야 합니다.')
    if not 2 <= round(intervals) <= 1000:
        raise ValueError('축별 3–1001개 위치를 지정하세요.')
    return np.linspace(start, stop, round(intervals) + 1)


def gaussian(coords, background, amplitude, x0, y0, wx, wy):
    x, y = coords
    return background + amplitude * np.exp(-2 * (((x-x0)/wx)**2 + ((y-y0)/wy)**2))


def fit_mfd(xs, ys, counts):
    z = np.asarray(counts, dtype=float)
    if z.shape != (len(ys), len(xs)) or not np.all(np.isfinite(z)):
        raise ValueError('완료된 scan만 MFD fitting 가능합니다.')
    if len(xs) < 5 or len(ys) < 5 or np.ptp(z) <= 0:
        raise ValueError('MFD fitting에는 각 축 5점 이상과 변화하는 신호가 필요합니다.')
    xx, yy = np.meshgrid(xs, ys)
    iy, ix = np.unravel_index(np.argmax(z), z.shape)
    spanx, spany = float(np.ptp(xs)), float(np.ptp(ys))
    dx, dy = abs(xs[1]-xs[0]), abs(ys[1]-ys[0])
    guess = [max(0, float(z.min())), float(np.ptp(z)), xs[ix], ys[iy], spanx/3, spany/3]
    lower = [0, 0, xs[0], ys[0], dx/4, dy/4]
    upper = [np.inf, np.inf, xs[-1], ys[-1], spanx*2, spany*2]
    with warnings.catch_warnings():
        warnings.simplefilter('error', OptimizeWarning)
        pars, covariance = curve_fit(gaussian, (xx.ravel(), yy.ravel()), z.ravel(),
            p0=guess, bounds=(lower, upper), maxfev=20000, x_scale='jac')
    prediction = gaussian((xx, yy), *pars)
    residual = z - prediction
    r2 = 1 - float(np.sum(residual**2) / np.sum((z-z.mean())**2))
    errors = np.sqrt(np.diag(covariance))
    b, a, x0, y0, wx, wy = map(float, pars)
    flags = []
    if r2 < 0.8:
        flags.append('낮은 R²: Gaussian 모델과 데이터가 잘 맞지 않음')
    if min(x0-xs[0], xs[-1]-x0) < wx or min(y0-ys[0], ys[-1]-y0) < wy:
        flags.append('스캔 범위가 1/e² 경계를 충분히 포함하지 않음')
    if wx < dx or wy < dy:
        flags.append('step보다 작은 폭: 더 작은 step 필요')
    if not np.all(np.isfinite(errors)) or errors[4] > wx/2 or errors[5] > wy/2:
        flags.append('폭의 피팅 불확도가 큼')
    return dict(model='B + A exp(-2*((x-x0)/wx)^2 -2*((y-y0)/wy)^2)',
        background=b, amplitude=a, x0_um=x0, y0_um=y0, wx_um=wx, wy_um=wy,
        coupling_mfd_x_um=2*wx, coupling_mfd_y_um=2*wy,
        mfd_x_std_um=float(2*errors[4]), mfd_y_std_um=float(2*errors[5]),
        r_squared=r2, warnings=flags,
        interpretation='Effective 1/e² coupling-profile diameter; not intrinsic fiber MFD without optical-mode calibration')



def fit_profiles(xs,ys,counts):
    """Return the elliptical MFD fit or its failure for display and saving."""
    try:return fit_mfd(xs,ys,counts)
    except Exception as exc:return {'error':str(exc)}
