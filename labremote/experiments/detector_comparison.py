"""Derived detector comparisons; physical acquisition channels stay unchanged."""
from collections import Counter

LABELS = {'PMT': 'PMT 1', 'PMT2': 'PMT 2', 'SUM': 'PMT 1 + PMT 2'}
COLORS = {'PMT': '#2474e8', 'PMT2': '#e68a2e', 'SUM': '#279765'}


def comparison_roles(settings):
    return ('PMT', 'PMT2', 'SUM') if settings.get('detector_count', 1) == 2 else ('PMT',)


def paired_sum(first, second):
    if len(first) != len(second):
        raise ValueError('PMT 1 and PMT 2 samples must be paired shot by shot')
    # Python ints prevent uint16 wraparound in the derived channel.
    return [int(a) + int(b) for a, b in zip(first, second)]


def comparison_counts(counts):
    channels = dict(counts) if isinstance(counts, dict) else {'PMT': counts}
    if 'PMT2' in channels:
        channels['SUM'] = paired_sum(channels['PMT'], channels['PMT2'])
    return channels


def histogram_steps(values, frequencies=None):
    """Sparse unit-width bins, including zero gaps, without allocating 131071 bins."""
    counts = Counter(map(int, values)) if frequencies is None else {
        int(v): int(n) for v, n in zip(values, frequencies) if n}
    padded = {0: 0}
    for value in counts:
        padded[max(0, value - 1)] = 0
        padded[value + 1] = 0
    padded.update(counts)
    x = sorted(padded)
    return x, [padded[v] for v in x]
