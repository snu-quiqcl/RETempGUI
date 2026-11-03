"""Measurement storage defaults, independent of the launch working directory."""
from pathlib import Path
from datetime import date

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_ROOT = Path(__file__).resolve().parent / 'data'

def data_directory(kind):
    return DATA_ROOT / kind

def resolve_data_directory(directory=None, kind='characterization'):
    if directory is None or not str(directory).strip():
        return data_directory(kind)
    path = Path(directory).expanduser()
    # Redirect former shipped defaults, including absolute paths on this PC.
    relative = path
    if path.is_absolute():
        try: relative = path.relative_to(PROJECT_ROOT)
        except ValueError: return path.resolve()
    parts = relative.as_posix().strip('/').split('/')
    if parts[:2] == ['logs', 'fpga_counts']:
        return DATA_ROOT.joinpath('input_counts', *parts[2:]).resolve()
    if parts[:2] == ['logs', 'fiber_scan']:
        return DATA_ROOT.joinpath('scans', *parts[2:]).resolve()
    if parts and parts[0] == 'data':
        return DATA_ROOT.joinpath(*parts[1:]).resolve()
    if parts[:2] == ['labremote', 'data']:
        return PROJECT_ROOT.joinpath(*parts).resolve()
    # Preserve explicitly selected custom destinations.
    if kind == 'scans' and not path.is_absolute():
        return (PROJECT_ROOT / path).resolve()
    return path.resolve()


SCAN_FOLDERS = ('EA_collection', 'EA_excitation', 'EC_collection', 'EC_excitation')

def scan_data_directory(directory, number):
    """Split the shared scan default by tab; preserve explicit custom folders."""
    if type(number) is not int or not 1 <= number <= len(SCAN_FOLDERS):
        raise ValueError('Scan number must be 1..4')
    return tab_data_directory(directory, 'scans', SCAN_FOLDERS[number - 1])


def _experiment_directory(directory, category, *parts):
    base = resolve_data_directory(directory, category)
    # Explicit per-run directories (e.g. archived sweep points) remain intact.
    return base.joinpath(*parts) if base == data_directory(category) else base

def _dated_experiment_directory(directory, category, *parts):
    """Resolve the date once per run; roll old auto-generated UI paths forward.

    Custom destinations and explicit workflow sweep-point folders remain intact.
    Existing undated files are never moved.
    """
    base = resolve_data_directory(directory, category)
    tab = data_directory(category).joinpath(*parts)
    automatic = base in (data_directory(category), tab)
    if base.parent == tab:
        try:
            automatic = date.fromisoformat(base.name).isoformat() == base.name
        except ValueError:
            pass
    return tab / date.today().isoformat() if automatic else base


def characterization_directory(directory, chamber, experiment):
    if chamber not in ('EA', 'EC'):
        raise ValueError('Invalid chamber')
    if experiment not in ('fluorescence', 'rabi', 'ramsey', 'spam', 'initialization'):
        raise ValueError('Invalid characterization experiment')
    return _dated_experiment_directory(directory, 'characterization', chamber, experiment)

def decay_directory(directory, chamber, mode):
    if chamber not in ('EA', 'EC') or mode not in ('171_single', '174_single', '171_dual', '174_dual'):
        raise ValueError('Invalid decay chamber/mode')
    return _dated_experiment_directory(directory, 'decay', chamber, mode.replace('_dual', '_interferometer'))

def counts_directory(directory, channel_name):
    # Names originate from the active hardware definition, never inferred EA/EC.
    if not isinstance(channel_name, str) or not channel_name.isidentifier():
        raise ValueError('Invalid input channel name')
    return tab_data_directory(directory, 'input_counts', channel_name)


def tab_data_directory(directory, category, *parts):
    """Default tab/device data destination, dated once when a session starts."""
    return _dated_experiment_directory(directory, category, *parts)


def series_directory(directory, recipe):
    chamber = recipe.get('chamber') if isinstance(recipe, dict) else None
    experiment = recipe.get('experiment') if isinstance(recipe, dict) else None
    if chamber in ('EA', 'EC') and experiment in ('fluorescence', 'rabi', 'ramsey', 'spam', 'initialization'):
        return characterization_directory(directory, chamber, experiment)
    return tab_data_directory(directory, 'characterization', 'series')
