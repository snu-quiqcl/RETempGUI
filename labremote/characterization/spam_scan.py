"""Typed scan axes; values in presets and plots use the displayed units."""
from copy import deepcopy
from dataclasses import dataclass
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
        'frequency': Parameter('Frequency', 'MHz', 53, 13600, 6, 1e6, 'set_frequency', 'channel_{channel}.frequency_hz'),
    },
    'sg384': {
        'power': Parameter('Power', 'dBm', -110, 16.5, 2, method='set_power', path='{channel}_power_dbm'),
        'frequency': Parameter('Frequency', 'MHz', 0, 4050, 6, 1e6, 'set_frequency', 'frequency'),
    },
    'anapico': {
        'frequency': Parameter('Frequency', 'MHz', 10, 20000, 6, 1e6, 'set_frequency', 'frequency'),
    },
    'dds4': {
        'vva': Parameter('VVA level', 'level', 0, 1000, 0, method='set_vva', path='ch{channel}.vva_level'),
        'frequency': Parameter('Frequency', 'MHz', 10, 400, 6, 1e6, 'set_frequency', 'ch{channel}.frequency_hz'),
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
        return PARAMETERS[axis['family']][axis['parameter']]
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


def axis_values(axis):
    p = spec(axis)
    if set(axis) != {'family', 'device', 'channel', 'parameter', 'start', 'stop', 'points', 'settle_s'}:
        raise ValueError('Invalid axis fields')
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
    raw = np.linspace(start, stop, n)
    values = np.round(raw, p.decimals)
    if not np.allclose(raw, values, rtol=0, atol=10**(-p.decimals)*1e-5):
        raise ValueError(f'{p.title}: 점 간격이 장비/FPGA 분해능에 맞지 않습니다. 범위 또는 점 개수를 바꾸세요.')
    if len(set(values)) != n:
        raise ValueError('분해능 적용 후 중복된 축 값이 있습니다.')
    return [int(v) if p.decimals == 0 else float(v) for v in values]


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


def draw_map(figure, settings, records, metric='average_spam_error', selected=None):
    from matplotlib.patches import Rectangle
    xs, ys = axis_values(settings['x']), axis_values(settings['y'])
    def edges(values):
        delta = (values[1] - values[0]) / 2
        return np.r_[np.array(values) - delta, values[-1] + delta]
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
    for point in records:
        if point['status'] != 'completed':
            ax.plot(point['x'], point['y'], 'rx', markersize=9)
    if selected is not None:
        ix, iy = selected
        ax.add_patch(Rectangle((xe[ix], ye[iy]), xe[ix+1]-xe[ix], ye[iy+1]-ye[iy],
                               fill=False, edgecolor='white', linewidth=2))
    figure.subplots_adjust(left=.14, right=.94, bottom=.20, top=.91)
    return ax
