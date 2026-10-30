"""Registry validation and worker-owned I/O. Every acquire performs a get."""
from contextvars import ContextVar
from copy import deepcopy
from dataclasses import dataclass, field, replace
from fnmatch import fnmatchcase
import math
import inspect
from pathlib import Path
import threading
import time
import yaml

from labremote.runtime.ownership import CURRENT_OWNER, DEFAULT_MANAGER
from labremote.runtime.errors import ResourceBusy, UnexpectedReadback

REGISTRY_SNAPSHOT = ContextVar('registry_snapshot', default=None)


@dataclass(frozen=True)
class ParameterSpec:
    readable: bool = True
    writable: bool = False
    kind: str = 'any'
    nullable_readback: bool = False
    unit: str = ''
    minimum: float | None = None
    maximum: float | None = None
    choices: tuple = ()
    verification: str = 'none'
    abs_tolerance: float = 0.0
    rel_tolerance: float = 0.0
    period: float | None = None
    monitor: bool = True
    max_age_s: float = 60.0
    readback_delay_s: float = 0.0
    required_values: dict = field(default_factory=dict)
    unknown_readbacks: tuple = ()
    readback_aliases: dict = field(default_factory=dict)
    positive_readback: bool = False
    readback_parser: str = ''
    readback_path: str = ''

    def normalize_readback(self, value):
        if self.nullable_readback and (value is None or value in self.unknown_readbacks): return None
        if self.kind == 'osa_spectrum':
            if not isinstance(value,dict):raise ValueError('Expected OSA trace pair')
            arrays=[]
            for key in ('x','y'):
                raw=value.get(key)
                if not isinstance(raw,str) or len(raw)>8000000:raise ValueError('Invalid or oversized OSA trace')
                data=[float(token) for token in raw.split(',')]
                if not 2<=len(data)<=200000 or not all(math.isfinite(v) for v in data):raise ValueError('Invalid OSA trace samples')
                arrays.append(data)
            x,y=arrays
            if len(x)!=len(y) or any(v<=0 for v in x):raise ValueError('Invalid OSA wavelength or X/Y length mismatch')
            pairs=sorted((299792458./v/1e12,power) for v,power in zip(x,y))
            if not all(math.isfinite(v[0]) for v in pairs):raise ValueError('Invalid OSA frequency')
            return {'frequency_thz':[v[0] for v in pairs],'power_dbm':[v[1] for v in pairs]}
        if self.kind == 'fpga_measurement':
            if not isinstance(value,dict) or type(value.get('count')) is not int or value['count']<0:
                raise ValueError('Invalid FPGA count result')
            if type(value.get('channel')) is not int or not isinstance(value.get('ms'),(int,float)) or not math.isfinite(value['ms']) or value['ms']<=0:
                raise ValueError('Invalid FPGA exposure metadata')
            return value
        if self.kind == 'motor_status':
            if not isinstance(value,dict):raise ValueError('Invalid motor status')
            position=value.get('position')
            if position is not None and (isinstance(position,bool) or not isinstance(position,(int,float)) or not math.isfinite(position)):
                raise ValueError('Invalid motor position')
            return value
        if self.kind == 'thermotek_watchdog':
            from labremote.runtime.json_response import decode_object
            value=decode_object(value,context='Thermotek watchdog')
            if any(type(value.get(k)) is not bool for k in ('pump_running','device_alarm','device_warning')):
                raise ValueError('Invalid Thermotek watchdog flags')
            if type(value.get('controller_state')) is not int or not isinstance(value.get('controller_state_text'),str):
                raise ValueError('Invalid Thermotek controller state')
            return value
        if self.kind == 'mso7054_preamble':
            if not isinstance(value,str):raise ValueError('Expected MSO7054 preamble text')
            fields=[float(v) for v in value.strip().split(',')]
            if len(fields)!=10 or not all(math.isfinite(v) for v in fields):raise ValueError('Invalid MSO7054 preamble')
            if fields[0]!=0 or fields[2]<1 or fields[2]>50000 or fields[2]!=int(fields[2]) or fields[4]<=0 or fields[7]<=0:
                raise ValueError('Invalid MSO7054 BYTE waveform calibration')
            return fields
        if self.kind == 'mso7054_waveform':
            import base64,zlib
            if not isinstance(value,str) or len(value)>100000:raise ValueError('Expected bounded MSO7054 waveform')
            unpack=zlib.decompressobj();data=unpack.decompress(base64.b64decode(value,validate=True),50001)
            if not 0<len(data)<=50000 or unpack.unconsumed_tail or not unpack.eof or unpack.unused_data:
                raise ValueError('Oversized or incomplete MSO7054 waveform')
            return data
        if self.kind == 'ds1052e_waveform':
            import base64
            import zlib
            if not isinstance(value,str) or len(value)>4096:
                raise ValueError('Expected a bounded base64 DS1052E waveform')
            unpack=zlib.decompressobj()
            data=unpack.decompress(base64.b64decode(value,validate=True),611)
            if len(data)>610 or unpack.unconsumed_tail or not unpack.eof or unpack.unused_data:
                raise ValueError('Oversized or incomplete DS1052E waveform')
            if len(data)==610:
                if data[:10]!=b'#800000600':
                    raise ValueError('Invalid DS1052E waveform header')
                data=data[10:]
            if len(data)!=600:
                raise ValueError(f'Expected 600 screen samples; received {len(data)}')
            return data
        if self.readback_parser == 'token':
            if not isinstance(value,str) or not value.strip():
                raise ValueError(f'Expected nonempty response token, received {value!r}')
            value=value.strip().upper()
        elif self.readback_parser == 'number' and isinstance(value,str):
            value=float(value.strip())
        elif self.readback_parser == 'int' and isinstance(value,str):
            import re
            if not re.fullmatch(r'[+-]?[0-9]+',value.strip()):
                raise ValueError(f'Expected integer response, received {value!r}')
            value=int(value.strip())
        if self.readback_aliases and isinstance(value,(str,int,float,bool)):
            key=value.strip().upper() if isinstance(value,str) else value
            value=self.readback_aliases.get(key,value)
        if self.kind == 'scope_measurement':
            # DS1052E measurement queries return numeric strings, with 9.9e37 for unavailable.
            if isinstance(value,bool):raise ValueError('Expected numeric measurement, received bool')
            value = float(value)
            if not math.isfinite(value) or abs(value) >= 1e30: return None
        if self.kind == 'bool' and type(value) is int and value in (0, 1):
            value = bool(value)
        if self.kind == 'json_object':
            from labremote.runtime.json_response import decode_object
            value = decode_object(value, context='Parameter readback')
        self.validate(value)
        if self.positive_readback and value <= 0:
            raise ValueError(f'Expected positive scale, received {value!r}')
        return value

    def validate(self, value, *, request=False, expected=None):
        if value is None and not request and self.nullable_readback and expected is None:
            return
        if self.kind in ('number','scope_measurement'):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError(f'Expected finite number, received {value!r}')
        elif self.kind == 'bool' and type(value) is not bool:
            raise ValueError(f'Expected bool, received {value!r}')
        elif self.kind == 'int' and type(value) is not int:
            raise ValueError(f'Expected int, received {value!r}')
        elif self.kind == 'string' and not isinstance(value, str):
            raise ValueError(f'Expected string, received {value!r}')
        if self.kind == 'json_object':
            if not isinstance(value, dict): raise ValueError('Expected JSON object')
            for key, expected_value in self.required_values.items():
                if value.get(key) != expected_value:
                    raise ValueError(f'{key}: expected {expected_value!r}')
        if self.choices and value not in self.choices:
            raise ValueError(f'{value!r} not in {self.choices!r}')
        if request:
            if self.minimum is not None and value < self.minimum:
                raise ValueError(f'{value} below minimum {self.minimum}')
            if self.maximum is not None and value > self.maximum:
                raise ValueError(f'{value} exceeds maximum {self.maximum}')

        if expected is not None:
            self.validate(expected, request=request)
            if not self.matches(value, expected):
                raise UnexpectedReadback(f'Value {value!r} differs from expected {expected!r}')

    def matches(self, actual, expected):
        if self.kind == 'number':
            if self.period is not None:
                return abs((actual - expected + self.period / 2) % self.period - self.period / 2) <= self.abs_tolerance
            return math.isclose(actual, expected, abs_tol=self.abs_tolerance,
                                rel_tol=self.rel_tolerance)
        return actual == expected


