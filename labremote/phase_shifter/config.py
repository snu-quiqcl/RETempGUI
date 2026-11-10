"""Configuration shared by the tab and background scan."""
from copy import deepcopy
import math
from decimal import Decimal, ROUND_HALF_UP
from labremote.devices.fpga.controller import hd
from .sequence import build_program
from .calibration import resolve

DEFAULTS = dict(phase_angle_deg=90., N_average=100, half_pi_time=5000,
    phase_zero_settle_clocks=1000, phase_settle_clocks=1000,
    T_cool=50000, T_cool_repeat=2, T_init=50000, T_det=50000,
    T_det_repeat=2, T_wait_for_aom_off=1000,
    scan_start_deg=0., scan_stop_deg=360., scan_step_deg=15., threshold=5, timeout_s=30.)

DEGREES_PER_CODE = 360 / 4096


def phase_point(angle):
    """Nominal linear 12-bit model; 360 degrees wraps to code zero."""
    if isinstance(angle, bool) or not isinstance(angle, (int, float)) or not math.isfinite(angle) or not 0 <= angle <= 360:
        raise ValueError('각도는 0..360° 범위의 유한한 숫자여야 합니다.')
    code = int((Decimal(str(angle)) * 4096 / 360).to_integral_value(rounding=ROUND_HALF_UP)) % 4096
    return dict(requested_angle_deg=float(angle), code=code,
                applied_angle_deg=code * DEGREES_PER_CODE)


def normalize(value):
    c = deepcopy(value)
    # Migrate existing code-based files without changing their physical codes.
    for old, new in [('scan_start', 'scan_start_deg'), ('scan_stop', 'scan_stop_deg'),
                     ('scan_step', 'scan_step_deg'), ('phase_code', 'phase_angle_deg')]:
        if new not in c and old in c:
            c[new] = c[old] * DEGREES_PER_CODE
        c.pop(old, None)
    c['schema_version'] = 2
    c['phase_code'] = phase_point(c['phase_angle_deg'])['code']
    return c


def scan_points(c, skipped=None):
    if c.get('calibration') is not None:
        from .calibration import rows
        rows(c['calibration'])
    start, stop, step = (c[key] for key in ('scan_start_deg', 'scan_stop_deg', 'scan_step_deg'))
    phase_point(start)
    phase_point(stop)
    if isinstance(step, bool) or not isinstance(step, (int, float)) or not math.isfinite(step) or not 0 < step <= 360:
        raise ValueError('각도 간격은 0보다 크고 360° 이하여야 합니다.')
    if start > stop:
        raise ValueError('시작 각도는 끝 각도보다 클 수 없습니다.')
    a, b, delta = (Decimal(str(v)) for v in (start, stop, step))
    count = int((b - a) // delta) + 1
    append_end = a + (count - 1) * delta != b
    if count + append_end > 4097:
        raise ValueError('스캔은 최대 4097지점입니다. 각도 간격을 늘리세요.')
    angles = [float(a + i * delta) for i in range(count)]
    if append_end:
        angles.append(float(b))
    plan = []
    for angle in angles:
        try:
            plan.append(resolve(angle, c.get('calibration')))
        except ValueError as exc:
            if not c.get('calibration') or not c.get('skip_unreliable', False):
                raise
            if skipped is not None:
                skipped.append(dict(angle_deg=angle, reason=str(exc)))
    if not plan:
        raise ValueError('보정 가능한 스캔 각도가 없습니다.')
    return plan


def codes(c):
    return [point['code'] for point in scan_points(c)]


def validate(value, single=False):
    c = normalize(value)
    plan = [resolve(c["phase_angle_deg"], c.get("calibration"))] if single else scan_points(c)
    if c.get("calibration"):
        c["phase_code"] = plan[0]["code"]
    for key, low, high in [('threshold', 0, 65535)]:
        if type(c[key]) is not int or not low <= c[key] <= high:
            raise ValueError(f'{key}: {low}..{high} 범위의 정수를 입력하세요.')
    timeout = c['timeout_s']
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or not .1 <= timeout <= 600:
        raise ValueError('Timeout은 0.1..600초 범위여야 합니다.')
    # Same definition and same validation used for actual execution.
    build_program(c, hd).program(show=False)
    return c
