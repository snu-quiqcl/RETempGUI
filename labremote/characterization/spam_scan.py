"""Typed scan axes; values in presets and plots use the displayed units."""
from copy import deepcopy
from dataclasses import dataclass, replace
from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING, ROUND_FLOOR, localcontext
import math
import numpy as np
from . import pulse_experiment as spam


@dataclass(frozen=True)
class Parameter:
    title: str
    unit: str
    low: float
    high: float
    decimals: int
    scale: float = 1
    method: str = ''
    path: str = ''


PARAMETERS = {
    'windfreak': {
        'power': Parameter('Power', 'dBm', -60, 20, 2, method='set_power', path='channel_{channel}.power_dbm'),
        'frequency': Parameter('Frequency', 'MHz', 53, 13600, 7, 1e6, 'set_frequency', 'channel_{channel}.frequency_hz'),
    },
    'sg384': {
        'power': Parameter('Power', 'dBm', -110, 16.5, 2, method='set_power', path='{channel}_power_dbm'),
        'frequency': Parameter('Frequency', 'MHz', 0, 4050, 12, 1e6, 'set_frequency', 'frequency'),
    },
    'anapico': {
        'frequency': Parameter('Frequency', 'MHz', 10, 20000, 9, 1e6, 'set_frequency', 'frequency'),
    },
    'dds4': {
        'vva': Parameter('VVA level', 'level', 0, 1000, 0, method='set_vva', path='ch{channel}.vva_level'),
        'frequency': Parameter('Frequency', 'MHz', 10, 400, 12, 1e6, 'set_frequency', 'ch{channel}.frequency_hz'),
    },
    'spam': {
        key: Parameter(title.replace(' (us)', ''), 'µs', lo, hi, 2, 100)
        for key, title, lo, hi, dec, step in spam.fields('spam') if key in spam.times('spam')
    },
}
CHANNELS = {'windfreak': ('A', 'B'), 'sg384': ('N', 'BNC'), 'anapico': ('',),
            'dds4': (1, 2, 3, 4), 'spam': ('',)}
METRICS = {
    'average_spam_error': 'Average SPAM error (%)', 'spam_fidelity': 'SPAM fidelity (%)',
    'error_0': 'State 0 error (%)', 'error_1': 'State 1 error (%)',
    'success_0': 'State 0 acceptance (%)', 'success_1': 'State 1 acceptance (%)',
}


def spec(axis):
    try:
        p = PARAMETERS[axis['family']][axis['parameter']]
        if axis['family'] == 'sg384' and axis['parameter'] == 'power' and axis.get('channel') == 'BNC':
            return replace(p, low=-47, high=13, decimals=4)
        return p
    except (KeyError, TypeError):
        raise ValueError('지원하지 않는 축 파라미터입니다.') from None


def path(axis):
    channel = axis['channel']
    if axis['family'] == 'sg384':
        channel = channel.lower()
    return spec(axis).path.format(channel=channel)


def identity(axis):
    if axis['family'] == 'spam':
        return ('spam', axis['parameter'])
    # SG384 frequency is shared by both output ports.
    return axis['family'], axis['device'], path(axis)


def label(axis):
    p = spec(axis)
    target = 'SPAM' if axis['family'] == 'spam' else axis['device'] + (f" / {axis['channel']}" if axis['channel'] != '' else '')
    return f'{target} · {p.title} ({p.unit})'


