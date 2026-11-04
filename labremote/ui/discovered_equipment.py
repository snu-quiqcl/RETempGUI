"""Merge discovered membership without changing hardware settings or existing choices."""
from copy import deepcopy
from labremote.config.equipment import FAMILY_GROUP, validate

AUTO_FAMILIES = frozenset({'windfreak', 'sg384', 'anapico', 'dds4', 'flip', 'oven_relay'})
SERVER_FAMILIES = {
    'windfreak_synthhd': 'windfreak', 'srs_sg384': 'sg384',
    'anapico_apsyn420': 'anapico', 'dds4_ad9912_vva': 'dds4',
    'rigol_ds1052e': 'ds1052e', 'rigol_mso7054': 'mso7054',
    'thermotek_t257p': 'thermotek', 'keithley_2231a': 'keithley',
    'yokogawa_aq6373': 'osa', 'mdt693b': 'mdt',
    'thorlabs_mff': 'flip', 'trap_dac81416': 'dac', 'oven_relay': 'oven_relay',
}

def discovery_candidates(descriptors):
    result = {}
    for descriptor in descriptors:
        family = SERVER_FAMILIES.get(descriptor.family)
        if family and descriptor.name.isidentifier():
            result[family, descriptor.name] = dict(family=family, name=descriptor.name,
                group=FAMILY_GROUP[family], enabled=False)
    return list(result.values())

def merge_discovered(document, candidates):
    result = deepcopy(document)
    entries = result['devices']
    known = {(e['family'], e['name']) for e in entries}
    relay_candidates = [e for e in candidates if e['family'] == 'oven_relay']
    notes = []
    for candidate in candidates:
        family, name = candidate['family'], candidate['name']
        if family not in AUTO_FAMILIES or (family, name) in known:
            continue
        if any(e['name'] == name and e['family'] != family for e in entries):
            notes.append(name + ': 장비 종류가 기존 구성과 다릅니다. 구성을 확인하세요.')
            continue
        if family == 'oven_relay' and (len(relay_candidates) != 1 or any(e['family'] == family for e in entries)):
            notes.append(name + ': 공유 relay를 자동 선택할 수 없습니다. 구성에서 사용할 relay 하나를 지정하세요.')
            continue
        entries.append(dict(candidate, enabled=True))
        known.add((family, name))
    return validate(result), notes
