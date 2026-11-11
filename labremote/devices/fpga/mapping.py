"""Per-device signal names and per-experiment roles for the v4_03 bitstream.

The vendor module is never modified. Contexts carry immutable snapshots across
Qt callbacks, runner threads and queued operations; old sequencers keep their
reviewed role names, instructions and timing.
"""
from collections.abc import Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from functools import wraps
import inspect
import json
from pathlib import Path
from types import SimpleNamespace

from labremote.config.paths import CONFIG_ROOT
from .vendor import HardwareDefinition_v4_04 as physical
from .vendor import HardwareDefinition_remote_ent_test_ec as legacy

PINS = tuple(f'{bank}_{n}' for bank in ('ja', 'jb', 'jc', 'jd') for n in range(8))
DEFAULT_ROLES = {**{name: pin for pin, name in legacy.input_mapping.items()}, **legacy.output_mapping}
EXPERIMENTS = ('fluorescence', 'rabi', 'ramsey', 'spam', 'initialization', 'decay',
               'hom', 'entanglement', 'ion_check', 'micromotion', 'phase_shifter')
CURRENT = ContextVar('fpga_mapping', default=None)
FROZEN = ContextVar('fpga_workflow_profiles', default={})
ROOT = CONFIG_ROOT / 'devices/fpga'


def capability(pin):
    if pin not in PINS:
        raise ValueError('Unknown FPGA signal: ' + str(pin))
    if hasattr(physical, pin + '_counter_result'):
        return 'counter / stopwatch input'
    if hasattr(physical, pin + '_stopwatch_result'):
        return 'stopwatch input'
    return 'slow output' if pin.startswith(('jc_', 'jd_')) else 'fast output'


def compatible(experiment, role, pin):
    if pin not in PINS:
        return False
    original = DEFAULT_ROLES[role]
    if 'input' not in capability(original):
        if experiment=='ion_check' and role in ('AOMA','AOMB','AOMC'):
            return hasattr(physical,pin+'_out')
        if experiment == 'hom' and role == 'AOMB':
            return hasattr(physical, pin + '_out')
        # Preserve the reviewed number of port-write instructions and timing.
        return capability(pin) == capability(original)
    stopwatch = role == 'SYNC' or experiment in ('hom', 'decay', 'micromotion') or (experiment == 'entanglement' and role in ('PMTA', 'PMTC'))
    suffix = '_stopwatch_result' if stopwatch else '_counter_result'
    return hasattr(physical, pin + suffix)


def default_document(name='fpga_local'):
    aliases = {pin: next((role for role, p in DEFAULT_ROLES.items() if p == pin), pin.replace('_', '').upper()) for pin in PINS}
    return dict(schema_version=1, device_id=name, alias=name, pins=aliases, experiments={})


def validate(document):
    if not isinstance(document, dict) or document.get('schema_version') != 1:
        raise ValueError('Expected FPGA mapping schema_version 1')
    if set(document) - {'schema_version', 'device_id', 'alias', 'pins', 'experiments'}:
        raise ValueError('Unknown FPGA mapping fields')
    name = document.get('device_id')
    if not isinstance(name, str) or not name.isidentifier():
        raise ValueError('FPGA device_id must be an identifier')
    result = default_document(name)
    result['alias'] = document.get('alias', name)
    alias = result['alias']
    if not isinstance(alias, str) or not alias.strip() or alias != alias.strip() or any(c in alias for c in '<>:"/\\|?*') or alias.endswith('.') or len(alias) > 80:
        raise ValueError('Alias must be a nonempty folder name (maximum 80 characters)')
    if alias.split('.')[0].upper() in {'CON','PRN','AUX','NUL',*(f'COM{i}' for i in range(1,10)),*(f'LPT{i}' for i in range(1,10))}:
        raise ValueError('Reserved Windows folder name')
    pins = document.get('pins', {})
    if not isinstance(pins, dict) or set(pins) - set(PINS):
        raise ValueError('Unknown pin in FPGA configuration')
    result['pins'].update(pins)
    names = list(result['pins'].values())
    if any(not isinstance(n, str) or not n.isidentifier() or n.startswith('_') or n in PINS for n in names) or len(set(names)) != len(names):
        raise ValueError('Each pin needs a unique identifier name; physical pin IDs are reserved')
    experiments = document.get('experiments', {})
    if not isinstance(experiments, dict) or set(experiments) - set(EXPERIMENTS):
        raise ValueError('Unknown experiment mapping')
    for experiment, roles in experiments.items():
        if not isinstance(roles, dict) or set(roles) - set(DEFAULT_ROLES):
            raise ValueError('Unknown experiment role')
        for role, pin in roles.items():
            if not compatible(experiment, role, pin):
                raise ValueError(role + ' is incompatible with ' + str(pin))
        result['experiments'][experiment] = dict(roles)
    return result


