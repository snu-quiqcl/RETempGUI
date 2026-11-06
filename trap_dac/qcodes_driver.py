"""Mapping-independent, synchronous QCoDeS driver for two DAC81416 chips.

Only ArtyS7.py is required beside this module. No sequence, files, or server jobs.
Successful writes report host transmission, never measured analog voltage.
"""
from copy import deepcopy
import hashlib
import json
import math
import threading
import time
from uuid import uuid4

from qcodes.instrument import Instrument
from .ArtyS7 import ArtyS7, CheckedArtyS7


def _number(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(label + ': finite number required')
    value = float(value)
    if not math.isfinite(value):
        raise ValueError(label + ': finite number required')
    return value


def _matrix(values, label):
    if not isinstance(values, (list, tuple)) or len(values) != 2:
        raise ValueError(label + ': expected [2][16] array')
    result = []
    for row in values:
        if not isinstance(row, (list, tuple)) or len(row) != 16:
            raise ValueError(label + ': expected [2][16] array')
        result.append([_number(v, label) for v in row])
    return result


def _code(voltage, offset):
    voltage = _number(voltage, 'voltage')
    if not -20 <= voltage <= 20:
        raise ValueError('Target voltage must be within -20..20 V')
    command = voltage - offset
    # Exact positive endpoint of the existing 16-bit transfer function.
    if not -20 <= command <= 20 - 40 / 65536:
        raise ValueError('Corrected voltage outside representable DAC range')
    return int(command / 40 * 65536 + 32768)


class DAC81416(Instrument):
    def __init__(self, name, serial_port, internal_reference=False,
                 command_gap_ms=5.0, pre_ldac_ms=10.0, cooldown_ms=100.0,
                 **kwargs):
        if type(internal_reference) is not bool:
            raise ValueError('internal_reference must be boolean')
        self._timing = self._check_timing(command_gap_ms, pre_ldac_ms, cooldown_ms)
        super().__init__(name, **kwargs)
        self._serial_port = serial_port
        self._internal_reference = internal_reference
        self._lock = threading.RLock()
        self._transport = None
        self._sleep = time.sleep
        self._offsets = None
        self._configuration_id = None
        self._calibration_hash = None
        self._ready = False
        self._faulted = False
        self._last_error = None
        self._last_voltages = None
        self._last_codes = None
        self._ldac = None
        self._spi_config = None
        self._reuse_spi = False
        self._active_gap = self._timing[0]

    @staticmethod
    def _check_timing(gap, pre, cooldown):
        values = tuple(_number(v, 'timing') for v in (gap, pre, cooldown))
        if any(v < 0 or v > limit for v, limit in zip(values, (1000, 1000, 5000))):
            raise ValueError('Timing outside allowed millisecond range')
        return values

    def get_idn(self):
        return dict(vendor='TI / custom ArtyS7', model='DAC81416',
                    serial=None, firmware='trap-dac-api-2')

    def connect(self):
        """Open USB only. Never initialize or change output voltages."""
        with self._lock:
            if self._transport is None:
                self._transport = CheckedArtyS7(ArtyS7(self._serial_port))
            return self.get_status()

    def get_status(self):
        """Return server memory, not FPGA or analog readback."""
        with self._lock:
            return deepcopy(dict(protocol=2, chips=2, channels_per_chip=16,
                connected=self._transport is not None, ready=self._ready,
                faulted=self._faulted, last_error=self._last_error,
                configuration_id=self._configuration_id,
                calibration_hash=self._calibration_hash,
                last_requested_voltages=self._last_voltages,
                last_sent_codes=self._last_codes, last_ldac=self._ldac,
                readback_verified=False))

    def _invalidate(self):
        self._ready = False
        self._configuration_id = None
        self._last_voltages = self._last_codes = None
        self._ldac = self._spi_config = None

    def _failed(self, exc):
        self._invalidate()
        self._faulted = True
        self._last_error = str(exc)

    def _write_register(self, chip, address, data):
        config = (1 << 29) | ((1 << chip) << 16) | (23 << 11) | (1 << 8) | 64
        if not self._reuse_spi or config != self._spi_config:
            self._transport.send_mod_BTF_int_list(list(config.to_bytes(8, 'big')))
            self._transport.send_command('SET CONFIG')
            self._spi_config = config
        self._transport.send_mod_BTF_int_list([address, data >> 8, data & 255, 0])
        self._transport.send_command('WRITE REG')
        self._transport.wait_tx()
        self._sleep(self._active_gap / 1000)

    def _both(self, address, data):
        for chip in range(2):
            self._write_register(chip, address, data)

    def _set_ldac(self, enabled):
        if self._ldac == enabled:
            return
        self._both(0x06, 0xFFFF if enabled else 0)
        if enabled:
            self._transport.send_mod_BTF_int_list([10])
            self._transport.send_command('LDAC LENGTH')
            self._transport.wait_tx()
        self._ldac = enabled

    def initialize(self, offsets, initial_voltages, use_ldac=True):
        """Validate then initialize all 32 outputs; returns a new session token.

        Offsets are supplied by the client and kept only in server memory.
        Initialization interrupts existing output. Reconnect after a TX fault.
        """
        with self._lock:
            if type(use_ldac) is not bool:
                raise ValueError('use_ldac must be boolean')
            offsets = _matrix(offsets, 'offsets')
            voltages = _matrix(initial_voltages, 'initial_voltages')
            codes = [[_code(voltages[c][n], offsets[c][n]) for n in range(16)] for c in range(2)]
            if self._transport is None or self._faulted:
                raise RuntimeError('Connect/reconnect before initialization')
            self._invalidate()
            self._active_gap = self._timing[0]
            self._reuse_spi = False
            try:
                self._both(0x09, 0xFFFF)
                self._both(0x03, 0x0A80)
                self._sleep(1)
                self._both(0x03, 0x0A80)
                self._both(0x04, 0x3F00 if self._internal_reference else 0x7F00)
                for address in range(0x0A, 0x0E):
                    self._both(address, 0xCCCC)
                self._both(0x07, 0)
                self._both(0x08, 0)
                self._both(0x06, 0)
                for chip in range(2):
                    for channel in range(16):
                        self._write_register(chip, 0x10 + channel, codes[chip][channel])
                self._sleep(.01)
                self._ldac = False
                self._set_ldac(use_ldac)
                self._both(0x09, 0)  # All 32 channels enabled, independent of electrode map.
                self._transport.wait_tx()
            except Exception as exc:
                self._failed(exc)
                raise
            self._offsets = offsets
            self._calibration_hash = hashlib.sha256(json.dumps(offsets, separators=(',', ':')).encode()).hexdigest()
            self._configuration_id = uuid4().hex
            self._last_voltages, self._last_codes = voltages, codes
            self._ready = True
            self._last_error = None
            return self.get_status()

    def set_voltage(self, chip, channel, voltage, configuration_id, use_ldac=True):
        return self.set_voltages([[chip, channel, voltage]], configuration_id, use_ldac)

    def set_voltages(self, updates, configuration_id, use_ldac=True,
                     command_gap_ms=None, pre_ldac_ms=None, cooldown_ms=None,
                     reuse_spi_config=False):
        """Apply physical [chip, channel, target_voltage] rows with one LDAC.

        Unspecified outputs retain their previous values. No automatic retries.
        The configuration token rejects writes after another initialization.
        """
        with self._lock:
            if not self._ready:
                raise RuntimeError('Initialize DAC before applying voltages')
            if not configuration_id or configuration_id != self._configuration_id:
                raise ValueError('DAC configuration changed; initialize or reconnect explicitly')
            if type(use_ldac) is not bool or type(reuse_spi_config) is not bool:
                raise ValueError('LDAC/reuse flags must be boolean')
            timing = self._check_timing(*(default if v is None else v for default, v in
                zip(self._timing, (command_gap_ms, pre_ldac_ms, cooldown_ms))))
            if not isinstance(updates, (list, tuple)) or not 1 <= len(updates) <= 32:
                raise ValueError('Expected 1..32 updates')
            parsed, seen = [], set()
            for row in updates:
                if not isinstance(row, (list, tuple)) or len(row) != 3:
                    raise ValueError('Expected [chip, channel, voltage]')
                chip, channel, voltage = row
                if type(chip) is not int or chip not in (0, 1) or type(channel) is not int or not 0 <= channel < 16:
                    raise ValueError('chip must be 0..1 and channel 0..15')
                if (chip, channel) in seen:
                    raise ValueError('Duplicate physical channel')
                seen.add((chip, channel))
                parsed.append((chip, channel, float(voltage), _code(voltage, self._offsets[chip][channel])))
            self._active_gap, pre, cooldown = timing
            self._reuse_spi = reuse_spi_config
            try:
                self._set_ldac(use_ldac)
                for chip, channel, voltage, code in parsed:
                    self._write_register(chip, 0x10 + channel, code)
                self._transport.wait_tx()
                if use_ldac:
                    self._sleep(pre / 1000)
                    self._transport.send_command('LDAC')
                    self._transport.wait_tx()
                self._sleep(cooldown / 1000)
            except Exception as exc:
                self._failed(exc)
                raise
            finally:
                self._reuse_spi = False
            for chip, channel, voltage, code in parsed:
                self._last_voltages[chip][channel] = voltage
                self._last_codes[chip][channel] = code
            return self.get_status()

    def disconnect(self):
        """Close USB, retain physical outputs, discard initialization state."""
        with self._lock:
            transport, self._transport = self._transport, None
            self._invalidate()
            self._offsets = self._calibration_hash = None
            self._faulted = False
            if transport is not None:
                transport.close()
            return self.get_status()

    def close(self):
        try:
            if hasattr(self, '_lock'):
                self.disconnect()
        finally:
            super().close()