def number(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(name + ' must be a finite number')
    return value


def is_dds_frequency(axis):
    return axis['family'] == 'dds4' and axis['parameter'] == 'frequency'


def resolution(axis):
    """Displayed-unit step. Decimal prevents negative-half/linspace artifacts."""
    if is_dds_frequency(axis):
        clock = number(axis.get('dds_clock_hz', 1e9), 'DDS system clock')
        if not 1 <= clock <= 1e9: raise ValueError('DDS system clock must be 1..1e9 Hz')
        return Decimal(str(clock)) / Decimal(2**48) / Decimal(1000000)
    return Decimal(10) ** -spec(axis).decimals


def resolution_note(axis):
    p = spec(axis)
    if is_dds_frequency(axis):
        return f"48-bit DDS · clock {axis.get('dds_clock_hz',1e9)/1e6:g} MHz · {float(resolution(axis))*1e6:.12g} Hz/step (server clock와 일치 필요)"
    if axis['family'] == 'sg384' and axis['parameter'] == 'power' and axis['channel'] == 'BNC':
        return '명령 간격 0.0001 dBm · BNC 실제 분해능은 <1% · readback으로 확정'
    value = float(resolution(axis)) * (p.scale if p.unit == 'MHz' else 1)
    return f"적용 간격 {value:.12g} {'Hz' if p.unit == 'MHz' else p.unit}"


def axis_plan(axis):
    p = spec(axis)
    if set(axis) - {'dds_clock_hz'} != {'family', 'device', 'channel', 'parameter', 'start', 'stop', 'points', 'settle_s'}:
        raise ValueError('Invalid axis fields')
    if 'dds_clock_hz' in axis and not is_dds_frequency(axis): raise ValueError('DDS clock only applies to DDS frequency')
    if axis['channel'] not in CHANNELS[axis['family']]:
        raise ValueError('Invalid axis channel')
    if not isinstance(axis['device'], str) or (axis['family'] != 'spam' and not axis['device'].strip()):
        raise ValueError('축에 사용할 장비를 선택하세요.')
    n = axis['points']
    if type(n) is not int or not 2 <= n <= 501:
        raise ValueError('축 점 개수는 2–501이어야 합니다.')
    start, stop = (number(axis[k], k) for k in ('start', 'stop'))
    if not p.low <= start < stop <= p.high:
        raise ValueError(f'{p.title}: {p.low} ≤ Start < Stop ≤ {p.high}')
    if not 0 <= number(axis['settle_s'], 'settle_s') <= 60:
        raise ValueError('안정화 대기는 0–60초입니다.')
    rows = []
    with localcontext() as context:
        context.prec = 50
        step = resolution(axis)
        first, last = Decimal(str(start)), Decimal(str(stop))
        for i in range(n):
            raw = first + (last-first)*i/(n-1)
            tick = (raw/step).to_integral_value(rounding=ROUND_HALF_UP)
            if is_dds_frequency(axis):
                ceiling = min(Decimal(str(p.high)), Decimal(str(axis.get('dds_clock_hz',1e9)))/2000000)
                if raw > ceiling: raise ValueError('DDS frequency exceeds system clock / 2')
                tick = min(max(tick,(Decimal(str(p.low))/step).to_integral_value(rounding=ROUND_CEILING)),
                           (ceiling/step).to_integral_value(rounding=ROUND_FLOOR))
            value = tick*step
            command = value*Decimal(str(p.scale))
            if is_dds_frequency(axis):
                clock = Decimal(str(axis.get('dds_clock_hz',1e9)))
                if value*Decimal(1000000) > clock/2: raise ValueError('DDS frequency exceeds system clock / 2')
                # Server truncates the FTW; an interior-bin command reliably
                # transmits the nearest word despite binary float conversion.
                command = (tick+Decimal('.25'))*clock/Decimal(2**48)
            if not Decimal(str(p.low)) <= value <= Decimal(str(p.high)):
                raise ValueError('반올림 값이 허용 범위를 벗어납니다.')
            if is_dds_frequency(axis): command = min(command,ceiling*Decimal(str(p.scale)))
            rows.append(dict(requested=float(raw), applied=int(value) if p.decimals==0 else float(value),
                             command=int(command) if p.decimals==0 or axis['family']=='spam' else float(command),
                             tick=int(tick)))
    values = [r['applied'] for r in rows]
    if len(set(values)) != n:
        raise ValueError('반올림 후 중복된 축 값이 있습니다. 점 개수를 줄이거나 범위를 넓히세요.')
    if len({r['command'] for r in rows}) != n: raise ValueError('전송값 변환 후 중복된 축 값이 있습니다.')
    return rows


def axis_values(axis):
    return [row['applied'] for row in axis_plan(axis)]


def plot_values(settings, records, frozen=None):
    """Frozen run plan plus completed point readbacks; never reinterpret archives."""
    result = {key:list(frozen[key]) if frozen else axis_values(settings[key]) for key in ('x','y')}
    planned = deepcopy(result)
    known = {key:set() for key in result}
    for point in records:
        if point['status'] != 'completed': continue
        for key in ('x','y'):
            if point.get(key) is not None:
                result[key][point['i'+key]] = point[key]
                known[key].add(point['i'+key])
    for key,values in result.items():
        # A readback offset may overlap a still-unmeasured planned coordinate.
        # Interpolate only gray cells in that case; measured centers stay exact.
        if not all(b>a for a,b in zip(values,values[1:])) and known[key]:
            indices = sorted(known[key])
            xp = [planned[key][i] for i in indices]
            fp = [values[i] for i in indices]
            for i in range(len(values)):
                if i in known[key]: continue
                x = planned[key][i]
                values[i] = (x+fp[0]-xp[0] if x<xp[0] else x+fp[-1]-xp[-1] if x>xp[-1]
                             else float(np.interp(x,xp,fp)))
        if not all(b>a for a,b in zip(values,values[1:])): raise ValueError('실제 축 값이 중복되거나 순서가 바뀌었습니다.')
    return result


def settings_at(c, x, y):
    settings = deepcopy(c['spam'])
    for axis, value in ((c['x'], x), (c['y'], y)):
        if axis['family'] == 'spam':
            settings[axis['parameter']] = round(value * spec(axis).scale)
    return spam.validate('spam', settings)


def validate(value):
    if not isinstance(value, dict) or set(value) != {'schema_version', 'experiment', 'spam', 'x', 'y', 'restore'}:
        raise ValueError('Invalid SPAM 2D Scan settings')
    if value['schema_version'] != 1 or value['experiment'] != 'spam_2d' or type(value['restore']) is not bool:
        raise ValueError('Invalid SPAM 2D Scan schema')
    spam.validate('spam', value['spam'])
    xs, ys = axis_values(value['x']), axis_values(value['y'])
    if identity(value['x']) == identity(value['y']):
        raise ValueError('X와 Y에 같은 파라미터를 선택할 수 없습니다.')
    if len(xs) * len(ys) > 10000:
        raise ValueError('최대 10,000개 측정점까지 지원합니다.')
    # All supported sequence fields affect duration monotonically. Corners
    # catch maximum timeout/sequence limits without building every program.
    for x in (xs[0], xs[-1]):
        for y in (ys[0], ys[-1]):
            settings_at(value, x, y)
    return deepcopy(value)


def metrics(data):
    out = {key: data[key] for key in ('average_spam_error', 'spam_fidelity')}
    for state in data['states']:
        out['error_' + str(state['condition'])] = state['spam_error']
        out['success_' + str(state['condition'])] = state['success_probability']
    return out


def matrix(settings, records, metric):
    result = np.full((settings['y']['points'], settings['x']['points']), np.nan)
    for point in records:
        value = point.get('metrics', {}).get(metric)
        if point['status'] == 'completed' and value is not None:
            result[point['iy'], point['ix']] = value * 100
    return result


def draw_map(figure, settings, records, metric='average_spam_error', selected=None, axis_values=None):
    from matplotlib.patches import Rectangle
    axes = plot_values(settings, records, axis_values)
    xs, ys = axes['x'], axes['y']
    def edges(values):
        values = np.asarray(values, dtype=float)
        # Rounded VVA steps need not be uniform. Bound each cell by the
        # midpoint between its actual neighboring device values.
        return np.r_[values[0] - (values[1]-values[0])/2,
                     (values[:-1]+values[1:])/2,
                     values[-1] + (values[-1]-values[-2])/2]
    xe, ye = edges(xs), edges(ys)
    figure.clear()
    ax = figure.add_subplot(111)
    cmap = __import__('matplotlib').colormaps['viridis'].copy()
    cmap.set_bad('#e3e7eb')
    z = np.ma.masked_invalid(matrix(settings, records, metric))
    plot = ax.pcolormesh(xe, ye, z, cmap=cmap, shading='flat', vmin=0,
                         vmax=100 if 'success' in metric or metric == 'spam_fidelity' else max(1, float(z.max()) if z.count() else 1))
    figure.colorbar(plot, ax=ax, label=METRICS[metric])
    ax.set(xlabel=label(settings['x']), ylabel=label(settings['y']), title='SPAM 2D Scan')
    if settings['x']['family'] == 'dds4' and settings['x']['parameter'] == 'vva' and len(xs) <= 21:
        ax.set_xticks(xs)
    if settings['y']['family'] == 'dds4' and settings['y']['parameter'] == 'vva' and len(ys) <= 21:
        ax.set_yticks(ys)
    for point in records:
        if point['status'] != 'completed':
            ax.plot(point.get('x') if point.get('x') is not None else point.get('requested_x'),
                    point.get('y') if point.get('y') is not None else point.get('requested_y'), 'rx', markersize=9)
    if selected is not None:
        ix, iy = selected
        ax.add_patch(Rectangle((xe[ix], ye[iy]), xe[ix+1]-xe[ix], ye[iy+1]-ye[iy],
                               fill=False, edgecolor='white', linewidth=2))
    figure.subplots_adjust(left=.14, right=.94, bottom=.20, top=.91)
    return ax
