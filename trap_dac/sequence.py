"""Validated row sequences and cancellable, host-timed DAC execution."""
from __future__ import annotations

from .timing import SequenceOptions

import csv
import io
import json
import re
import tempfile
import time
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path

from .configuration import DeviceConfig, number, read_json
from .model import VoltageSet, atomic_json, atomic_text

MAX_ROWS = 10000


@dataclass(frozen=True)
class SequenceRow:
    state: VoltageSet
    hold_s: float = 0.1

    def validate(self):
        self.state.validate()
        hold = number(self.hold_s, 'Hold (s)')
        if not 0 <= hold <= 86400:
            raise ValueError('Hold (s) must be from 0 to 86400.')
        return self


@dataclass(frozen=True)
class VoltageSequence:
    config: DeviceConfig
    rows: tuple[SequenceRow, ...]
    use_ldac: bool = True
    name: str = 'Sequence'

    def validate(self):
        if type(self.use_ldac) is not bool or not isinstance(self.name, str):
            raise ValueError('Invalid sequence name or LDAC mode.')
        if not isinstance(self.rows, (tuple, list)) or not 1 <= len(self.rows) <= MAX_ROWS:
            raise ValueError(f'A sequence requires 1 to {MAX_ROWS} rows.')
        for index, row in enumerate(self.rows, 1):
            try:
                if not isinstance(row, SequenceRow) or row.state.config != self.config:
                    raise ValueError('Row does not match the current device configuration.')
                row.validate()
            except ValueError as exc:
                raise ValueError(f'Row {index}: {exc}') from exc
        return self

    def as_dict(self, **metadata):
        self.validate()
        data = dict(format='trap-dac-sequence', schema_version=1,
                    device=self.config.device, name=self.name, use_ldac=self.use_ldac,
                    saved_at=datetime.now().astimezone().isoformat(),
                    configuration=self.config.as_dict(),
                    rows=[dict(voltages=row.state.by_id, hold_s=row.hold_s) for row in self.rows])
        data.update(metadata)
        return data

    @classmethod
    def from_dict(cls, data, config):
        if (not isinstance(data, dict) or data.get('format') != 'trap-dac-sequence'
                or type(data.get('schema_version')) is not int or data['schema_version'] != 1):
            raise ValueError('Unsupported sequence format.')
        if data.get('device') != config.device:
            raise ValueError(f'Open a {config.device} sequence in this tab.')
        saved = DeviceConfig.from_dict(data.get('configuration'), config.device)
        if saved.wiring() != config.wiring():
            raise ValueError('Sequence wiring differs from the current configuration.')
        raw_rows = data.get('rows')
        if not isinstance(raw_rows, list) or not 1 <= len(raw_rows) <= MAX_ROWS:
            raise ValueError(f'A sequence requires 1 to {MAX_ROWS} rows.')
        rows = []
        for index, row in enumerate(raw_rows, 1):
            if not isinstance(row, dict):
                raise ValueError(f'Row {index}: invalid row object.')
            try:
                state = VoltageSet.from_values(config, row.get('voltages'), name=f'Row {index}')
                rows.append(SequenceRow(state, row.get('hold_s')).validate())
            except ValueError as exc:
                raise ValueError(f'Row {index}: {exc}') from exc
        return cls(config, tuple(rows), data.get('use_ldac', True), data.get('name', 'Sequence')).validate()


