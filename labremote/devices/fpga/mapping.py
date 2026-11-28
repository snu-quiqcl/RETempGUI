"""Per-device signal names and per-experiment roles for the v4_05 bitstream.

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

from labremote.configuration.paths import CONFIG_ROOT
from .vendor import HardwareDefinition_v4_05 as physical
from .vendor import HardwareDefinition_remote_ent_test_ec as legacy

PINS = tuple(f'{bank}_{n}' for bank in ('ja', 'jb', 'jc', 'jd') for n in range(8))
DEFAULT_ROLES = {**{name: pin for pin, name in legacy.input_mapping.items()}, **legacy.output_mapping}
# Input role names come from the sequencer vocabulary, not the board's UI
# nicknames. Both vocabularies occur in saved profiles; keep each saved route
# independent and leave absent routes unassigned rather than guessing a pin.
_INPUT_ROLES = tuple(dict.fromkeys((*legacy.input_mapping.values(),
                                    'JA4', 'JA6', 'UPMT1', 'UMPT2')))
ROLE_KINDS = {**dict.fromkeys(_INPUT_ROLES, 'input'),
              **dict.fromkeys(('TRIG','AOMC','EOM_7GC1','EOM_7GC2','EOM_2GC','AOMA','EOM_7GA1','EOM_7GA2','EOM_2GA'), 'fast output'),
              **dict.fromkeys(('AOMB','AOMM','CCD_EC','CCD_EA','MW_A','MW_C'), 'slow output')}
for _role in _INPUT_ROLES:
    DEFAULT_ROLES.setdefault(_role, None)
EXPERIMENTS = ('spin_echo', 'fluorescence', 'rabi', 'ramsey', 'spam', 'initialization', 'decay',
               'hom', 'entanglement', 'entanglement_no_mirror', 'ion_check', 'micromotion', 'phase_shifter')
CURRENT = ContextVar('fpga_mapping', default=None)
EDITING = ContextVar('fpga_settings_editor', default=False)

@contextmanager
def editing_settings(enabled=True):
    token = EDITING.set(enabled)
    try:
        yield
    finally:
        EDITING.reset(token)

FROZEN = ContextVar('fpga_workflow_profiles', default={})
ROOT = CONFIG_ROOT / 'devices/fpga'


def capability(pin):
    if pin is None:
        return 'unassigned'
    if pin not in PINS:
        raise ValueError('Unknown FPGA signal: ' + str(pin))
    if hasattr(physical, pin + '_counter_result'):
        return 'counter / stopwatch input' if hasattr(physical, pin + '_stopwatch_result') else 'counter input'
    if hasattr(physical, pin + '_stopwatch_result'):
        return 'stopwatch input'
    return 'slow output' if pin and pin.startswith(('jc_', 'jd_')) else 'fast output'


def compatible(experiment, role, pin):
    if pin is None:
        return True
    if pin not in PINS:
        return False
    required = ROLE_KINDS.get(role)
    if required is None:
        raise ValueError('Unknown sequencer role: ' + str(role))
    if required != 'input':
        if experiment == 'ion_check' and role in ('AOMA','AOMB','AOMC') or experiment == 'hom' and role == 'AOMB':
            return hasattr(physical, pin + '_out')
        return capability(pin) == required
    stopwatch = role == 'SYNC' or experiment in ('hom','decay','micromotion') or experiment in ('entanglement','entanglement_no_mirror') and role in ('PMTA','PMTC')
    suffix = '_stopwatch_result' if stopwatch else '_counter_result'
    return hasattr(physical, pin + suffix)


def default_document(name='fpga_local'):
    aliases = {pin: next((role for role, p in DEFAULT_ROLES.items() if p == pin), pin.replace('_', '').upper()) for pin in PINS}
    return dict(schema_version=2, device_id=name, alias=name, pins=aliases)


def validate(document):
    if not isinstance(document, dict) or document.get('schema_version') not in (1, 2):
        raise ValueError('Expected FPGA mapping schema_version 1 or 2')
    if set(document) - {'schema_version', 'device_id', 'alias', 'pins', 'experiments', 'role_bindings'}:
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
    bindings = deepcopy(document.get('role_bindings', {}))
    experiments = document.get('experiments', {})
    if not isinstance(experiments, dict) or set(experiments) - set(EXPERIMENTS):
        raise ValueError('Unknown experiment mapping')
    for experiment, roles in experiments.items():
        if not isinstance(roles, dict) or set(roles) - set(DEFAULT_ROLES):
            raise ValueError('Unknown experiment role')
        for role, pin in roles.items():
            if not compatible(experiment, role, pin):
                raise ValueError(role + ' is incompatible with ' + str(pin))
    if document.get('schema_version') == 1 or 'experiments' in document:
        for experiment in EXPERIMENTS:
            routes = experiments.get(experiment, {})
            bindings.setdefault(experiment, {role: result['pins'][pin] if pin else None
                                             for role, pin in routes.items()})
            for role, pin in experiments.get(experiment, {}).items():
                bindings[experiment][role] = result['pins'][pin] if pin else None
    if not isinstance(bindings, dict) or set(bindings) - set(EXPERIMENTS):
        raise ValueError('Unknown experiment mapping')
    for experiment in EXPERIMENTS:
        bindings.setdefault(experiment, {})
    for experiment, roles in bindings.items():
        if not isinstance(roles, dict) or set(roles) - set(DEFAULT_ROLES):
            raise ValueError('Unknown experiment role')
        for role, signal in roles.items():
            if signal is not None and (not isinstance(signal, str) or not signal.isidentifier()):
                raise ValueError('Experiment roles must reference common signal nicknames')
    result['role_bindings'] = bindings
    return result


class Profile:
    def __init__(self, document):
        self._document = validate(document)
        self.device_id = self._document['device_id']
        self.alias = self._document['alias']
        self._views = {}

    def document(self):
        return deepcopy(self._document)

    def board_document(self):
        return {k: v for k, v in self.document().items() if k != 'role_bindings'}

    def bindings(self, experiment):
        names = dict.fromkeys(DEFAULT_ROLES)
        names.update(self._document['role_bindings'].get(experiment, {}))
        return names

    def resolve(self, token, experiment=None):
        if token is None or token == '':
            return token
        if not isinstance(token,str):raise ValueError('Select a common FPGA signal nickname')
        if token in PINS:
            raise ValueError('Physical pin references are not experiment routes; select a common nickname: ' + token)
        if token.startswith('signal:'):
            token = token[7:]
        elif experiment is not None and token in DEFAULT_ROLES:
            token = self.bindings(experiment)[token]
            if token is None:
                return None
        pins = {name: pin for pin, name in self._document['pins'].items()}
        if token not in pins:
            raise ValueError('Unknown common FPGA signal: ' + str(token))
        return pins[token]

    def view(self, experiment=None):
        if experiment not in self._views:
            names = {name: pin for pin, name in self._document['pins'].items()}
            if experiment is not None:
                for role, signal in self.bindings(experiment).items():
                    names[role] = None if signal is None else next(
                        (p for p, n in self._document['pins'].items() if n == signal), 'missing')
            names.update({'signal:' + n: p for p, n in self._document['pins'].items()})
            values = {k: v for k, v in vars(physical).items() if not k.startswith('__') and not any(k.startswith(p + '_') for p in PINS)}
            values.update(__name__=legacy.__name__, __file__=legacy.__file__, C1_phase_shifter_port=2, C2_phase_shifter_port=3)
            inputs, outputs = {}, {}
            for name, pin in names.items():
                if pin == 'missing':
                    continue
                if pin is None:
                    continue
                for key, value in vars(physical).items():
                    if key.startswith(pin + '_'):
                        values[name + key[len(pin):]] = value
                if name.startswith('signal:'):
                    continue
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
    return ROOT / (name + '.json')


def load_profile(name):
    path = profile_path(name)
    document = json.loads(path.read_text(encoding='utf-8-sig')) if path.exists() else default_document(name)
    routes = role_settings_path(name)
    if document.get('schema_version') == 2 and routes.exists():
        document['role_bindings'] = json.loads(routes.read_text(encoding='utf-8-sig'))['role_bindings']
    profile = Profile(document)
    if profile.device_id != name:
        raise ValueError('FPGA profile identity mismatch')
    return profile


def role_settings_path(name):
    profile_path(name)
    return ROOT / 'settings' / name / 'role_bindings.json'


def save_profile(profile):
    path = profile_path(profile.device_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    for other in ROOT.glob('*.json'):
        if other == path or other.name in ('ports.json', 'registry.json'):
            continue
        document = json.loads(other.read_text(encoding='utf-8-sig'))
        if isinstance(document, dict) and document.get('device_id') and str(document.get('alias', '')).casefold() == profile.alias.casefold():
            raise ValueError('FPGA alias already used by ' + document['device_id'])
    document=profile.board_document()
    if path.exists() and not role_settings_path(profile.device_id).exists():
        original=json.loads(path.read_text(encoding='utf-8-sig'))
        if 'experiments' in original or 'role_bindings' in original:
            from labremote.configuration.settings_migration import backup_file
            backup_file(path)
            document['role_bindings']=profile.document()['role_bindings']
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(document, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
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
    """Canonical operation settings; previous locations are migration inputs only."""
    path=Path(path);state=CURRENT.get()
    if state is None or path.suffix!='.json':return path
    try:relative=path.relative_to(CONFIG_ROOT/'operations')
    except ValueError:return path
    if relative.parts[0]=='fpga':return path
    destination=CONFIG_ROOT/'operations/fpga'/state[0].device_id/relative
    if not destination.exists():
        old=ROOT/'settings'/state[0].device_id/relative
        source=old if old.exists() else path
        if source.exists():
            from labremote.configuration.experiment_settings import read,save
            from labremote.configuration.settings_migration import backup_file
            value=read(source)
            # Physical IDs from old direct routes retain exactly the same pin.
            def migrate(value,field=None):
                if isinstance(value,dict):return {k:migrate(v,k) for k,v in value.items()}
                if isinstance(value,list):return [migrate(v,field) for v in value]
                if isinstance(value,str) and value in PINS and field in ('PMT','AOM','MW','EOM_7G_1','EOM_7G_2','EOM_2G','trg_pin','pmt_pin','counter_pin','pmt'):
                    return signal_token(value)
                return value
            backup_file(source)
            save(destination,migrate(value),state[1],ui_state_imported=False)
    return destination


def write_snapshot(folder):
    from labremote.runtime.queue_archive import active
    if active():return
    document = snapshot()
    if document is not None:
        path = Path(folder) / 'fpga_mapping.json'
        path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


class Hardware:
    def __setattr__(self, name, value):
        raise AttributeError('Hardware definitions are read-only; edit the device profile')

    def __getattr__(self, name):
        state = CURRENT.get()
        if state and state[1] is not None and name.endswith('_out') and name[:-4] in DEFAULT_ROLES:
            role = name[:-4]
            if not compatible(state[1], role, state[0].resolve(role, state[1])):
                raise AttributeError(role + ': common signal has incompatible output timing/port')
        # Catalog metadata is available without a device; addresses are not.
        if state is None and name in ('input_mapping', 'output_mapping'):
            return {}
        if state is None and any(name.endswith('_' + suffix) for suffix in ('out', 'counter_result', 'counter_reset', 'counter_enable', 'stopwatch_result', 'stopwatch_reset', 'stopwatch_start', 'stopwatch_stopped_TLI')):
            raise AttributeError('Select an FPGA and map its common signal nickname: ' + name)
        source = DEFAULT.view() if state is None else state[0].view(state[1])
        if state and state[1] is not None:
            for role in DEFAULT_ROLES:
                if name.startswith(role + '_') and state[0].resolve(role, state[1]) is None:
                    raise AttributeError(role + ': common signal nickname is unassigned in this experiment')
        return getattr(source, name)


hd = Hardware()


class SignalMap(Mapping):
    def __init__(self, outputs):
        self.outputs = outputs

    def _values(self):
        if CURRENT.get() is None:return {}
        if self.outputs:
            return {name: (pin, hd.external_slow_port if pin and pin.startswith(('jc_', 'jd_')) else hd.external_control_port, getattr(hd, name + '_out')) for name, pin in hd.output_mapping.items()}
        return {getattr(hd, name + '_counter_result'): (name, pin) for pin, name in hd.input_mapping.items() if hasattr(hd, name + '_counter_result')}

    def __getitem__(self, name):
        state = CURRENT.get()
        if state is None:raise ValueError('Select an FPGA before resolving hardware addresses')
        if self.outputs and state and state[1] is not None and name in DEFAULT_ROLES:
            if not compatible(state[1], name, state[0].resolve(name, state[1])):
                raise ValueError(name + ': common signal has incompatible output timing/port')
        if self.outputs and isinstance(name, str) and name.startswith('signal:'):
            state = CURRENT.get()
            pin = (state[0] if state else DEFAULT).resolve(name)
            return (pin, physical.external_slow_port if pin.startswith(('jc_', 'jd_')) else physical.external_control_port, getattr(physical, pin + '_out'))
        if self.outputs and name in PINS:
            raise ValueError('Select a common signal nickname, not a physical pin: ' + name)
        if self.outputs:
            if not isinstance(name,str):raise ValueError('Select a common output nickname')
            pin = resolve_signal(name)
            if not pin or not hasattr(physical,pin+'_out'):
                raise ValueError(str(name) + ': output nickname is unassigned or incompatible')
            return pin, physical.external_slow_port if pin.startswith(('jc_', 'jd_')) else physical.external_control_port, getattr(physical,pin+'_out')
        return self._values()[name]
    def __iter__(self): return iter(self._values())
    def __len__(self): return len(self._values())


class InputNames(Mapping):
    """Physical input IDs mapped to the active board's configured names."""
    def __getitem__(self, token):
        state = CURRENT.get()
        profile = state[0] if state else DEFAULT
        pin = token if token in PINS else profile.resolve(token, state[1] if state else None)
        return profile.document()['pins'][pin]
    def __iter__(self): return iter(hd.input_mapping)
    def __len__(self): return len(hd.input_mapping)