class ParameterRegistry:
    def __init__(self, path):
        paths = (path,) if isinstance(path, (str, Path)) else tuple(path)
        document = {'parameters': []}
        from labremote.config.paths import read_yaml_document
        for policy_path in paths:
            policy = read_yaml_document(policy_path)
            if not isinstance(policy, dict) or policy.get('schema_version') != 1:
                raise ValueError('Registry requires schema_version: 1')
            document['parameters'].extend(policy['parameters'])
        self.rules = []
        for rule in document['parameters']:
            values = dict(rule)
            pattern = values.pop('pattern')
            values['choices'] = tuple(values.get('choices', ()))
            values['unknown_readbacks'] = tuple(values.get('unknown_readbacks', ()))
            spec = ParameterSpec(**values)
            if spec.readback_parser not in ('','token','number','int'):
                raise ValueError(f'{pattern}: unknown readback parser')
            if spec.verification not in ('none', 'readback'):
                raise ValueError(f'{pattern}: unknown verification mode')
            if spec.verification == 'readback' and not spec.readable and not spec.readback_path:
                raise ValueError(f'{pattern}: readback requires readable parameter')
            if min(spec.abs_tolerance, spec.rel_tolerance, spec.max_age_s, spec.readback_delay_s) < 0:
                raise ValueError(f'{pattern}: negative tolerance/age')
            if spec.period is not None and (not math.isfinite(spec.period) or spec.period <= 0):
                raise ValueError(f'{pattern}: invalid comparison period')
            if spec.minimum is not None and spec.maximum is not None and spec.minimum > spec.maximum:
                raise ValueError(f'{pattern}: inverted bounds')
            self.rules.append((pattern, spec))

    def get(self, family, path):
        key = f'{family}.{path}'
        for pattern, spec in reversed(self.rules):
            if fnmatchcase(key, pattern):
                return spec
        raise KeyError(f'Unregistered parameter: {key}')