def load_sequence(path, config, *, use_ldac=True):
    """Load CSV against the active config; retain legacy JSON compatibility.

    CSV contains only a Hold (s) column and electrode-ID voltage columns.
    Its LDAC mode comes from the caller, not from the file.
    """
    path = Path(path)
    if path.suffix.lower() == '.json':
        return VoltageSequence.from_dict(read_json(path), config)
    if path.suffix.lower() != '.csv':
        raise ValueError('Choose a .csv sequence or a legacy .json sequence.')
    with path.open(encoding='utf-8-sig', newline='') as stream:
        reader = csv.reader(stream, strict=True)
        try:
            header = next((row for row in reader if any(v.strip() for v in row)), None)
            if header is None:
                raise ValueError('CSV is empty. Include Hold (s) and electrode IDs in the first row.')
            # Ignore surrounding header whitespace while retaining case-sensitive IDs.
            header = [v.strip() for v in header]
            if len(set(header)) != len(header):
                raise ValueError('CSV contains duplicate column headers.')
            hold_columns = [i for i, value in enumerate(header)
                            if value.casefold() in ('hold (s)', 'hold_s')]
            if len(hold_columns) != 1:
                raise ValueError('CSV requires exactly one Hold (s) (or hold_s) column.')
            hold_index = hold_columns[0]
            voltage_columns = {key: i for i, key in enumerate(header) if i != hold_index}
            legacy_ec_ids = {f'{side}{ch}' for side in ('L', 'R') for ch in range(7)} | {'L_IN', 'R_IN'}
            if (config.device == 'EC' and len(config.electrodes) == 32
                    and set(voltage_columns) == legacy_ec_ids):
                raise ValueError('This is a legacy 16-electrode EC CSV. The current EC mapping uses 32 electrodes. '
                                 'Remap the old voltages by physical electrode number and supply all 32 values; '
                                 'do not only append zeros to the old columns. See EC_sequence_example.csv and README.md.')
            expected = set(config.by_id)
            missing, extra = expected - voltage_columns.keys(), voltage_columns.keys() - expected
            if missing or extra:
                details = []
                if missing: details.append('missing IDs: ' + ', '.join(sorted(missing)))
                if extra: details.append('unknown IDs: ' + ', '.join(sorted(extra)))
                raise ValueError(f'CSV does not match {config.device}.json (' + '; '.join(details) + ').')
            rows = []
            for fields in reader:
                if not any(v.strip() for v in fields):
                    continue
                if len(fields) != len(header):
                    raise ValueError(f'CSV line {reader.line_num}: expected {len(header)} cells, got {len(fields)}.')
                values = []
                for key, field in zip(header, fields):
                    try:
                        values.append(float(field.strip()))
                    except ValueError as exc:
                        raise ValueError(f'CSV line {reader.line_num}, column {key}: a numeric value is required.') from exc
                try:
                    state = VoltageSet.from_values(config, {eid: values[i] for eid, i in voltage_columns.items()},
                                                   name=f'Row {len(rows)+1}')
                    rows.append(SequenceRow(state, values[hold_index]).validate())
                except ValueError as exc:
                    raise ValueError(f'CSV line {reader.line_num}: {exc}') from exc
                if len(rows) > MAX_ROWS:
                    raise ValueError(f'Maximum {MAX_ROWS} sequence rows.')
        except csv.Error as exc:
            raise ValueError(f'Invalid CSV near line {reader.line_num}: {exc}') from exc
    return VoltageSequence(config, tuple(rows), use_ldac, path.stem).validate()


def save_sequence(path, sequence):
    """Save an editable CSV by default in the UI, or a complete legacy JSON file."""
    path = Path(path)
    sequence.validate()
    if path.suffix.lower() == '.json':
        atomic_json(path, sequence.as_dict())
        return
    if path.suffix.lower() != '.csv':
        raise ValueError('Save the sequence with a .csv or .json extension.')
    if any(e.id.strip() != e.id or e.id.casefold() in ('hold (s)', 'hold_s')
           for e in sequence.config.electrodes):
        raise ValueError('CSV electrode IDs cannot have surrounding whitespace or use the reserved Hold (s) / hold_s names.')
    output = io.StringIO(newline='')
    writer = csv.writer(output, lineterminator='\r\n')
    writer.writerow(['Hold (s)'] + [e.id for e in sequence.config.electrodes])
    for row in sequence.rows:
        # Short round-trip representations keep CSV editable without losing precision.
        writer.writerow([str(float(row.hold_s))] + [str(float(v)) for v in row.state.voltages])
    atomic_text(path, output.getvalue(), encoding='utf-8-sig')


def parse_rows(text, config, default_hold=0.1):
    """Parse bracketed voltage arrays or CSV/TSV rows in JSON electrode order.

    N columns means voltages only. N+1 means hold_s followed by the voltages.
    No row is returned until the entire pasted block has been validated.
    """
    rows = []
    n = len(config.electrodes)
    for line_number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        try:
            if line.lstrip().startswith('['):
                values = json.loads(line)
            else:
                fields = next(csv.reader([line], delimiter='\t' if '\t' in line else ','))
                if len(fields) == 1:
                    fields = re.split(r'\s+', line.strip())
                values = [float(v.strip()) for v in fields]
            if not isinstance(values, list) or len(values) not in (n, n + 1):
                raise ValueError(f'Expected {n} voltages or Hold (s) + {n} voltages.')
            hold, voltages = (default_hold, values) if len(values) == n else (values[0], values[1:])
            state = VoltageSet(config, tuple(voltages), name=f'Row {len(rows)+1}').validate()
            rows.append(SequenceRow(state, hold).validate())
            if len(rows) > MAX_ROWS:
                raise ValueError(f'Maximum {MAX_ROWS} rows.')
        except (ValueError, OverflowError, csv.Error) as exc:
            raise ValueError(f'Line {line_number}: {exc}') from exc
    if not rows:
        raise ValueError('Paste at least one voltage row.')
    return tuple(rows)


