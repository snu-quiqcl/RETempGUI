from copy import deepcopy
from PyQt5 import QtCore
from labremote.runtime.parameters import LIBRARY
from labremote.devices.windfreak.monitor import empty_snapshot, FLAGS


def current_snapshot(identity, previous=None):
    """Project one atomic library snapshot, never a queued observation payload."""
    data = deepcopy(previous) if previous is not None else empty_snapshot()
    states = {path: state for (device, path), state in LIBRARY.snapshot().items() if device == identity}
    metadata = data.setdefault('_parameter_states', {})
    for path, state in states.items():
        metadata[path] = dict(quality=state.quality, verification=state.verification, error=state.error)
        # Keep a previously valid value on failures, with its uncertainty marker.
        value = state.observed if state.quality == 'valid' else state.last_valid
        if value is None and state.quality != 'valid': continue
        if path.startswith('channel_'):
            channel, field = path.split('.', 1)
            if channel[-1] not in data['channels']: continue
            data['channels'][channel[-1]][field] = value
            if field == 'pll_lock': data['reference']['pll_lock'][channel[-1]] = value
        elif path.startswith('reference_'): data['reference'][path] = value
        elif path == 'device_info_json': data['device_info'] = value
    sources = data.setdefault('_output_sources', {})
    def valid(state):
        return state is not None and state.quality == 'valid' and state.verification not in ('failed', 'mismatch', 'pending')
    def timestamp(state):
        return max(state.observed_at, state.attempted_at) if state is not None else 0
    for channel in 'AB':
        prefix = 'channel_' + channel + '.'
        output = states.get(prefix + 'output_enabled')
        flags = [states.get(prefix + flag) for flag in FLAGS]
        if output is None and all(flag is None for flag in flags): continue
        if valid(output) and output.observed_at >= max(timestamp(flag) for flag in flags):
            value = output.observed
            sources[channel] = [prefix + 'output_enabled']
        elif all(valid(flag) and flag.observed_at > timestamp(output) for flag in flags):
            value = all(flag.observed for flag in flags)
            sources[channel] = [prefix + flag for flag in FLAGS]
        else:
            # A new individual flag cannot make older flags contemporaneous
            # with a newer aggregate output read. Wait for a complete observation.
            value = None
            sources[channel] = [prefix + 'output_enabled', *(prefix + flag for flag in FLAGS)]
        data['channels'][channel]['output_enabled'] = value
    ref = data['reference']
    ref['configuration_matches_external'] = (ref['reference_mode'] == 'external'
        and ref['reference_frequency_hz'] is not None and 10e6 <= ref['reference_frequency_hz'] <= 100e6)
    return data


class LibraryUpdates(QtCore.QObject):
    changed = QtCore.pyqtSignal(object, object)
    def __init__(self, worker):
        super().__init__(worker)
        self.worker = worker
        self.changed.connect(self.apply, QtCore.Qt.QueuedConnection)
        self.unsubscribe = LIBRARY.subscribe(lambda key, state: self.changed.emit(key, state))
        worker.destroyed.connect(self.unsubscribe)

    def apply(self, key, state):
        w = self.worker
        if key[0] != w._execution_device: return
        with w._lock:
            if w.ps is None and w._snapshot is None: return
            if w.family == 'windfreak':
                data = current_snapshot(key[0], w._snapshot)
            else:
                states = {path: value for (device, path), value in LIBRARY.snapshot().items() if device == key[0]}
                data = {path: value.observed if value.quality == 'valid' else value.last_valid
                        for path, value in states.items()}
                data['_parameter_states'] = {path: dict(quality=value.quality,
                    verification=value.verification, error=value.error) for path,value in states.items()}
            w._snapshot = deepcopy(data)
        data['_library_generated'] = True
        w.snapshot.emit(data, 'LIBRARY')
