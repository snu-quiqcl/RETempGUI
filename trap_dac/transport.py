"""Checked, bounded UART writes around the user's unchanged ArtyS7 driver.

Framing stays in ArtyS7_v1_02. A drained host queue is not a DAC readback or
an FPGA acknowledgement; the UI deliberately continues to report 'sent'.
"""
from __future__ import annotations

import time
from contextlib import contextmanager


class CheckedSerial:
    def __init__(self, port, *, timeout_s=2.0, clock=time.monotonic, sleep=time.sleep):
        self.port = port
        self.timeout_s = timeout_s
        self.clock, self.sleep = clock, sleep
        # ArtyS7 originally uses writeTimeout=0. Keep its baud/framing unchanged.
        port.write_timeout = timeout_s
        parity_bits = 0 if port.parity == 'N' else 1
        self.byte_time = (1 + port.bytesize + parity_bits + port.stopbits) / port.baudrate
        self.bytes_written = 0
        self._wire_ready = clock()
        self._pending = False
        self._batch = None
        self.write_calls = 0
        self.write_s = 0.0

    @contextmanager
    def batch_packets(self):
        """Preserve driver framing/order while issuing one checked OS write.

        Used only for the packets of one manual register transaction. Never
        collect a whole sequence, and discard an unsubmitted batch on errors.
        """
        if self._batch is not None:
            raise RuntimeError('Nested UART packet batches are not supported.')
        self._batch = bytearray()
        try:
            yield
            data = bytes(self._batch)
            self._batch = None
            if data:
                self.write(data)
        finally:
            self._batch = None

    def __getattr__(self, name):
        return getattr(self.port, name)

    def write(self, data):
        if self._batch is not None:
            self._batch.extend(data)
            return len(data)
        started = self.clock()
        self.write_calls += 1
        try:
            count = self.port.write(data)
        finally:
            self.write_s += self.clock() - started
        if count != len(data):
            raise OSError(f'UART incomplete write: {count!r}/{len(data)} bytes. '
                          'Output state is unknown; reconnect and reinitialize.')
        self.bytes_written += count
        self._wire_ready = max(self._wire_ready, started) + count * self.byte_time
        self._pending = True
        return count

    def wait_tx(self):
        """Bounded OS queue drain plus the UART wire-time lower bound.

        out_waiting may reach zero before a USB adapter finishes its bytes.
        The wire budget prevents a fast host callback starting Hold too early.
        Only FPGA acknowledgement/readback could prove device completion.
        """
        if self._batch is not None:
            raise RuntimeError('Finish the UART packet batch before waiting for transmission.')
        if not self._pending:
            return
        deadline = self.clock() + self.timeout_s
        while True:
            if not self.port.is_open:
                raise OSError('UART closed while waiting for transmission.')
            remaining = self.port.out_waiting
            now = self.clock()
            if remaining == 0 and now >= self._wire_ready:
                self._pending = False
                return
            if now >= deadline:
                raise TimeoutError(f'UART transmission did not finish within {self.timeout_s:g} s '
                                   f'({remaining} bytes still queued).')
            self.sleep(min(.002, deadline - now))


class CheckedArtyS7:
    def __init__(self, driver, **kwargs):
        self.driver = driver
        try:
            self.serial = CheckedSerial(driver.com, **kwargs)
            driver.com = self.serial
        except Exception:
            driver.close()
            raise

    @property
    def bytes_written(self):
        return self.serial.bytes_written

    @property
    def write_stats(self):
        return dict(write_calls=self.serial.write_calls, write_s=self.serial.write_s)

    def batch_packets(self):
        return self.serial.batch_packets()

    def __getattr__(self, name):
        return getattr(self.driver, name)

    def send_command(self, command):
        if not isinstance(command, str) or not 0 < len(command) <= 15:
            raise ValueError('ArtyS7 command must contain 1 to 15 characters.')
        self.driver.send_command(command)

    def send_mod_BTF_int_list(self, data):
        if not 0 < len(data) <= 256 or any(type(v) is not int or not 0 <= v <= 255 for v in data):
            raise ValueError('ArtyS7 payload must contain 1 to 256 bytes.')
        self.driver.send_mod_BTF_int_list(data)

    def wait_tx(self):
        self.serial.wait_tx()

    def close(self):
        self.driver.close()