@dataclass(frozen=True)
class Observation:
    requested: object = None
    observed: object = None
    last_valid: object = None
    observed_at: float = 0.0
    fresh_until: float = 0.0
    attempted_at: float = 0.0
    quality: str = 'unknown'
    verification: str = 'none'
    error: str | None = None
    source: str | None = None
    revision: int = 0


class ParameterLibrary:
    def __init__(self):
        self._lock = threading.RLock()
        self._values = {}
        self._listeners = []

    def read(self, key):
        with self._lock:
            return deepcopy(self._values.get(key, Observation()))

    def snapshot(self):
        with self._lock:
            return deepcopy(self._values)

    def subscribe(self, callback):
        with self._lock:
            self._listeners.append(callback)
        def unsubscribe():
            with self._lock:
                if callback in self._listeners:
                    self._listeners.remove(callback)
        return unsubscribe

    def update(self, key, **changes):
        with self._lock:
            old = self._values.get(key, Observation())
            state = replace(old, **deepcopy(changes), revision=old.revision + 1)
            self._values[key] = state
            listeners = tuple(self._listeners)
        for callback in listeners:
            # Observers must never turn a completed device write into a failure.
            try:
                callback(key, deepcopy(state))
            except Exception:
                import logging
                logging.getLogger(__name__).exception('Parameter observer failed')
        return state

    def invalidate(self, identity):
        for key in self.snapshot():
            if key[0] == identity:
                self.update(key, quality='unknown', error='Connection changed')


LIBRARY = ParameterLibrary()
_registry = None
_locks = {}
_locks_guard = threading.Lock()


def registry():
    snapshot = REGISTRY_SNAPSHOT.get()
    if snapshot is not None: return snapshot
    global _registry
    if _registry is None:
        from labremote.config.paths import registry_paths
        _registry = ParameterRegistry(registry_paths())
    return _registry


def check_cancelled():
    from labremote.runtime.jobs import CURRENT_JOB, ATOMIC_ASSIGN
    if ATOMIC_ASSIGN.get(): return
    job = CURRENT_JOB.get()
    if job is not None: job.check_cancelled()


def wait(seconds):
    if not math.isfinite(seconds) or seconds < 0:
        raise ValueError('Invalid wait interval')
    deadline = time.monotonic() + seconds
    while True:
        check_cancelled()
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        threading.Event().wait(min(remaining, .05))


