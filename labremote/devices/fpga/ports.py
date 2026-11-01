"""Enumerate without opening ports; remember only successful local connections."""
import json
import os
from PyQt5 import QtCore
from labremote.config.paths import CONFIG_ROOT

LOCAL = CONFIG_ROOT / 'fpga_ports.local.json'

def load_port(name):
    if not LOCAL.exists(): return {}
    data = json.loads(LOCAL.read_text(encoding='utf-8'))
    entry = data.get(name, {})
    if not isinstance(entry, dict): raise ValueError('Invalid saved FPGA port')
    return entry

def save_port(name, device, ports):
    data = json.loads(LOCAL.read_text(encoding='utf-8')) if LOCAL.exists() else {}
    info = next((p for p in ports if p['device'] == device), {})
    data[name] = {**info, 'device': device}
    temp = LOCAL.with_suffix('.tmp')
    temp.write_text(json.dumps(data, indent=2)+'\n', encoding='utf-8')
    os.replace(temp, LOCAL)

def remembered_device(saved, ports):
    # A unique USB serial can follow a changed COM number. Never guess by VID alone.
    if saved.get('serial_number'):
        matches = [p for p in ports if all(p.get(k) == saved.get(k) for k in ('serial_number', 'vid', 'pid'))]
        if len(matches) == 1: return matches[0]['device']
    return saved.get('device', '')

class PortScanner(QtCore.QThread):
    found = QtCore.pyqtSignal(object)
    failed = QtCore.pyqtSignal(str)
    def run(self):
        try:
            from serial.tools import list_ports
            self.found.emit([dict(device=p.device, description=p.description,
                                  serial_number=p.serial_number, vid=p.vid, pid=p.pid)
                             for p in sorted(list_ports.comports(), key=lambda p:p.device)])
        except Exception as exc: self.failed.emit(str(exc))
