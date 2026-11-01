"""Windfreak tab: InstrumentServer client component."""
from __future__ import annotations
from labremote.api.devices import device_api

import math
import time
from labremote.ui.widgets.readback_inputs import add_readback_button
from PyQt5 import QtCore, QtWidgets
from labremote.ui.widgets.step_control import StepControl, FREQUENCY_SCALES, FREQUENCY_DECIMALS
from labremote.ui.widgets.rf_layout import align_rf_grid, value_with_unit
from labremote.devices.windfreak.worker import WindfreakWorker
from labremote.config.device_config import load_rf_device_config, optional_number

RF_INACTIVE_STYLE = '''QPushButton {background-color:#42464d; color:#d1d5db; border-color:#60656e;}
QPushButton:hover {background-color:#535860; border-color:#818791;}
QPushButton:disabled {background-color:#30343a; color:#858b94; border-color:#474c54;}'''


class WindfreakTab(QtWidgets.QWidget):
    log_message = QtCore.pyqtSignal(str)
    channel_names_changed = QtCore.pyqtSignal(object)
    def __init__(self, name: str, host: str, port: int, parent=None, *, channel_names=None):
        super().__init__(parent)
        self.channel_names = dict(channel_names or {})
        self.device_name, self.host, self.port = name, host, int(port)
        self.rf_config = load_rf_device_config('windfreak', name)
        self._power_caps = {}
        self._presets = {}
        for ch in 'AB':
            channel_cfg = self.rf_config.get('channels', {}).get(ch, {})
            preset = channel_cfg.get('preset', {})
            self._presets[ch] = {
                'frequency_hz': optional_number(preset, 'frequency_hz'),
                'power_dbm': optional_number(preset, 'power_dbm'),
                'phase_step_deg': optional_number(preset, 'phase_step_deg'),
            }
            cap = optional_number(channel_cfg.get('limits', {}), 'max_power_dbm')
            if cap is not None and not -60 <= cap <= 20:
                raise ValueError(f'{name}/CH{ch}: maximum power must be within -60..20 dBm')
            self._power_caps[ch] = cap
            target = self._presets[ch]['power_dbm']
            if target is not None and cap is not None and target > cap + 1e-9:
                raise ValueError(f'{name}/CH{ch}: preset power {target} exceeds cap {cap}')
        self.worker = WindfreakWorker()
        self.worker.connected.connect(self._on_connected)
        self.worker.disconnected.connect(self._on_disconnected)
        self.worker.snapshot.connect(self._on_snapshot)
        self.worker.completed.connect(lambda action: self.log_message.emit(f'[Windfreak {self.device_name}] {action}: command/readback completed'))
        self.worker.failure.connect(self._on_error)
        self.worker.ramp_active.connect(self._on_ramp_active)
        self.worker.reference_warning.connect(self._reference_warning)
        self.worker.busy_changed.connect(self._runner_busy)
        self.worker.handle_changed.connect(lambda handle: self._runner_busy(None))
        self.worker.completed.connect(self._completed)
        self.connected = False
        self.busy = False
        self.ramping = False
        self.latest = {}
        self.last_snapshot_time = 0.0  # monotonic; invalidated on every read error
        self.rows = {}
        self._build()
        reference = self.rf_config['reference']
        if reference['source'] == 'external':
            self.ref_target.setValue(reference['frequency_hz'] / 1e6)
        self.reference_default.setText(f"Default: {reference['source']} {reference['frequency_hz']/1e6:g} MHz (not applied)")
        self.ramp_dwell.setValue(self.rf_config['rf_operation']['interval_s'])
        self.worker.start()

    def _reference_warning(self, message):
        self.reference_warning_label.setText(message)
        self.log_message.emit(f'[Windfreak {self.device_name}] WARNING: {message}')

    def _rename_channel(self, ch):
        alias = self.rows[ch]['alias'].text().strip()
        self.channel_names[ch] = alias
        self.rows[ch]['card'].setTitle(alias or f'Channel {ch}')
        self.channel_names_changed.emit(dict(self.channel_names))

    def _build(self):
        base = QtWidgets.QVBoxLayout(self)
        self.windfreak_load_inputs_button = add_readback_button(
            self, base, '_load_inputs_requested', lambda: self.connected and not self.busy, lambda: self._queue('REFRESH'))
        title = QtWidgets.QGroupBox(f'Windfreak SynthHD — registered instrument: {self.device_name}')
        g = QtWidgets.QGridLayout(title)
        self.connect_btn = QtWidgets.QPushButton('Connect')
        self.disconnect_btn = QtWidgets.QPushButton('Disconnect')
        self.refresh_btn = QtWidgets.QPushButton('Refresh now')
        self.status = QtWidgets.QLabel('Not connected. The server owns all USB connections.')
        self.device_id = QtWidgets.QLabel('Model: — | S/N: — | Server USB: —')
        self.device_id.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        device_label = QtWidgets.QLabel(f'Device: {self.device_name}')
        device_label.setWordWrap(True)
        g.addWidget(device_label, 0, 0)
        for i, w in enumerate((self.connect_btn, self.disconnect_btn, self.refresh_btn), 1):
            w.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)
            g.addWidget(w, 0, i)
        g.setColumnStretch(4, 1)
        g.addWidget(QtWidgets.QLabel('Auto readback: every 60 s while connected'), 1, 0, 1, 5)
        self.device_id.setWordWrap(True)
        self.status.setWordWrap(True)
        g.addWidget(self.device_id, 2, 0, 1, 5)
        g.addWidget(self.status, 3, 0, 1, 5)
        base.addWidget(title)
        self.reference_warning_label = QtWidgets.QLabel('')
        self.reference_warning_label.setWordWrap(True)
        self.reference_warning_label.setStyleSheet('color: #f3c46b; font-weight: bold;')
        base.addWidget(self.reference_warning_label)

        ref = QtWidgets.QGroupBox('Reference clock')
        rr = QtWidgets.QGridLayout(ref)
        self.ref_mode = QtWidgets.QLabel('Reference mode: —')
        self.ref_frequency = QtWidgets.QLabel('Reference setting: — MHz')
        self.pll_state = QtWidgets.QLabel('PLL A / B: — / — (advisory only)')
        self.ext_verified = QtWidgets.QLabel('Physical external reference lock: NOT VERIFIED')
        self.ext_verified.setStyleSheet('color:#f3c46b;font-weight:600;')
        self.ref_target = QtWidgets.QDoubleSpinBox()
        self.ref_target.setRange(10, 100)
        self.ref_target.setDecimals(6)
        self.ref_target.setSingleStep(0.1)
        self.ref_target.setValue(10)
        self.set_external_btn = QtWidgets.QPushButton('Reference Lock')
        self.set_external_btn.setToolTip('Apply external reference mode and frequency; physical lock is not verified.')
        self.internal10_btn = QtWidgets.QPushButton('10 MHz')
        self.internal27_btn = QtWidgets.QPushButton('27 MHz')
        self.reference_default = QtWidgets.QLabel()
        rr.addWidget(self.reference_default, 5, 0, 1, 4)
        rr.addWidget(self.ref_mode, 0, 0, 1, 2)
        rr.addWidget(self.ref_frequency, 0, 2, 1, 2)
        rr.addWidget(self.pll_state, 1, 0, 1, 4)
        rr.addWidget(self.ext_verified, 2, 0, 1, 4)
        rr.addWidget(QtWidgets.QLabel('External reference'), 3, 0)
        self.ref_units=QtWidgets.QComboBox();self.ref_units.addItems(['GHz','MHz','kHz','Hz']);self.ref_units.setCurrentText('MHz')
        self.ref_scale=1e6
        self.ref_units.currentTextChanged.connect(self._reference_unit)
        rr.addWidget(value_with_unit(self.ref_target,self.ref_units), 3, 1)
        rr.addWidget(self.set_external_btn, 3, 2, 1, 2)
        rr.addWidget(QtWidgets.QLabel('Internal reference'), 4, 0)
        rr.addWidget(self.internal10_btn, 4, 1)
        rr.addWidget(self.internal27_btn, 4, 2)
        for label in (self.ref_mode, self.ref_frequency, self.pll_state, self.ext_verified):
            label.setWordWrap(True)
        for button in (self.set_external_btn, self.internal10_btn, self.internal27_btn):
            button.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)
        self.ref_target.setMaximumWidth(150)
        rr.setColumnStretch(4, 1)

        ramp_row = QtWidgets.QGridLayout()
        ramp_row.addWidget(QtWidgets.QLabel('RF power change: max 0.1 Vpp per step (50 Ω sine)'), 0, 0, 1, 4)
        ramp_row.addWidget(QtWidgets.QLabel('Dwell (s)'), 1, 0)
        self.ramp_dwell = QtWidgets.QDoubleSpinBox()
        self.ramp_dwell.setRange(0.0, 1e6)
        self.ramp_dwell.setDecimals(2)
        self.ramp_dwell.setSingleStep(0.1)
        self.ramp_dwell.setMaximumWidth(100)
        ramp_row.addWidget(self.ramp_dwell, 1, 1)
        self.stop_ramp_btn = QtWidgets.QPushButton('STOP POWER RAMP')
        self.stop_ramp_btn.setToolTip(
            'Stops further setpoint changes after the current network command; '
            'holds the last power setting. This is not an RF output OFF switch.')
        self.stop_ramp_btn.clicked.connect(self._stop_power_ramp)
        self.stop_ramp_btn.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)
        ramp_row.addWidget(self.stop_ramp_btn, 1, 2)
        self.ramp_label = QtWidgets.QLabel('Power ramp idle')
        self.ramp_label.setWordWrap(True)
        ramp_row.addWidget(self.ramp_label, 2, 0, 1, 4)
        ramp_row.setColumnStretch(3, 1)


        for ch in 'AB':
            group = QtWidgets.QGroupBox(self.channel_names.get(ch) or f'Channel {ch}')
            gg = QtWidgets.QGridLayout(group)
            fields = {}
            for j, (key, title, lo, hi, step, dec) in enumerate((
                ('frequency_hz','Frequency', 53, 13600, 1, 6),
                ('power_dbm','Power', -60, 20, .1, 3),
                ('phase_deg','Relative phase step (deg)', 0, 360, 1, 3),
            )):
                w = QtWidgets.QDoubleSpinBox()
                if key == 'power_dbm' and self._power_caps[ch] is not None:
                    # Never round a configured cap UP to the 0.001-dBm UI precision.
                    hi = min(hi, math.floor(self._power_caps[ch] * 1000) / 1000)
                w.setDecimals(dec); w.setRange(lo, hi); w.setSingleStep(step)
                w.setToolTip('Device preset/limit: labremote/config/devices/windfreak/device_config.yml')
                preset_name = 'phase_step_deg' if key == 'phase_deg' else key
                configured = self._presets[ch][preset_name]
                if configured is not None:
                    preset_value = configured / 1e6 if key == 'frequency_hz' else configured
                    if not w.minimum() <= preset_value <= w.maximum():
                        raise ValueError(f'{self.device_name}/CH{ch}: {key} preset is out of range')
                    w.setValue(preset_value)
                w.setKeyboardTracking(False)
                set_btn = QtWidgets.QPushButton('Set')
                w.setMinimumWidth(130)
                w.setMaximumWidth(170)
                set_btn.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)
                gg.addWidget(QtWidgets.QLabel(title), j, 0)
                unit=QtWidgets.QLabel(('MHz','dBm','deg')[j])
                if key=='frequency_hz':
                    unit=QtWidgets.QComboBox();unit.addItems(['GHz','MHz','kHz','Hz']);unit.setCurrentText('MHz')
                    fields['frequency_units']=unit;fields['frequency_scale']=1e6
                    unit.currentTextChanged.connect(lambda u,c=ch:self._frequency_unit(c,u))
                gg.addWidget(value_with_unit(w,unit), j, 2)
                gg.addWidget(set_btn, j, 4)
                set_btn.clicked.connect(lambda _, c=ch, k=key, widget=w: self._set_value(c, k, widget))
                fields[key + '_step'] = StepControl(w, ('MHz', 'dBm', 'deg')[j])
                if key=='frequency_hz':fields[key+'_step'].enable_frequency_units(['GHz','MHz','kHz','Hz'])
                fields[key + '_step'].edit.setMinimumWidth(65)
                fields[key + '_step'].edit.setMaximumWidth(150)
                gg.addWidget(fields[key + '_step'], j, 3)
                fields[key] = w
                fields[key+'_button'] = set_btn
            for row_index, key, placeholder in ((0, 'freq_read', '— MHz'),
                                                (1, 'power_read', '— dBm'),
                                                (2, 'phase_read', 'Unknown (last cmd)')):
                readback = QtWidgets.QLabel(placeholder)
                readback.setWordWrap(True)
                readback.setMaximumWidth(145)
                readback.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
                gg.addWidget(readback, row_index, 1)
                fields[key] = readback
            fields['phase_read'].setToolTip('Last commanded relative phase increment; not an absolute phase measurement.')
            output = QtWidgets.QLabel('Output: UNKNOWN')
            off = QtWidgets.QPushButton('Ramp OFF')
            on = QtWidgets.QPushButton('RF ON (confirm)')
            output_row = QtWidgets.QHBoxLayout()
            output_row.addWidget(output)
            output_row.addWidget(off)
            output_row.addWidget(on)
            output_row.addStretch(1)
            for button in (off, on):
                button.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)
            gg.addLayout(output_row, 3, 0, 1, 6)
            gg.setColumnStretch(5, 1)
            off.clicked.connect(lambda _, c=ch: self._set_output(c, False))
            on.clicked.connect(lambda _, c=ch: self._set_output(c, True))
            cap = self._power_caps[ch]
            cap_note = QtWidgets.QLabel(
                f'Experimental RF max: {cap:.3f} dBm (assign enforced)' if cap is not None
                else 'Experimental RF max: NOT CONFIGURED (device limits only)')
            cap_note.setWordWrap(True)
            gg.addWidget(cap_note, 5, 0, 1, 6)
            fields.update(output=output, off=off, on=on)
            alias = QtWidgets.QLineEdit(self.channel_names.get(ch, ''))
            alias.setPlaceholderText('채널 별명')
            alias.setMaxLength(80)
            alias.editingFinished.connect(lambda c=ch: self._rename_channel(c))
            gg.addWidget(alias, 6, 0, 1, 6)
            fields.update(card=group, alias=alias)
            self.rows[ch] = fields
            align_rf_grid(gg)
            gg.setColumnMinimumWidth(2,240);gg.itemAtPosition(0,2).widget().setFixedWidth(240)
            for index in range(3):
                gg.itemAtPosition(index,3).widget().setFixedWidth(250)
            gg.setColumnMinimumWidth(3,250)
            base.addWidget(group)

        base.addWidget(ref)
        base.addLayout(ramp_row)

        warning = QtWidgets.QLabel(
            'The GUI frequency/power entry limits follow the default v1.4 server driver '
            '(53–13600 MHz; -60 to +20 dBm). RF settings outside these bounds are '
            'shown in Readback but not silently clamped into entry values. '
            'Phase is a relative increment only, not a phase measurement. '
            'Connect, Refresh and monitoring only READ. RF ON and reference changes explicitly affect '
            'the hardware. A reported PLL lock does NOT prove external-reference coherence. '
            'Verify with a frequency counter or a beat against a known reference. '
            'Do not open the manufacturer GUI and this server on the same USB port concurrently.')
        warning.setWordWrap(True)
        base.addWidget(warning)
        base.addStretch(1)
        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(60000)
        self.timer.timeout.connect(self._poll)
        self.stale_timer = QtCore.QTimer(self)
        self.stale_timer.setInterval(1000)
        self.stale_timer.timeout.connect(self._update_buttons)
        self.stale_timer.start()
        self.timer.start()
        self.connect_btn.clicked.connect(self._connect)
        self.disconnect_btn.clicked.connect(lambda: self._queue('DISCONNECT'))
        self.refresh_btn.clicked.connect(lambda: self._queue('REFRESH'))
        self.set_external_btn.clicked.connect(self._external)
        self.internal10_btn.clicked.connect(lambda: self._internal('internal 10mhz'))
        self.internal27_btn.clicked.connect(lambda: self._internal('internal 27mhz'))
        self._update_buttons()

    def _set_status(self, text):
        self.status.setText(text)
        self.log_message.emit(f'[Windfreak {self.device_name}] {text}')
        self._update_buttons()

    def _update_buttons(self):
        active = self.connected and not self.busy
        self.stop_ramp_btn.setEnabled(self.ramping)
        self.ramp_dwell.setEnabled(not self.busy)
        writable = active
        if not self.latest:
            for row in self.rows.values():
                row['on'].setStyleSheet(RF_INACTIVE_STYLE)
                row['on'].setText('RF ON (unknown)')
        self.connect_btn.setEnabled(not self.busy and not self.connected)
        self.disconnect_btn.setEnabled(active)
        self.refresh_btn.setEnabled(active)
        self.set_external_btn.setEnabled(writable)
        self.internal10_btn.setEnabled(writable)
        self.internal27_btn.setEnabled(writable)
        for r in self.rows.values():
            for name in ('frequency_hz_button', 'power_dbm_button',
                         'phase_deg_button', 'on'):
                r[name].setEnabled(writable)
            r['off'].setEnabled(active)  # Explicit OFF works even if readback is stale.

    def _queue(self, action, *args):
        self.status.setText(f'{action}: queued...')
        try:
            if action in ('OUTPUT', 'SET_POWER'):
                rf = device_api(self.worker, channel=args[0])
                if action == 'OUTPUT':
                    return rf.on() if args[1] else rf.off()
                ch, target, interval = args
                return rf.set_power(target, interval_s=interval)
            return device_api(self.worker).submit(action, *args)
        except Exception as error:
            self.worker.failure.emit(action, str(error))

    def _poll(self):
        if self.connected:
            return device_api(self.worker).auto_monitor()

    def _connect(self):
        provider = getattr(self, 'endpoint_provider', None)
        host, port = provider() if callable(provider) else (self.host, self.port)
        self._queue('CONNECT', host, port, self.device_name)

    def _on_connected(self, info):
        self.connected = True
        self.device_id.setText(f'Model: {info.get("model")} | S/N: {info.get("serial")} | '
                               f'Server USB: {info.get("devpath")}')
        self._set_status('Connected to server-owned device; no RF parameters changed')
        self._queue('REFRESH')

    def _on_disconnected(self, reason):
        self.connected = False
        self.latest = {}
        self.last_snapshot_time = 0.0
        for row in self.rows.values():
            row['freq_read'].setText('— '+row['frequency_units'].currentText())
            row['power_read'].setText('— dBm')
            row['phase_read'].setText('Unknown (last cmd)')
            row['power_read'].setStyleSheet('')
            row['on'].setStyleSheet(RF_INACTIVE_STYLE)
            row['on'].setText('RF ON (confirm)')
        self._set_status(reason)

    def _runner_busy(self, busy):
        self.busy = self.worker.has_requests()
        self._update_buttons()

    def _completed(self, action):
        self._set_status(f'{action}: completed')

    def _on_error(self, action, message):
        self._load_inputs_requested = False
        if action == 'CONNECT': self.connected = False
        self._set_status(f'{action}: {message}')
        box = QtWidgets.QMessageBox(QtWidgets.QMessageBox.Warning, 'Windfreak operation',
                                    f'{self.device_name} — {action}\n{message}', parent=self)
        box.setAttribute(QtCore.Qt.WA_DeleteOnClose)
        box.open()

    def _on_snapshot(self, data, action):
        from labremote.ui.library_updates import current_snapshot
        data = current_snapshot(self.worker._execution_device, data)
        ref = data['reference']
        val = ref.get('reference_frequency_hz')
        self.ref_mode.setText('Reference mode: ' + str(ref.get('reference_mode', 'UNKNOWN')))
        self.ref_frequency.setText(
            f'Reference setting: {float(val)/1e6:.6f} MHz'
            if val is not None else 'Reference: UNKNOWN')
        reported = ref.get('pll_lock') or {}
        if not isinstance(reported, dict):
            reported = {}
        self.pll_state.setText('PLL A/B reported: ' +
                               '/'.join(str(reported.get(ch, '?')) for ch in 'AB') +
                               ' (advisory only)')
        self.ext_verified.setText('Physical external reference lock: NOT VERIFIED '
                                  '(independent measurement required)')
        if (action == 'LOAD_INPUTS' or (action != 'LIBRARY' and getattr(self, '_load_inputs_requested', False))) and val is not None and ref.get('reference_mode') == 'external':
            self.ref_target.setValue(float(val)/self.ref_scale)
        for ch in 'AB':
            r = data['channels'][ch]
            row = self.rows[ch]
            freq_mhz = float(r['frequency_hz']) / row['frequency_scale'] if r.get('frequency_hz') is not None else None
            unit=row['frequency_units'].currentText()
            text=(format(freq_mhz,'.6f' if unit=='MHz' else '.9g')+' ') if freq_mhz is not None else '— '
            row['freq_read'].setText(text+unit)
            p_dbm = float(r['power_dbm']) if r.get('power_dbm') is not None else None
            # Keep configured presets as edit values; current hardware goes in Readback.
            # A QDoubleSpinBox silently CLAMPS out-of-range readbacks. Never
            # display its clamped value as the actual hardware frequency.
            for key, value in (('frequency_hz', freq_mhz), ('power_dbm', p_dbm)):
                widget = row[key]
                if ((action in ('CONNECT', 'LOAD_INPUTS') or (action != 'LIBRARY' and getattr(self, '_load_inputs_requested', False)))
                        and value is not None and widget.minimum() <= value <= widget.maximum()):
                    widget.setValue(value)
            phase = r.get('phase_deg')
            try:
                phase_txt = f'{float(phase):.3f} deg (last cmd)' if phase is not None else 'unknown'
            except (ValueError, TypeError):
                phase_txt = 'unknown'
            # Do NOT set the input for relative phase from a purported phase
            # measurement: no absolute-phase readback exists on v1.4.
            cap = self._power_caps[ch]
            over_cap = cap is not None and p_dbm is not None and p_dbm > cap + 1e-9
            row['power_read'].setText((f'{p_dbm:.3f} dBm' + (' (OVER MAX)' if over_cap else '')) if p_dbm is not None else '— dBm')
            row['power_read'].setStyleSheet('color:#ff8fa3;font-weight:bold' if over_cap else '')
            row['phase_read'].setText(phase_txt)
            on = r['output_enabled']
            row['output'].setText(
                f'Output: {"UNKNOWN" if on is None else "ON" if on else "OFF"}  |  PLL reported {r.get("pll_lock")}')
            row['on'].setText('RF ON' + (' ✓' if on else ' (confirm)'))
            row['on'].setStyleSheet(
                'QPushButton {background-color:#20554f; color:#9ef1df; font-weight:bold;}'
                if on else RF_INACTIVE_STYLE)
        self._apply_parameter_states(data)
        self.latest = data
        if not data.get('_library_generated') or data.get('_library_observation'):
            self.last_snapshot_time = time.monotonic()
        if action != 'LIBRARY':
            self._set_status(f'{action}: completed; displaying latest observations')

        if action != 'LIBRARY': self._load_inputs_requested = False

    def _apply_parameter_states(self, data):
        states = data.get('_parameter_states', {})
        def mark(label, paths):
            problems = []
            for path in paths:
                state = states.get(path, {})
                if state.get('quality', 'valid') != 'valid' or state.get('verification') in ('failed', 'mismatch'):
                    problems.append(f"{path}: {state.get('error') or state.get('quality')}")
            label.setToolTip('\n'.join(problems))
            if problems:
                label.setText(label.text() + ' [미확인]')
        for ch in 'AB':
            row = self.rows[ch]
            prefix = 'channel_' + ch + '.'
            for field, label in (('frequency_hz','freq_read'),('power_dbm','power_read'),('phase_deg','phase_read')):
                mark(row[label], [prefix + field])
            paths = data.get('_output_sources', {}).get(ch,
                [prefix + field for field in ('output_enabled','rf_enabled','pa_enabled','pll_enabled')])
            mark(row['output'], paths)
            if data['channels'][ch]['output_enabled'] is None or any(
                    states.get(path, {}).get('quality', 'valid') != 'valid'
                    or states.get(path, {}).get('verification') in ('failed','mismatch','pending') for path in paths):
                row['on'].setText('RF ON (unknown)')
                row['on'].setStyleSheet(RF_INACTIVE_STYLE)
        mark(self.ref_mode, ['reference_mode'])
        mark(self.ref_frequency, ['reference_frequency_hz'])
        mark(self.pll_state, ['channel_A.pll_lock','channel_B.pll_lock'])

    def _on_ramp_active(self, active):
        self.ramping = bool(active)
        self._update_buttons()
        if not active and self.ramp_label.text().startswith('Ramp'):
            self.ramp_label.setText('Ramp stopped / complete; check fresh readback')


    def _stop_power_ramp(self):
        if not self.ramping:
            return
        self.worker.cancel_power_ramp()
        self.ramp_label.setText('STOP requested — keeping last verified power; no automatic RF OFF')

    def _frequency_unit(self, channel, unit):
        row=self.rows[channel];editor=row['frequency_hz'];scale=FREQUENCY_SCALES[unit]
        value=editor.value()*row['frequency_scale']/scale
        editor.setDecimals(FREQUENCY_DECIMALS[unit]);editor.setRange(53e6/scale,13600e6/scale)
        editor.setValue(value);row['frequency_scale']=scale
        row['frequency_hz_step'].set_target_unit(unit)
        from labremote.ui.library_updates import current_snapshot
        data=current_snapshot(self.worker._execution_device)
        data['_library_generated']=True;data['_library_observation']=False
        self._on_snapshot(data,'LIBRARY')

    def _set_value(self, channel, key, widget):
        value = widget.value() * (self.rows[channel]['frequency_scale'] if key == 'frequency_hz' else 1)
        if key == 'power_dbm':
            self.ramp_label.setText(f'CH {channel}: ramp to {value:.3f} dBm queued')
            return self._queue('SET_POWER', channel, value, self.ramp_dwell.value())
        return self._queue('SET', key, channel, value)

    def _set_output(self, channel, on):
        if not on and self.connected:
            # RF OFF is allowed without a fresh readback; worker does not
            # require expected frequency/power when disabling output.
            self._queue('OUTPUT', channel, False, 0.0, 0.0)
            return
        r = self.latest.get('channels', {}).get(channel, {})
        if not r:
            return
        if on:
            text = f'Enable {self.device_name} channel {channel} at configured low power?'
            if QtWidgets.QMessageBox.question(self, 'Confirm physical RF output', text,
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No, QtWidgets.QMessageBox.No) != QtWidgets.QMessageBox.Yes:
                return
        self._queue('OUTPUT', channel, on, r['frequency_hz'], r['power_dbm'])

    def _reference_unit(self,unit):
        scale=FREQUENCY_SCALES[unit];value=self.ref_target.value()*self.ref_scale/scale
        step=self.ref_target.singleStep()*self.ref_scale/scale
        self.ref_target.setDecimals(FREQUENCY_DECIMALS[unit]);self.ref_target.setRange(10e6/scale,100e6/scale)
        self.ref_target.setValue(value);self.ref_target.setSingleStep(step);self.ref_scale=scale

    def _external(self):
        mhz = float(self.ref_target.value())*self.ref_scale/1e6
        msg = (f'Apply external {mhz:.6f} MHz reference on {self.device_name}?\n'
               'This changes the PLL clock source and may change RF phase/frequency.\n'
               'Readback confirms configuration only, NOT external synchronization.\n'
               'Check reference input amplitude and verify the RF externally.')
        if QtWidgets.QMessageBox.question(self, 'Confirm reference-clock CHANGE', msg,
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No, QtWidgets.QMessageBox.No) == QtWidgets.QMessageBox.Yes:
            self._queue('EXTERNAL_REFERENCE', mhz * 1e6)

    def _any_rf_stage_active(self):
        for r in self.latest.get('channels', {}).values():
            if any(r.get(key) for key in ('rf_enabled', 'pa_enabled',
                                          'pll_enabled', 'output_enabled')):
                return True
        return False

    def _internal(self, mode):
        if QtWidgets.QMessageBox.question(self, 'Confirm reference-clock CHANGE',
            f'Change {self.device_name} to {mode}? This may change its RF frequency/phase.',
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No, QtWidgets.QMessageBox.No) == QtWidgets.QMessageBox.Yes:
            self._queue('INTERNAL_REFERENCE', mode)

    def shutdown(self):
        self.timer.stop()
        self.stale_timer.stop()
        self.worker.shutdown()

    def still_running(self):
        return self.worker.isRunning()