class ManagedParameter:
    def __init__(self, target, identity, family, path, library=LIBRARY, spec=None, device=None):
        self.target, self.identity, self.family, self.path = target, identity, family, path
        self.device = device
        self.key = (identity, path)
        self.spec = spec or registry().get(family, path)
        if spec is None and family == 'windfreak' and path.endswith('power_dbm'):
            from labremote.config.device_config import load_rf_device_config, optional_number
            config = load_rf_device_config(family, identity[-1])
            cap = optional_number(config, 'channels', path.split('.')[0].removeprefix('channel_'),
                                  'limits', 'max_power_dbm')
            if cap is not None:
                self.spec = replace(self.spec, maximum=min(cap, self.spec.maximum) if self.spec.maximum is not None else cap)
        if spec is None and family == 'sg384' and path in ('bnc_power_dbm', 'n_power_dbm'):
            from labremote.config.device_config import load_rf_device_config, sg_power_cap_dbm
            cap = sg_power_cap_dbm(load_rf_device_config(family, identity[-1]), path.split('_')[0].upper())
            if cap is not None:
                self.spec = replace(self.spec, maximum=min(cap, self.spec.maximum))
        if spec is None and family=='keithley' and path.endswith(('.target_voltage','.target_current','.voltage_limit')):
            from labremote.config.device_config import load_rf_device_config,optional_number
            config=load_rf_device_config(family,identity[-1])
            key='max_current_a' if path.endswith('target_current') else 'max_voltage_v'
            cap=optional_number(config,'channels',path.split('.')[0].upper(),'limits',key)
            if cap is not None:self.spec=replace(self.spec,maximum=min(cap,self.spec.maximum))
        self.library = library
        self.thread_id = threading.get_ident()
        with _locks_guard:
            self.lock = _locks.setdefault(identity, threading.RLock())

    def _io(self, method, *args):
        from labremote.runtime.recording import record_io
        data = {'parameter': self.path, 'device': self.identity}
        if args: data['requested_value'] = args[0]
        record_io(method + '_requested', **data)
        try: value = getattr(self.target, method)(*args)
        except Exception as error:
            record_io(method + '_failed', **data, error_type=type(error).__name__, error=str(error))
            raise
        record_io(method + '_completed', **data, value=value)
        return value

    def _thread(self):
        if threading.get_ident() != self.thread_id:
            raise RuntimeError('Use the device WorkerBridge; parameter belongs to another thread')

    def _acquire(self):
        from labremote.runtime.jobs import CURRENT_JOB
        job = CURRENT_JOB.get()
        if job is not None: job.location = f'{self.identity} / {self.path} / get'
        self._thread()
        check_cancelled()
        if not self.spec.readable:
            raise ValueError(f'{self.path}: not readable')
        with self.lock:
            previous = self.library.read(self.key)
            now = time.monotonic()
            actual = None
            received = False
            try:
                actual = self._io('get')
                received = True
                actual = self.spec.normalize_readback(actual)
            except Exception as error:
                changes = dict(attempted_at=now, quality='invalid' if received else 'unknown', error=str(error))
                if received:
                    changes.update(observed=actual)
                self.library.update(self.key, **changes)
                raise
            from labremote.runtime.jobs import CURRENT_JOB
            job = CURRENT_JOB.get()
            from labremote.runtime.jobs import ATOMIC_ASSIGN
            verification = previous.verification if ATOMIC_ASSIGN.get() else 'observed'
            self.library.update(self.key, observed=actual, last_valid=actual,
                                observed_at=time.monotonic(), attempted_at=now, quality='valid',
                                fresh_until=time.monotonic() + self.spec.max_age_s,
                                error=None, verification=verification, source=getattr(job, 'request_id', 'acquire'))
            return actual

    def _assign(self, value):
        self._thread()
        check_cancelled()
        if not self.spec.writable:
            raise ValueError(f'{self.path}: not writable in registry')
        self.spec.validate(value, request=True)
        from labremote.runtime.jobs import CURRENT_JOB
        job=CURRENT_JOB.get()
        arguments=job.arguments if job is not None else {}
        if self.family=='motors' and self.path=='position' and arguments.get('readback_tolerance') is not None:
            tolerance=arguments['readback_tolerance']
            ParameterSpec(kind='number',minimum=0).validate(tolerance,request=True)
            self.spec=replace(self.spec,abs_tolerance=min(self.spec.abs_tolerance,tolerance))
        if self.family=='mdt' and self.device is not None and self.path.endswith('.voltage'):
            from labremote.config.device_config import load_device_config
            p=DeviceProxy(self.device,self.identity,self.family)
            axis=getattr(p,self.path.split('.')[0]);limits=load_device_config('mdt',self.identity[-1])['limits']
            lower=max(limits['min_voltage'],axis.minimum.acquire(),p.software_minimum.acquire())
            upper=min(limits['max_voltage'],axis.maximum.acquire(),p.software_maximum.acquire(),p.output_limit_v.acquire())
            ParameterSpec(kind='number',minimum=lower,maximum=upper).validate(value,request=True)
            guard=arguments.get('pid_guard')
            if guard is not None:
                for field in ('expected','max_delta','minimum','maximum'):ParameterSpec(kind='number').validate(guard[field],request=True)
                if guard['max_delta']<0:raise ValueError('Invalid PID step limit')
                if p.master_scan_enabled.acquire():raise ValueError('Master Scan enabled; PID voltage HOLD')
                actual=self.acquire()
                if abs(actual-guard['expected'])>.05:raise ValueError('Unexpected MDT voltage change; PID HOLD')
                ParameterSpec(kind='number',minimum=guard['minimum'],maximum=guard['maximum']).validate(value,request=True)
                if abs(value-actual)>guard['max_delta']+1e-6:raise ValueError('Actual PID voltage step/slew exceeds limit')
        if self.family=='fpga' and self.path=='channel':
            from labremote.devices.fpga.controller import INPUTS
            ParameterSpec(kind='int',choices=tuple(INPUTS)).validate(value,request=True)
        if self.family=='motors' and self.path=='position':
            from labremote.config.device_config import load_device_config
            limits=load_device_config('motors',self.identity[-1])['limits']
            ParameterSpec(kind='number',minimum=limits['min_position'],maximum=limits['max_position']).validate(value,request=True)
        if self.family=='thermotek' and self.device is not None and (self.path=='temperature_setpoint' or self.path=='run_request' and value is True):
            p=DeviceProxy(self.device,self.identity,self.family)
            if p.watchdog_json.acquire()['device_alarm']:raise ValueError('Chiller alarm present: write blocked')
        if self.family=='keithley' and self.device is not None and self.path.endswith('.output') and value is True:
            p=getattr(DeviceProxy(self.device,self.identity,self.family),self.path.split('.')[0])
            for parameter in (p.target_voltage,p.target_current):parameter.spec.validate(parameter.acquire(),request=True)
        if self.family == 'ds1052e' and self.device is not None and self.path == 'trigger_level':
            p = DeviceProxy(self.device,self.identity,self.family)
            source = p.trigger_source.acquire()
            scale = getattr(p,'ch'+source[-1]+'_scale').acquire()
            ParameterSpec(kind='number',minimum=-6*scale,maximum=6*scale).validate(value,request=True)
        if self.family == 'anapico' and self.path == 'output' and value is True:
            from labremote.config.device_config import load_rf_device_config, optional_number
            config = load_rf_device_config(self.family, self.identity[-1])
            cap = optional_number(config, 'output', 'max_allowed_power_dbm')
            expected = optional_number(config, 'output', 'expected_fixed_power_dbm')
            if cap is not None and (expected is None or expected > cap):
                raise ValueError('Fixed RF output power is unknown or above the configured maximum')
        if self.family == 'sg384' and self.device is not None:
            p = DeviceProxy(self.device, self.identity, self.family)
            from labremote.config.device_config import load_rf_device_config
            config = load_rf_device_config(self.family,self.identity[-1])
            bands = {port.lower(): (limits['frequency_min_hz'],limits['frequency_max_hz'])
                     for port in ('BNC','N') for limits in (config['outputs'][port]['limits'],)}
            if self.path == 'frequency':
                for prefix,(low,high) in bands.items():
                    if getattr(p, prefix+'_output').acquire():
                        ParameterSpec(kind='number',minimum=low,maximum=high).validate(value,request=True)
            elif self.path in ('bnc_output','n_output') and value is True:
                prefix=self.path.split('_')[0];low,high=bands[prefix]
                ParameterSpec(kind='number',minimum=low,maximum=high).validate(p.frequency.acquire(),request=True)
                power=getattr(p,prefix+'_power_dbm')
                power.spec.validate(power.acquire(),request=True)
        runner = CURRENT_OWNER.get()
        owner = DEFAULT_MANAGER.owner(self.identity)
        if owner is not None and owner is not runner:
            raise ResourceBusy('Device writes owned by another runner')
        local = None
        if owner is None:
            local = DEFAULT_MANAGER.acquire({self.identity})
        try:
            with self.lock:
                self.library.update(self.key, requested=value, verification='pending', quality='unknown',
                                    attempted_at=time.monotonic(), error=None)
                try:
                    from labremote.runtime.jobs import CURRENT_JOB
                    job = CURRENT_JOB.get()
                    if job is not None: job.location = f'{self.identity} / {self.path} / set'
                    if job is not None and job.write_guard is not None:job.write_guard()
                    self._io('set', value)
                    if self.spec.verification == 'none':
                        return self.library.update(self.key, verification='unverified')
                    # Verification is forced even inside a background context.
                    time.sleep(self.spec.readback_delay_s)
                    if self.spec.readback_path:
                        readback=DeviceProxy(self.device,self.identity,self.family)
                        for part in self.spec.readback_path.split('.'):readback=getattr(readback,part)
                        actual=readback.acquire()
                        state=self.library.read(readback.key)
                        self.library.update(self.key,observed=actual,last_valid=actual,observed_at=state.observed_at,quality='valid')
                    else:actual = self.acquire()
                    if not self.spec.matches(actual, value):
                        self.library.update(self.key, verification='mismatch')
                        raise UnexpectedReadback(f'{self.path}: readback {actual!r} != requested {value!r}')
                    return self.library.update(self.key, verification='verified')
                except Exception as error:
                    state = self.library.read(self.key)
                    self.library.update(self.key, error=str(error),
                                        quality=state.quality if state.verification == 'mismatch' else 'unknown',
                                        verification='mismatch' if state.verification == 'mismatch' else 'failed')
                    raise
        finally:
            if local: local.release()

    def acquire(self):
        try:
            return self._acquire()
        except Exception as error:
            error.args = (f'{self.identity} / {self.path} / acquire: {error}',)
            raise

    def assign(self, value):
        from labremote.runtime.jobs import assign_boundary
        check_cancelled()
        try:
            with assign_boundary():
                return self._assign(value)
        except Exception as error:
            self.library.update(self.key, error=str(error))
            error.args = (f'{self.identity} / {self.path} / assign: {error}',)
            raise

    def get(self):
        return self.acquire()

    def set(self, value):
        return self.assign(value)