class Profile:
    def __init__(self, document):
        self._document = validate(document)
        self.device_id = self._document['device_id']
        self.alias = self._document['alias']
        self._views = {}

    def document(self):
        return deepcopy(self._document)

    def view(self, experiment=None):
        if experiment not in self._views:
            names = {name: pin for pin, name in self._document['pins'].items()}
            if experiment is not None:
                # Legacy names are experiment roles, never required board aliases.
                names = dict(DEFAULT_ROLES)
                names.update(self._document['experiments'].get(experiment, {}))
                names.update({p.replace('_', '').upper(): p for p in PINS if p not in DEFAULT_ROLES.values()})
            values = {k: v for k, v in vars(physical).items() if not k.startswith('__')}
            values.update(__name__=legacy.__name__, __file__=legacy.__file__, C1_phase_shifter_port=2, C2_phase_shifter_port=3)
            inputs, outputs = {}, {}
            for name, pin in names.items():
                for key, value in vars(physical).items():
                    if key.startswith(pin + '_'):
                        values[name + key[len(pin):]] = value
                if hasattr(physical, pin + '_out'):
                    outputs[name] = pin
                else:
                    inputs[pin] = name
            values.update(input_mapping=inputs, output_mapping=outputs)
            self._views[experiment] = SimpleNamespace(**values)
        return self._views[experiment]


DEFAULT = Profile(default_document())


def profile_path(name):
    if not isinstance(name, str) or not name.isidentifier():
        raise ValueError('Invalid FPGA device ID')
    return ROOT / (name + '.local.json')


def load_profile(name):
    path = profile_path(name)
    profile = Profile(json.loads(path.read_text(encoding='utf-8-sig')) if path.exists() else default_document(name))
    if profile.device_id != name:
        raise ValueError('FPGA profile identity mismatch')
    return profile


