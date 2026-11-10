"""Conditional Ramsey phase inference and piecewise-linear inverse interpolation."""
import bisect
import math


def isotonic(values, weights, sign):
    blocks = []
    for i, (value, weight) in enumerate(zip(values, weights)):
        blocks.append([i, i, weight, sign * value * weight])
        while len(blocks) > 1 and blocks[-2][3]/blocks[-2][2] > blocks[-1][3]/blocks[-1][2]:
            b, a = blocks.pop(), blocks.pop()
            blocks.append([a[0], b[1], a[2]+b[2], a[3]+b[3]])
    result = [0.] * len(values)
    for start, end, weight, total in blocks:
        result[start:end+1] = [sign*total/weight] * (end-start+1)
    return result


def fit(result):
    if result.get('settings', {}).get('calibration'):
        raise ValueError('현재 모델은 선형 코드 스캔 원본만 지원합니다. 보정 후 결과는 사용할 수 없습니다.')
    points = result['points']
    angles = [float(p['requested_angle_deg']) for p in points]
    codes = [p['code'] for p in points]
    probs = [float(p['probability']) for p in points]
    shots = [p['shots'] for p in points]
    if (len(points) < 7 or angles[0] != 0 or angles[-1] != 360 or 180 not in angles
            or codes[0] != 0 or codes[-1] != 0):
        raise ValueError('0°, 180°, 360°를 포함하는 전체 Ramsey 스캔이 필요합니다.')
    from .config import phase_point
    for a, c, p, n in zip(angles, codes, probs, shots):
        if (not math.isfinite(a) or type(c) is not int or c != phase_point(a)['code']
                or not math.isfinite(p) or not 0 <= p <= 1 or type(n) is not int or n <= 0):
            raise ValueError('유효하지 않은 선형 스캔 데이터입니다.')
    u = codes[:-1] + [4096]
    if any(b <= a for a, b in zip(angles, angles[1:])) or any(b <= a for a, b in zip(u, u[1:])):
        raise ValueError('각도와 코드는 중복 없이 증가해야 합니다.')
    bright = (probs[0]*shots[0]+probs[-1]*shots[-1])/(shots[0]+shots[-1])
    floor = [i for i,a in enumerate(angles) if 160 <= a <= 190]
    dark = sum(probs[i]*shots[i] for i in floor)/sum(shots[i] for i in floor)
    if bright-dark <= .05:
        raise ValueError('Ramsey contrast가 부족해 위상을 추정할 수 없습니다.')
    mid = angles.index(180)
    fitted = isotonic(probs[:mid+1], shots[:mid+1], -1)[:-1] + isotonic(probs[mid:], shots[mid:], 1)
    fitted = [min(bright, max(dark, p)) for p in fitted]
    fitted[0] = fitted[-1] = bright
    fitted[mid] = dark
    phase = [math.degrees(math.acos(max(-1., min(1., 2*(p-dark)/(bright-dark)-1)))) for p in fitted]
    phase[mid:] = [360-p for p in phase[mid:]]
    phase[0], phase[mid], phase[-1] = 0., 180., 360.
    return dict(codes=u, phases=phase, bright=bright, dark=dark,
                method='weighted_isotonic_cosine_inverse_piecewise_linear_v1',
                assumptions='One monotone 0..360 phase turn; fixed contrast; nominal 180 splits branches; plateau uses midpoint code')


def resolve(angle, model):
    phases, codes = model['phases'], model['codes']
    equal = [i for i,p in enumerate(phases) if abs(p-angle) < 1e-9]
    plateau = len(equal) > 1
    if angle in (0, 360):
        code, estimated = 0, 0.
        quality = 'reference_anchor'
    else:
        if equal:
            coordinate = (codes[equal[0]] + codes[equal[-1]])/2
        else:
            hi = bisect.bisect_right(phases, angle)
            lo = hi-1
            coordinate = codes[lo] + (angle-phases[lo])*(codes[hi]-codes[lo])/(phases[hi]-phases[lo])
        code = min(4095, int(math.floor(coordinate+.5)))
        hi = bisect.bisect_right(codes, code)
        lo = hi-1
        estimated = phases[lo] + (code-codes[lo])*(phases[hi]-phases[lo])/(codes[hi]-codes[lo])
        normalized = (1+math.cos(math.radians(angle)))/2
        quality = 'plateau_midpoint_assumption' if plateau else 'low_sensitivity_interpolated' if normalized < .05 or normalized > .95 else 'interpolated_conditional'
    return dict(requested_angle_deg=float(angle), code=code, applied_angle_deg=estimated,
                conversion_mode='ramsey_data_interpolation', quality=quality,
                plateau_code_interval=[codes[equal[0]], codes[equal[-1]]] if plateau and angle not in (0,360) else None)
