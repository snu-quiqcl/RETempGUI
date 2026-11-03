"""FPGA adapter using the command protocol in the supplied DAC81416 scripts.

The existing utils.ArtyS7_v1_02 implementation owns UART framing. This module
deliberately does not guess its baud rate, packet encoding, or reply format.
"""
from __future__ import annotations

import importlib
import time
from pathlib import Path
import sys
from contextlib import nullcontext

from .model import VoltageSet
from .configuration import voltage_code
from .timing import ManualTiming, SequenceOptions
from .transport import CheckedArtyS7


class MockArtyS7:
    """An in-memory transport; never opens a serial port."""
    def __init__(self, port: str):
        self.port = port
        self.events = []
        self.closed = False
        self.buffer_codes = [[0] * 16 for _ in range(2)]
        self.active_codes = [[0] * 16 for _ in range(2)]
        self.sync_masks = [0, 0]
        self._packet = []
        self._chip_mask = 0

    def send_command(self, value):
        if self.closed:
            raise OSError("Simulation connection is closed.")
        self.events.append(("command", value))
        if value == "SET CONFIG":
            self._chip_mask = (int.from_bytes(bytes(self._packet), 'big') >> 16) & 0xff
        elif value == "WRITE REG":
            address, hi, lo, _ = self._packet
            data = (hi << 8) | lo
            for chip in range(2):
                if not self._chip_mask & (1 << chip):
                    continue
                if address == 0x06:
                    self.sync_masks[chip] = data
                elif 0x10 <= address <= 0x1f:
                    channel = address - 0x10
                    self.buffer_codes[chip][channel] = data
                    if not self.sync_masks[chip] & (1 << channel):
                        self.active_codes[chip][channel] = data
        elif value == "LDAC":
            for chip in range(2):
                for channel in range(16):
                    if self.sync_masks[chip] & (1 << channel):
                        self.active_codes[chip][channel] = self.buffer_codes[chip][channel]

    def send_mod_BTF_int_list(self, value):
        if self.closed:
            raise OSError("Simulation connection is closed.")
        self.events.append(("bytes", list(value)))
        self._packet = list(value)

    def close(self):
        self.closed = True

    def wait_tx(self):
        if self.closed:
            raise OSError('Simulation connection is closed.')


def open_transport(port: str, simulation: bool, driver_dir: str = ""):
    if simulation:
        return MockArtyS7(port)
    if driver_dir:
        folder = str(Path(driver_dir).expanduser().resolve())
        if folder not in sys.path:
            sys.path.insert(0, folder)
        importlib.invalidate_caches()
    try:
        module = importlib.import_module("trap_dac.vendor.ArtyS7_v1_02")
    except ImportError as exc:
        raise RuntimeError(
            "Cannot import utils.ArtyS7_v1_02. Copy your existing utils folder "
            "beside main.py, or select its parent using Driver folder. "
            f"Install the driver's dependencies as well. Detail: {exc}"
        ) from exc
    return CheckedArtyS7(module.ArtyS7(port))


