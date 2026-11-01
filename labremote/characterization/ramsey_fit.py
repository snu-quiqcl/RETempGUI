"""Original binomial-deviance Ramsey fit; sampling interval passed explicitly."""
import numpy as np
from scipy.optimize import least_squares
from scipy.special import xlogy

def ramsey_model(time_s, offset, amplitude, frequency_hz, t2_s, phase_rad):
    """Population = offset + amplitude * exp(-t/T2*) * cos(2*pi*f*t + phase)."""
    return offset + amplitude * np.exp(-np.asarray(time_s) / t2_s) * np.cos(2 * np.pi * frequency_hz * np.asarray(time_s) + phase_rad)

def population_and_error(bright_counts, shot_counts):
    """Actual bright fraction and a stabilized binomial standard error."""
    k = np.asarray(bright_counts, dtype=float)
    n = np.asarray(shot_counts, dtype=float)
    population = k / n
    p_for_error = (k + 0.5) / (n + 1)
    error = np.sqrt(p_for_error * (1 - p_for_error) / n)
    return (population, error)

def fit_ramsey(time_s, bright_counts, shot_counts, frequency_range_hz=None, *, precession_step_s):
    """Bounded multi-start fit using binomial deviance, with times in seconds.

    Frequency is the nonnegative, sampled Ramsey frequency, not Rabi frequency.
    The envelope is exponential, as in the original script. A scan too short
    to resolve decay produces a T2* status rather than a claimed measurement.
    """
    t = np.asarray(time_s, dtype=float)
    k = np.asarray(bright_counts, dtype=float)
    n = np.asarray(shot_counts, dtype=float)
    valid = np.isfinite(t) & np.isfinite(k) & np.isfinite(n) & (n > 0)
    t, k, n = (t[valid], k[valid], n[valid])
    order = np.argsort(t)
    t, k, n = (t[order], k[order], n[order])
    if len(t) <= 5 or np.ptp(t) <= 0:
        return {'status': 'failed', 'message': 'At least 6 distinct time points are needed.'}
    span = float(np.ptp(t))
    u = t / span
    nyquist_hz = 0.5 / precession_step_s
    f_low, f_high = (0.0, nyquist_hz) if frequency_range_hz is None else frequency_range_hz
    f_low = max(float(f_low), 0.0)
    f_high = min(float(f_high), nyquist_hz)
    if f_high <= f_low:
        return {'status': 'failed', 'message': 'Fit frequency range is outside the sampled band.'}
    population, sigma = population_and_error(k, n)

    def model_scaled(parameters):
        low, high, cycles, phase, decay = parameters
        return (low + high) / 2 + (high - low) / 2 * np.exp(-decay * u) * np.cos(2 * np.pi * cycles * u + phase)

    def deviance_residual(probability):
        p = np.clip(probability, 1e-12, 1 - 1e-12)
        deviance = 2 * (xlogy(k, k / (n * p)) + xlogy(n - k, (n - k) / (n * (1 - p))))
        return np.sign(k - n * p) * np.sqrt(np.maximum(deviance, 0))

    def residual(parameters):
        return deviance_residual(model_scaled(parameters))
    cycle_low, cycle_high = (f_low * span, f_high * span)
    cycle_grid = np.linspace(cycle_low, cycle_high, max(256, int(32 * (cycle_high - cycle_low))))
    seeds = []
    for decay in (0.0, 0.25, 1.0, 3.0, 8.0):
        envelope = np.exp(-decay * u)
        scores, parameters = ([], [])
        for cycles in cycle_grid:
            angle = 2 * np.pi * cycles * u
            design = np.column_stack((np.ones_like(u), envelope * np.cos(angle), envelope * np.sin(angle)))
            coefficients = np.linalg.lstsq(design / sigma[:, None], population / sigma, rcond=None)[0]
            offset = float(np.clip(coefficients[0], 0.001, 0.999))
            amplitude = min(float(np.hypot(*coefficients[1:])), offset, 1 - offset)
            phase = float(np.arctan2(-coefficients[2], coefficients[1]))
            seed = [offset - amplitude, offset + amplitude, cycles, phase, decay]
            scores.append(float(np.sum(residual(seed) ** 2)))
            parameters.append(seed)
        selected = []
        for index in np.argsort(scores):
            if all((abs(cycle_grid[index] - cycle_grid[j]) >= 0.35 for j in selected)):
                selected.append(index)
                seeds.append((scores[index], parameters[index]))
            if len(selected) == 4:
                break
    lower = np.array([0, 0, cycle_low, -4 * np.pi, 0.0])
    upper = np.array([1, 1, cycle_high, 4 * np.pi, 20.0])
    solutions = []
    for _, seed in sorted(seeds, key=lambda pair: pair[0]):
        seed = np.clip(seed, lower + 1e-09, upper - 1e-09)
        try:
            result = least_squares(residual, seed, bounds=(lower, upper), x_scale='jac', max_nfev=2000)
        except (ValueError, RuntimeError, FloatingPointError):
            continue
        if result.success and np.all(np.isfinite(result.x)):
            solutions.append(result)
    if not solutions:
        return {'status': 'failed', 'message': 'Ramsey optimization did not converge.'}
    best = min(solutions, key=lambda result: np.sum(result.fun ** 2))
    low, high, cycles, phase, decay = best.x
    offset, amplitude = ((low + high) / 2, (high - low) / 2)
    if amplitude < 0:
        amplitude = -amplitude
        phase += np.pi
    phase = (phase + np.pi) % (2 * np.pi) - np.pi
    covariance = np.full((5, 5), np.nan)
    if np.linalg.matrix_rank(best.jac) == 5:
        covariance = np.linalg.pinv(best.jac.T @ best.jac)
    standard_error = np.sqrt(np.maximum(np.diag(covariance), 0))
    frequency_hz = float(cycles / span)
    frequency_se_hz = float(standard_error[2] / span)
    t2_s = float(span / decay) if decay > 1e-08 else np.inf
    t2_se_s = float(span * standard_error[4] / decay ** 2) if decay > 1e-08 else np.inf
    t2_resolved = bool(np.isfinite(standard_error[4]) and decay > 2 * standard_error[4] and (1e-08 < decay < 19.99))
    deviance = float(np.sum(best.fun ** 2))
    constant_deviance = float(np.sum(deviance_residual(np.sum(k) / np.sum(n)) ** 2))
    bic_improvement = constant_deviance - deviance - 4 * np.log(len(t))
    notes = []
    if bic_improvement <= 0:
        notes.append('Oscillation is not resolved versus a constant population (BIC).')
    if not np.isfinite(frequency_se_hz) or frequency_se_hz >= frequency_hz:
        notes.append('Frequency uncertainty is large or unidentifiable.')
    if min(cycles - cycle_low, cycle_high - cycles) < 0.0001:
        notes.append('Frequency reached a fit boundary; inspect the sampling/range.')
    if not t2_resolved:
        notes.append('T2* is not resolved by this scan; saved T2* is only a fit parameter.')
    frequency_resolved = bool(bic_improvement > 0 and np.isfinite(frequency_se_hz) and (frequency_se_hz < frequency_hz) and (min(cycles - cycle_low, cycle_high - cycles) >= 0.0001))
    return {'status': 'ok' if frequency_resolved else 'uncertain', 'message': ' '.join(notes), 'model': 'offset + amplitude * exp(-time_s / t2_star_s) * cos(2*pi*frequency_hz*time_s + phase_rad)', 'offset': float(offset), 'amplitude': float(amplitude), 'contrast_peak_to_peak': float(2 * amplitude), 'frequency_hz': frequency_hz, 'frequency_se_hz': frequency_se_hz, 'frequency_resolved': frequency_resolved, 't2_star_s': t2_s, 't2_star_se_s': t2_se_s, 't2_resolved': t2_resolved, 'phase_rad': float(phase), 'deviance': deviance, 'degrees_of_freedom': len(t) - 5, 'bic_improvement_vs_constant': float(bic_improvement), 'frequency_range_hz': (f_low, f_high), 'nyquist_hz': nyquist_hz, 'internal_parameter_names': ['p_low', 'p_high', 'cycles_per_scan', 'phase_rad', 'decay_per_scan'], 'internal_parameters': best.x.copy(), 'internal_covariance': covariance, 'time_scale_s': span}
