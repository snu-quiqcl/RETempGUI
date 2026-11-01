"""Server-owned instrument discovery and local UI capability matching.

InstrumentServer's Blueprint is authoritative about remote capabilities.  The
client has a UI registry, but no hardware serial ports or drivers are loaded.
"""
from __future__ import annotations

from dataclasses import dataclass
import queue
import threading
from PyQt5 import QtCore
from labremote.runtime.network import configure_client_timeout


@dataclass(frozen=True)
class DeviceDescriptor:
    name: str
    family: str
    driver_class: str
    detail: str = ''


REQUIRED_WINDFREAK_METHODS = frozenset({
    'get_device_info', 'read_snapshot', 'get_reference_status',
    'configure_external_reference',
})
REQUIRED_WINDFREAK_SUBMODULES = frozenset({'channel_A', 'channel_B'})


def identify_family(driver_class, name='', *, methods=(), submodules=()):
    typ = str(driver_class).lower().replace('_', '')
    if (REQUIRED_WINDFREAK_METHODS <= set(methods) and REQUIRED_WINDFREAK_SUBMODULES <= set(submodules)) or ('windfreak' in typ and 'synthhd' in typ):
        return 'windfreak_synthhd'
    if 'mff101' in typ or 'mff002' in typ:return 'thorlabs_mff'
    if 'aq6373' in typ:return 'yokogawa_aq6373'
    if 'mdt693b' in typ:return 'mdt693b'
    if 'ds1052e' in typ: return 'rigol_ds1052e'
    if 'mso7054' in typ:return 'rigol_mso7054'
    if 'thermotek' in typ or 't257p' in typ:return 'thermotek_t257p'
    if 'keithley' in typ and ('2231' in typ or '2230' in typ):return 'keithley_2231a'
    if 'sg384' in typ: return 'srs_sg384'
    if 'apsyn420' in typ: return 'anapico_apsyn420'
    if 'ad9912vva4' in typ: return 'dds4_ad9912_vva'
    return 'unknown'


def plan_dynamic_tabs(devices: list[DeviceDescriptor], existing: set[str]) -> list[DeviceDescriptor]:
    return [d for d in devices if d.family in ('windfreak_synthhd','srs_sg384','anapico_apsyn420','dds4_ad9912_vva','rigol_ds1052e','rigol_mso7054','thermotek_t257p','keithley_2231a','yokogawa_aq6373','mdt693b') and d.name not in existing]


class DiscoveryWorker(QtCore.QThread):
    devices_found = QtCore.pyqtSignal(object)
    failure = QtCore.pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._queue = queue.Queue()
        self._stop = threading.Event()

    def scan(self, host: str, port: int):
        self._queue.put(('SCAN', host, int(port)))

    def shutdown(self):
        self._stop.set()
        self._queue.put(('EXIT', '', 0))

    def run(self):
        while not self._stop.is_set():
            try:
                cmd, host, port = self._queue.get(timeout=0.2)
            except queue.Empty:
                continue
            if cmd == 'EXIT':
                break
            cli = None
            try:
                from labremote.runtime.transport import Client
                # Client constructor timeout is milliseconds, including during connect().
                cli = Client(host=host, port=port, timeout=12000)
                configure_client_timeout(cli, 12)
                names = cli.list_instruments()
                if isinstance(names, dict):
                    name_to_class = {str(k): str(v or '') for k, v in names.items()}
                else:
                    name_to_class = {str(k): '' for k in names}

                descriptors = []
                for name, reported_type in name_to_class.items():
                    driver_type = reported_type
                    detail = ''
                    methods, modules = (), ()
                    try:
                        bp = cli.getBluePrint(name)
                        driver_type = str(getattr(bp, 'instrument_module_class', '') or reported_type)
                        methods = tuple((getattr(bp, 'methods', None) or {}).keys())
                        modules = tuple((getattr(bp, 'submodules', None) or {}).keys())
                        if 'windfreak' in driver_type.lower() or name.lower().startswith('synthhd'):
                            detail = f'Blueprint methods={sorted(methods)}; submodules={sorted(modules)}'
                    except Exception as exc:
                        detail = f'Blueprint unavailable: {type(exc).__name__}: {exc}'
                    family = identify_family(driver_type, name, methods=methods, submodules=modules)
                    descriptors.append(DeviceDescriptor(name, family, driver_type, detail))
                self.devices_found.emit(descriptors)
            except Exception as exc:
                self.failure.emit(f'{type(exc).__name__}: {exc}')
            finally:
                if cli is not None:
                    try:
                        cli.disconnect()
                    except Exception:
                        pass
