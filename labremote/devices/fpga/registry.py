"""Local USB identity registry and in-process duplicate-port exclusion."""
import json
import threading
from .mapping import ROOT, default_document, Profile, save_profile

LOCK = threading.RLock()
CLAIMS = {}
LOCAL = ROOT / 'registry.local.json'


def claim_port(port, worker):
    key = port.strip().upper()
    if not key:
        raise ValueError('Select a serial port')
    with LOCK:
        owner = CLAIMS.get(key)
        if owner is not None and owner is not worker:
            raise RuntimeError('Port already connected by ' + owner.profile.alias)
        CLAIMS[key] = worker


def release_port(worker):
    with LOCK:
        for key in [k for k, w in CLAIMS.items() if w is worker]:
            del CLAIMS[key]


def read():
    return json.loads(LOCAL.read_text(encoding='utf-8')) if LOCAL.exists() else {'schema_version': 1, 'devices': {}}


def identify(info, ports, alias=None):
    """Persist a unique USB serial; unidentified devices get new sequential IDs.

    Fallback order is intentionally not treated as stable hardware identity.
    """
    with LOCK:
        document = read()
        serial = info.get('serial_number')
        unique = bool(serial) and sum(p.get('serial_number') == serial for p in ports) == 1
        identity = [info.get('vid'), info.get('pid'), serial] if unique else None
        if identity is not None:
            for name, entry in document['devices'].items():
                if entry.get('usb_identity') == identity:
                    return name, True
        number = 1
        while 'fpga_' + str(number) in document['devices'] or (ROOT / ('fpga_' + str(number) + '.local.json')).exists():
            number += 1
        name = 'fpga_' + str(number)
        profile = default_document(name)
        profile['alias'] = alias or 'FPGA ' + str(number)
        profile = Profile(profile)
        for entry in document['devices'].values():
            if entry['alias'].casefold() == profile.alias.casefold():
                raise ValueError('FPGA alias already exists')
        document['devices'][name] = dict(usb_identity=identity, alias=profile.alias, last_port=info['device'])
        save_profile(profile)
        LOCAL.parent.mkdir(parents=True, exist_ok=True)
        temp = LOCAL.with_suffix('.tmp')
        temp.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding='utf-8')
        temp.replace(LOCAL)
        return name, unique