OUTPUTS = SignalMap(True)
INPUTS = SignalMap(False)


def signal_token(pin):
    """Persist a common signal reference, independently of sequencer role names."""
    state = CURRENT.get()
    profile = state[0] if state else DEFAULT
    return 'signal:' + profile.document()['pins'][pin] if pin in PINS else pin


def role_signal_token(role, experiment):
    state = CURRENT.get()
    name = (state[0] if state else DEFAULT).bindings(experiment).get(role)
    return 'signal:' + name if name else None


def resolve_signal(token):
    state = CURRENT.get()
    return (state[0] if state else DEFAULT).resolve(token, state[1] if state else None)


class RouteChoices:
    """Legacy roles plus explicit common signals; validate actual pin capabilities."""
    def __init__(self, legacy, feature):
        self.legacy, self.feature = tuple(legacy), feature

    def __iter__(self):
        return iter(self.legacy)

    def __contains__(self, token):
        if EDITING.get():
            return token is None or token == '' or isinstance(token, str) and token not in PINS
        try:
            pin = resolve_signal(token)
            if pin is None:
                return False
            kind = capability(pin)
            return kind == 'fast output' if self.feature == 'fast' else self.feature in kind
        except (ValueError, TypeError, AttributeError):
            return False


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
                worker = self.__dict__.get('worker')
                if worker is None and __name == '__init__':
                    worker = kwargs.get('worker') or next((a for a in args if getattr(a, 'family', None) == 'fpga' and hasattr(a, 'profile')), None)
                profile = getattr(worker, 'profile', None)
                if profile is None:
                    return __fn(self, *args, **kwargs)
                if not qt_class:
                    profile = FROZEN.get().get(profile.device_id, profile)
                kind = self.__dict__.get('kind', 'ramsey') if experiment == 'pulse' else getattr(type(self),'mapping_experiment',experiment)
                if experiment == 'pulse' and __name == '__init__':
                    kind = inspect.signature(__fn).bind(self, *args, **kwargs).arguments.get('kind', kind)
                current = CURRENT.get()
                if not qt_class and current is not None and current[0].device_id == profile.device_id:
                    profile = current[0]
                if not qt_class and kind in ('entanglement','entanglement_no_mirror','ion_check'):
                    from .routing import settings_profile
                    c=kwargs.get('settings') or getattr(self,'settings',{}).get('settings')
                    profile=settings_profile(profile,kind,c)
                with scope(profile, kind), editing_settings(qt_class and __name not in ('start', 'begin', 'validate_sequence', 'run_sequence')):
                    result = __fn(self, *args, **kwargs)
                    if qt_class and __name=='__init__' and type(self) is cls:
                        from labremote.ui.mapping_persistence import bind
                        bind(self)
                    return result
            setattr(cls, name, call)
        return cls
    return decorate