class DeviceProxy:
    """Compatibility adapter: legacy get/set now use Acquire/Assign."""
    def __init__(self, target, identity, family, path='', root=None):
        self._target, self._identity, self._family, self._path = target, identity, family, path
        self._root = target if root is None else root
        self._children = {}

    def __getattr__(self, name):
        if name in self._children:
            return self._children[name]
        target = getattr(self._target, name)
        path = f'{self._path}.{name}'.strip('.')
        get = getattr(target, 'get', None)
        set_value = getattr(target, 'set', None)
        is_parameter = False
        for method, arguments in ((get, ()), (set_value, (0,))):
            method_name = 'get' if method is get else 'set'
            if not callable(method) or inspect.getattr_static(target, method_name, None) is None:
                continue
            try:
                # QCoDeS Instrument/Channel also expose get(name)/set(name,value).
                # Read-only/write-only QCoDeS Parameters expose just one method.
                inspect.signature(method).bind(*arguments)
            except TypeError:
                continue
            except ValueError:
                pass
            is_parameter = True
            break
        if is_parameter:
            child = ManagedParameter(target, self._identity, self._family, path, device=self._root)
        elif callable(target) or target is None or isinstance(target, (str, int, float, bool, dict, list, tuple)):
            return target
        else:
            child = DeviceProxy(target, self._identity, self._family, path, root=self._root)
        self._children[name] = child
        return child


def bind_device(worker, target, family, name, host=None, port=None):
    identity = getattr(worker, '_execution_device', None)
    if identity is None:
        from labremote.runtime.ownership import device_id
        if host is None or port is None:
            raise RuntimeError('Device endpoint required')
        identity = device_id(host, port, name)
    LIBRARY.invalidate(identity)
    return DeviceProxy(target, identity, family)
