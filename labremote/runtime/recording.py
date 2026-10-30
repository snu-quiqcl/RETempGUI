"""Per-run configuration/result files and optional durable protocol I/O logs."""
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import threading
from uuid import uuid4

from labremote.runtime.errors import OperationCancelled

DEFAULT_RUNS = Path(__file__).resolve().parents[2] / 'logs' / 'operations'
_lock = threading.Lock()
_detailed = False


def set_detailed_logging(enabled):
    global _detailed
    with _lock:
        _detailed = bool(enabled)


def detailed_logging():
    with _lock:
        return _detailed


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def log_value(value):
    if isinstance(value, float) and not math.isfinite(value):
        return repr(value)
    if isinstance(value, dict):
        return {key: log_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [log_value(item) for item in value]
    return value


def write_json(path, value):
    temporary = path.with_suffix('.tmp')
    with temporary.open('w', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


class RunRecord:
    def __init__(self, operation, configuration, *, root=None, detailed=None):
        self.run_id = uuid4().hex
        self.started_at = timestamp()
        self.detailed = detailed_logging() if detailed is None else bool(detailed)
        self.path = Path(root if root is not None else DEFAULT_RUNS) / operation / self.run_id
        self.path.mkdir(parents=True, exist_ok=False)
        self.sequence = 0
        self.configuration = {**configuration, 'run_id': self.run_id,
                              'detailed_logging': self.detailed}
        # These writes must succeed before any instrument I/O.
        write_json(self.path / 'configuration.json', self.configuration)
        self.result = {'run_id': self.run_id, 'operation': operation,
                       'started_at': self.started_at, 'status': 'running',
                       'value': None, 'error': None}
        write_json(self.path / 'result.json', self.result)
        self.event('run_started')

    def event(self, event, **data):
        if not self.detailed:
            return
        self.sequence += 1
        row = dict(sequence=self.sequence, time=timestamp(), event=event, **data)
        # Non-finite readbacks are logged as strings; the protocol rejects them.
        line = json.dumps(log_value(row), ensure_ascii=False, default=repr, allow_nan=False)
        with (self.path / 'events.jsonl').open('a', encoding='utf-8') as stream:
            stream.write(line + '\n')
            stream.flush()
            os.fsync(stream.fileno())

    def finish(self, value=None, error=None):
        status = ('cancelled' if isinstance(error, OperationCancelled) else
                  'failed' if error is not None else 'succeeded')
        result = dict(self.result, finished_at=timestamp(), status=status,
                      value=value if error is None else None,
                      error=None if error is None else {
                          'type': type(error).__name__, 'message': str(error)})
        write_json(self.path / 'result.json', result)
        self.event('run_finished', status=status)



from contextvars import ContextVar
CURRENT_RECORD = ContextVar('operation_record', default=None)


def record_io(event, **data):
    context = CURRENT_RECORD.get()
    if context is None: return
    record, report_error = context
    try: record.event(event, **data)
    except Exception as error:
        # Logging errors must not turn a completed hardware write into a failed write.
        report_error(str(error))