def save_profile(profile):
    path = profile_path(profile.device_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    for other in ROOT.glob('*.local.json'):
        if other == path or other.name in ('ports.local.json', 'registry.local.json'):
            continue
        document = json.loads(other.read_text(encoding='utf-8-sig'))
        if isinstance(document, dict) and document.get('device_id') and str(document.get('alias', '')).casefold() == profile.alias.casefold():
            raise ValueError('FPGA alias already used by ' + document['device_id'])
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(profile.document(), ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temporary.replace(path)


@contextmanager
def scope(profile, experiment=None):
    token = CURRENT.set((profile, experiment))
    try:
        yield
    finally:
        CURRENT.reset(token)


@contextmanager
def profiles_scope(documents=None):
    profiles = {name: Profile(document) for name, document in (documents or {}).items()}
    if any(name != profile.device_id for name, profile in profiles.items()):
        raise ValueError('Workflow FPGA profile identity mismatch')
    token = FROZEN.set(profiles)
    try:
        yield
    finally:
        FROZEN.reset(token)


def profiles_from_bindings(bindings):
    documents = {}
    for family, bridge in bindings.values():
        if family == 'fpga':
            worker = getattr(bridge, 'worker', bridge)
            profile = getattr(worker, 'profile', None)
            if isinstance(profile, Profile):
                documents[profile.device_id] = profile.document()
    return documents


def snapshot():
    state = CURRENT.get()
    return None if state is None else dict(**state[0].document(), experiment=state[1])


def settings_path(path):
    """Keep first-device legacy settings; isolate subsequent device presets."""
    path = Path(path)
    state = CURRENT.get()
    if state is None or state[0].device_id == 'fpga_local' or not path.name.endswith('.local.json'):
        return path
    try:
        relative = path.relative_to(CONFIG_ROOT / 'operations')
    except ValueError:
        return path
    return ROOT / 'settings.local' / state[0].device_id / relative


def write_snapshot(folder):
    document = snapshot()
    if document is not None:
        path = Path(folder) / 'fpga_mapping.json'
        path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


class Hardware:
    def __setattr__(self, name, value):
        raise AttributeError('Hardware definitions are read-only; edit the device profile')

    def __getattr__(self, name):
        state = CURRENT.get()
        # Without a device context preserve the shipped public/default map.
        source = legacy if state is None else state[0].view(state[1])
        return getattr(source, name)


hd = Hardware()


class SignalMap(Mapping):
    def __init__(self, outputs):
        self.outputs = outputs

    def _values(self):
        if self.outputs:
            return {name: (pin, hd.external_slow_port if pin.startswith(('jc_', 'jd_')) else hd.external_control_port, getattr(hd, name + '_out')) for name, pin in hd.output_mapping.items()}
        return {getattr(hd, name + '_counter_result'): (name, pin) for pin, name in hd.input_mapping.items() if hasattr(hd, name + '_counter_result')}

    def __getitem__(self, name):
        if self.outputs and name in PINS and 'output' in capability(name):
            return (name, hd.external_slow_port if name.startswith(('jc_', 'jd_')) else hd.external_control_port, getattr(hd, name+'_out'))
        return self._values()[name]
    def __iter__(self): return iter(self._values())
    def __len__(self): return len(self._values())


class InputNames(Mapping):
    """Physical input IDs mapped to the active board's configured names."""
    def __getitem__(self, pin): return hd.input_mapping[pin]
    def __iter__(self): return iter(hd.input_mapping)
    def __len__(self): return len(hd.input_mapping)


OUTPUTS = SignalMap(True)
INPUTS = SignalMap(False)


def bound_methods(experiment=None, editor=False):
    """Explicit adapter for legacy Qt views/runners at their entry boundaries.

Each instance resolves its worker; no process-global hardware/module rewriting.
The same immutable profile is retained by a nested operation until it completes.
"""
    def decorate(cls):
        qt_class = any(base.__module__.startswith('PyQt5') for base in cls.__mro__)
        for name, function in list(vars(cls).items()):
            if not inspect.isfunction(function):
                continue
            parameters = tuple(inspect.signature(function).parameters.values())
            limit = None
            if qt_class and not any(p.kind == p.VAR_POSITIONAL for p in parameters):
                limit = sum(p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD) for p in parameters) - 1
            @wraps(function)
            def call(self, *args, __fn=function, __name=name, __limit=limit, **kwargs):
                if __limit is not None:
                    # Qt normally drops surplus signal arguments for a slot.
                    args = args[:__limit]
                if editor and __name=='start':
                    routing=self.__dict__.get('fpga_role_mapping')
                    if routing is not None and routing.dirty():
                        self.status.setText('변경한 핀 매핑을 저장한 뒤 실행하세요.')
                        return
                worker = self.__dict__.get('worker')
                if worker is None and __name == '__init__':
                    worker = kwargs.get('worker') or next((a for a in args if getattr(a, 'family', None) == 'fpga' and hasattr(a, 'profile')), None)
                profile = getattr(worker, 'profile', None)
                if profile is None:
                    return __fn(self, *args, **kwargs)
                if not qt_class:
                    profile = FROZEN.get().get(profile.device_id, profile)
                kind = self.__dict__.get('kind', 'ramsey') if experiment == 'pulse' else experiment
                if experiment == 'pulse' and __name == '__init__':
                    kind = inspect.signature(__fn).bind(self, *args, **kwargs).arguments.get('kind', kind)
                current = CURRENT.get()
                if not qt_class and current is not None and current[0].device_id == profile.device_id:
                    profile = current[0]
                with scope(profile, kind):
                    result = __fn(self, *args, **kwargs)
                    if editor and __name == '__init__':
                        from labremote.ui.fpga_mapping import RoleMapping
                        self.fpga_role_mapping = RoleMapping(worker, kind, self)
                        layout = self.layout()
                        if hasattr(layout, 'insertWidget'):
                            layout.insertWidget(0, self.fpga_role_mapping)
                        else:
                            layout.addWidget(self.fpga_role_mapping)
                    return result
            setattr(cls, name, call)
        return cls
    return decorate