@dataclass(frozen=True)
class RunResult:
    status: str
    completed: int
    last_sent: VoltageSet | None
    elapsed_s: float
    error: str = ''


def run_sequence(session, sequence, stop_event, on_applied=None, on_writing=None, clock=time.monotonic,
                 *, options=None):
    """Stop at row boundaries; a row already writing always finishes its trigger.

    Hold starts when apply() returns. History/progress callback time counts
    toward hold; the next row still needs its own serial transfer time.
    """
    sequence.validate()
    options = (options or SequenceOptions()).validate()
    if sequence.config != session.config or not session.ready or session.closed:
        raise ValueError('Connect and initialize the matching device before running.')
    started = clock()
    completed, last_sent = 0, None
    try:
        for index, row in enumerate(sequence.rows, 1):
            if stop_event.is_set():
                return RunResult('stopped', completed, last_sent, clock() - started)
            if on_writing:
                on_writing(index)
            session.apply(row.state, use_ldac=sequence.use_ldac, profile='sequence',
                          sequence_options=options, force_full=(index == 1))
            applied = clock()
            completed, last_sent = index, row.state
            if on_applied:
                on_applied(index, row.state, applied - started)
            if stop_event.wait(max(0.0, applied + row.hold_s - clock())):
                return RunResult('stopped', completed, last_sent, clock() - started)
        return RunResult('completed', completed, last_sent, clock() - started)
    except Exception as exc:
        if not session.ready:
            last_sent = None
        return RunResult('failed', completed, last_sent, clock() - started, str(exc))


def execute_recorded_sequence(session, sequence, stop_event, preset_root, port,
                              on_applied=None, on_writing=None, *, options=None):
    """Persist the plan before sending, each applied target, and the run outcome."""
    sequence.validate()
    options = (options or SequenceOptions()).validate()
    kind = 'simulation' if session.simulation else 'hardware'
    device = sequence.config.device
    run_id = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    history = Path(preset_root) / 'history' / kind / device
    report = Path(preset_root) / 'sequences' / 'history' / kind / device / f'{run_id}_{device}.json'
    history.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryFile(dir=history):
        pass
    metadata = dict(record_type='sequence_run', mode=kind, port=port, run_id=run_id,
                    readback_verified=False, sequence_options=options.as_dict(),
                    timing='hold after checked UART transmit and LDAC command; no FPGA acknowledgement')
    atomic_json(report, sequence.as_dict(**metadata, status='running', completed_rows=0))
    records = []

    def applied(index, state, elapsed):
        written_ids = list(session.last_written_electrode_ids)
        records.append(dict(row=index, elapsed_s=elapsed, sent_at=datetime.now().astimezone().isoformat(),
                            written_electrode_ids=written_ids, transfer=dict(session.last_transfer)))
        if on_applied:
            on_applied(index, state, elapsed)
        atomic_json(history / f'{run_id}_sequence_{index:05d}_{device}.json',
                    state.as_dict(record_type='last_sent', mode=kind, port=port,
                                  readback_verified=False, use_ldac=sequence.use_ldac,
                                  transfer=dict(session.last_transfer), sequence_options=options.as_dict(),
                                  written_electrode_ids=written_ids,
                                  sequence_run_id=run_id, sequence_row=index))

    result = run_sequence(session, sequence, stop_event, applied, on_writing, options=options)
    try:
        atomic_json(report, sequence.as_dict(**metadata, status=result.status, completed_rows=result.completed,
                                            elapsed_s=result.elapsed_s, error=result.error, applied_rows=records))
    except OSError as exc:
        result = replace(result, status='failed', error=(result.error + '; ' if result.error else '') + f'Run report save failed: {exc}')
    return result