class DACSession:
    def __init__(self, config, transport, simulation: bool = False, *,
                 clock=time.monotonic, sleep=time.sleep):
        self.config = config
        self.device = config.device
        self.transport = transport
        self.simulation = simulation
        self.ready = False
        self.closed = False
        self._ldac_mode = None
        self._last_voltages = None
        self.last_written_electrode_ids = ()
        self.last_transfer = {}
        self._last_codes = None
        self._spi_config = None
        self._reuse_spi = False
        self._manual_timing = None
        self._config_writes = 0
        self._clock, self._sleep = clock, sleep
        self._phase_stats = None

    def _invalidate_outputs(self):
        self.ready = False
        self._ldac_mode = None
        self._last_voltages = None
        self.last_written_electrode_ids = ()
        self._last_codes = None
        self._spi_config = None
        self.last_transfer = {}

    def _pause_ms(self, milliseconds, phase='other'):
        if milliseconds and not self.simulation:
            started = self._clock()
            self._sleep(milliseconds / 1000)
            if self._phase_stats is not None:
                self._phase_stats['sleep_requested_s'] += milliseconds / 1000
                self._phase_stats['sleep_actual_s'] += self._clock() - started
                self._phase_stats['sleep_calls'] += 1
                self._phase_stats[phase + '_s'] = self._phase_stats.get(phase + '_s', 0) + self._clock() - started

    def _drain(self):
        started = self._clock()
        self.transport.wait_tx()
        if self._phase_stats is not None:
            self._phase_stats['tx_wait_s'] += self._clock() - started
            self._phase_stats['tx_wait_calls'] += 1

    def _send_data(self, data):
        self.transport.send_mod_BTF_int_list(data)

    def _send_command(self, command):
        self.transport.send_command(command)

    def _check_open(self):
        if self.closed:
            raise RuntimeError("The connection is closed.")

    @staticmethod
    def config_bytes(chip: int) -> list[int]:
        config = (1 << 29) | ((1 << chip) << 16) | (23 << 11) | (1 << 8) | 64
        return list(config.to_bytes(8, "big"))

    def write_register(self, chip: int, address: int, data: int):
        self._check_open()
        config = tuple(self.config_bytes(chip))
        batch = getattr(self.transport, 'batch_packets', nullcontext)
        with batch() if self._manual_timing is not None else nullcontext():
            if not self._reuse_spi or self._spi_config != config:
                self._send_data(list(config))
                self._send_command("SET CONFIG")
                self._spi_config = config
                self._config_writes += 1
            self._send_data([address & 0xff, (data >> 8) & 0xff, data & 0xff, 0])
            self._send_command("WRITE REG")
        if self._manual_timing is not None:
            self._drain()
            self._pause_ms(self._manual_timing.command_gap_ms, 'register_gap')

    def _both(self, address, data):
        for chip in (0, 1):
            self.write_register(chip, address, data)

    def initialize(self, initial_voltages=None, *, use_ldac=True,
                   internal_reference=False, stop_event=None):
        """Preload calibrated codes while outputs are disabled, then enable used channels.

        Never reset FPGA. External reference is the original board convention;
        the server owner explicitly selects internal reference if wired for it.
        Completion means host TX complete, not analog readback verification.
        """
        self._check_open()
        if type(use_ldac) is not bool or type(internal_reference) is not bool:
            raise ValueError('LDAC/reference flags must be boolean')
        values = {e.id: 0.0 for e in self.config.electrodes} if initial_voltages is None else initial_voltages
        state = VoltageSet.from_values(self.config, values, name='Initialization')
        commands = state.commands()  # Validate ALL values before the first write.
        self._invalidate_outputs()
        def cancelled():
            if stop_event is not None and stop_event.is_set():
                raise InterruptedError('Initialization cancelled; outputs not verified')
        try:
            cancelled()
            self._both(0x09, 0xFFFF)  # Disable both chips before changing range.
            self._drain()
            self._both(0x03, 0x0A80)  # Active, reserved bit7=1, alarm enables, no SDO/CRC.
            self._drain()
            if not self.simulation:self._sleep(1)
            cancelled()
            self._both(0x03, 0x0A80)
            self._both(0x04, 0x3F00 if internal_reference else 0x7F00)
            for address in range(0x0A, 0x0E):self._both(address, 0xCCCC)
            self._both(0x07, 0); self._both(0x08, 0)  # Disable toggle.
            self._both(0x06, 0)
            # Also preload unused outputs to midscale, but leave them powered down.
            codes = {(c.chip,c.channel):c.code for c in commands}
            for chip in (0,1):
                for channel in range(16):
                    self.write_register(chip,0x10+channel,codes.get((chip,channel),0x8000))
            self._drain()
            self._pause_ms(10)
            cancelled()
            self._ldac_mode = False
            self._configure_ldac(use_ldac)
            self._drain()
            cancelled()
            for chip in (0,1):
                used=sum(1<<e.channel for e in self.config.electrodes if e.chip==chip)
                self.write_register(chip,0x09,0xFFFF ^ used)
            self._drain()
        except Exception:
            self._invalidate_outputs()
            raise
        self.ready=True
        self._last_voltages=dict(state.by_id)
        self._last_codes={c.electrode_id:c.code for c in commands}
        self.last_written_electrode_ids=tuple(state.by_id)
        self.last_transfer=dict(profile='initialize',host_tx_completed=True,readback_verified=False)
        return state

    def _configure_ldac(self, enabled):
        if enabled == self._ldac_mode:
            return
        for chip in (0, 1):
            # Only mapped electrodes participate in the common LDAC trigger.
            mask = sum(1 << e.channel for e in self.config.electrodes if e.chip == chip) if enabled else 0
            self.write_register(chip, 0x06, mask)
        if enabled:
            # Original update_ldac_period(10): 10 FPGA clocks (100 ns per source).
            self._send_data([10])
            self._send_command("LDAC LENGTH")
        self._ldac_mode = enabled

    def dac_set_voltage(self, chip, channel, voltage):
        """Write one mapped DAC channel; synchronous mode only stages its value.

        This is the original dac_set_voltage(chip, ch, voltage) operation with
        the current JSON calibration and range checks. It never triggers LDAC.
        A standalone call invalidates the complete-set comparison cache.
        """
        self._check_open()
        if not self.ready:
            raise RuntimeError("Initialize the DAC before setting a voltage.")
        code = voltage_code(self.config, chip, channel, voltage)
        if not any(e.chip == chip and e.channel == channel for e in self.config.electrodes):
            raise ValueError("DAC channel is not mapped to an electrode in this configuration.")
        self._last_voltages = None
        self._last_codes = None
        self.last_written_electrode_ids = ()
        try:
            self.write_register(chip, 0x10 | channel, code)
        except Exception:
            self._invalidate_outputs()
            raise

    def trigger_ldac(self):
        """Commit staged channel values with one common FPGA LDAC command."""
        self._check_open()
        if not self.ready or self._ldac_mode is not True:
            raise RuntimeError("Enable synchronous LDAC updates before triggering.")
        self._last_voltages = None
        self._last_codes = None
        self.last_written_electrode_ids = ()
        try:
            self._send_command("LDAC")
        except Exception:
            self._invalidate_outputs()
            raise

    def apply(self, state: VoltageSet, use_ldac: bool = False, *, profile='standard',
              manual_timing=None, sequence_options=None, force_full=False):
        """Validate once, write channels individually, then optionally trigger.

        Manual: full resend, drain/gap each register, pre-LDAC wait and cooldown.
        Sequence: compare actual DAC codes, reuse selected SPI config, drain
        before/after LDAC. First run row is explicitly forced full by runner.
        Standard retains the original API's immediate/LDAC selection policy.
        """
        self._check_open()
        if not self.ready:
            raise RuntimeError("Initialize the DAC before applying voltages.")
        if state.device != self.device:
            raise ValueError("Preset and connected device do not match.")
        if state.config != self.config:
            raise ValueError("Configuration changed. Reconnect before applying voltages.")
        if type(use_ldac) is not bool:
            raise ValueError("use_ldac must be true or false.")
        if profile not in ('standard', 'manual', 'sequence'):
            raise ValueError('Unknown transmission profile.')
        timing = (manual_timing or ManualTiming()).validate()
        options = (sequence_options or SequenceOptions()).validate()
        commands = state.commands()  # Validate the complete target before any I/O.
        target_codes = {c.electrode_id: c.code for c in commands}
        mode_changed = self._ldac_mode != use_ldac
        if profile == 'sequence' and self._last_codes is not None and not force_full and not mode_changed:
            commands = tuple(c for c in commands if self._last_codes[c.electrode_id] != c.code)
        elif profile == 'standard' and not use_ldac and self._last_voltages is not None and not force_full:
            commands = tuple(c for c in commands
                             if self._last_voltages[c.electrode_id] != c.voltage)
        self.last_written_electrode_ids = ()
        self.last_transfer = {}
        started = self._clock()
        before_bytes = getattr(self.transport, 'bytes_written', None)
        before_write_stats = getattr(self.transport, 'write_stats', {})
        before_configs = self._config_writes
        phases = dict(tx_wait_s=0.0, tx_wait_calls=0, sleep_requested_s=0.0,
                      sleep_actual_s=0.0, sleep_calls=0)
        self._phase_stats = phases
        self._reuse_spi = profile == 'sequence' and options.reuse_spi_config
        self._manual_timing = timing if profile == 'manual' else None
        if force_full or profile == 'manual':
            self._spi_config = None
        try:
            self._configure_ldac(use_ldac)
            for item in commands:
                self.dac_set_voltage(item.chip, item.channel, item.voltage)
            self._drain()
            if use_ldac:
                self._pause_ms(timing.pre_ldac_ms if profile == 'manual' else
                               options.pre_ldac_ms if profile == 'sequence' else 0, 'pre_ldac')
                self.trigger_ldac()
                self._drain()
            if profile == 'manual':
                self._pause_ms(timing.cooldown_ms, 'cooldown')
        except Exception:
            # The previous complete set can no longer describe all outputs.
            # Require recovery before another apply; do not attempt a rollback.
            self._invalidate_outputs()
            raise
        finally:
            self._manual_timing = None
            self._reuse_spi = False
            self._phase_stats = None
        self._last_voltages = dict(state.by_id)
        self._last_codes = target_codes
        self.last_written_electrode_ids = tuple(c.electrode_id for c in commands)
        after_bytes = getattr(self.transport, 'bytes_written', None)
        after_write_stats = getattr(self.transport, 'write_stats', {})
        write_s = after_write_stats.get('write_s', 0) - before_write_stats.get('write_s', 0)
        elapsed = self._clock() - started
        self.last_transfer = dict(profile=profile, channels_written=len(commands),
                                  channels_total=len(target_codes),
                                  spi_config_writes=self._config_writes-before_configs,
                                  uart_bytes=None if before_bytes is None else after_bytes-before_bytes,
                                  tx_elapsed_s=elapsed, host_tx_completed=True,
                                  readback_verified=False, ldac_triggered=use_ldac,
                                  write_s=write_s, write_calls=after_write_stats.get('write_calls', 0)-before_write_stats.get('write_calls', 0),
                                  other_s=max(0.0, elapsed-write_s-phases['tx_wait_s']-phases['sleep_actual_s']),
                                  **phases)
        return state

    def close(self):
        """Close UART only. Do not reset, zero, or power down the DAC."""
        self._invalidate_outputs()
        self.transport.close()
        self.closed = True
