"""Append-only PID CSV independent of the GUI's bounded plot history."""
import csv
import json
import re
import time
from datetime import datetime, timezone
from labremote.data_paths import DATA_ROOT, tab_data_directory

FIELDS = ('time_utc', 'elapsed_s', 'phase', 'request_id', 'raw_thz', 'fit_thz',
          'fit_error', 'selected_thz', 'measured_thz', 'raw_mean_thz', 'fit_mean_thz', 'raw_moving_mean_thz', 'moving_count', 'batch_collected', 'batch_size',
          'samples', 'voltage_before_v', 'voltage_v', 'target_thz', 'error_ghz',
          'peak_dbm', 'snr_db', 'axis', 'osa_name', 'use_fit', 'average_count',
          'kp_v_per_ghz', 'ki_v_per_ghz_s', 'kd_v_s_per_ghz', 'outcome')

class PIDLog:
    def __init__(self, name, settings):
        self.origin = time.monotonic()
        safe_name = re.sub(r'[^A-Za-z0-9_-]', '_', str(name)) or 'mdt'
        folder = tab_data_directory(None, 'pid', safe_name)
        folder.mkdir(parents=True, exist_ok=True)
        self.path = folder / (datetime.now().strftime('%Y%m%d_%H%M%S_%f') + '.csv')
        self.path.with_suffix('.json').write_text(json.dumps(settings, indent=2, ensure_ascii=False), encoding='utf-8')
        self.file = self.path.open('x', newline='', encoding='utf-8')
        self.writer = csv.DictWriter(self.file, fieldnames=FIELDS, extrasaction='ignore')
        self.writer.writeheader(); self.file.flush()
        self.last_voltage = None

    def write(self, data, settings):
        if data.get('voltage_v') is not None: self.last_voltage = data['voltage_v']
        row = {key: value for key, value in settings.items() if key in FIELDS}
        row.update(voltage_v=self.last_voltage)
        row.update(data)
        row.update(time_utc=datetime.now(timezone.utc).isoformat(timespec='milliseconds'),
                   elapsed_s=time.monotonic()-self.origin)
        self.writer.writerow(row)
        self.file.flush()

    def close(self):
        self.file.close()
