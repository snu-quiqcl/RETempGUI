"""Consolidate old override files explicitly; preview by default, never on import.

python -B -m labremote.configuration.migration --apply --backup D:/outside/repo/backup
"""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil

LEGACY = {
    'client_settings.json': 'ui/client_settings.json',
    'equipment.local.json': 'ui/equipment.json',
    'local_hardware.json': 'devices/connections.json',
    'fpga_ports.local.json': 'devices/fpga/ports.json',
    'flip.local.json': 'operations/flipper_routes.json',
    'oven.local.json': 'operations/oven.json',
}

def canonical(name):
    return '/'.join(part.removesuffix('.local').replace('.local.', '.') for part in name.split('/'))

def overlay(base, override, deep=False):
    if not isinstance(base, dict) or not isinstance(override, dict):
        return deepcopy(override)
    result = deepcopy(base)
    for key, value in override.items():
        result[key] = overlay(result.get(key), value, True) if deep and isinstance(value, dict) else deepcopy(value)
    return result

def _encode(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode('utf-8')

def plan(root):
    root = Path(root).resolve()
    config = root / 'labremote/config'
    originals = {p: p.read_bytes() for p in config.rglob('*') if p.is_file() and '__pycache__' not in p.parts}
    serials = root / 'server_deploy_latest/KDC101/serials.local.json'
    if serials.exists():
        originals[serials] = serials.read_bytes()
        target = serials.with_name('serials.json')
        if target.exists(): originals[target] = target.read_bytes()
    for path in originals:
        if path.is_symlink() or not path.resolve().is_relative_to(root):
            raise ValueError(f'Linked or external configuration: {path}')
    documents = {}
    for path, raw in originals.items():
        if path.suffix == '.json':
            value = json.loads(raw.decode('utf-8-sig'))
            documents[path] = value
    final = dict(originals)
    moves = {}
    sources = sorted(originals, key=lambda p: ('.local' in p.name, len(p.parts), str(p)))
    for source in sources:
        if source.is_relative_to(config):
            relative = source.relative_to(config).as_posix()
            destination = config / LEGACY.get(relative, canonical(relative))
            if source.parent == config and source.name.startswith('scan_'):
                destination = config / 'ui' / canonical(source.name)
        else:
            destination = source.with_name(canonical(source.name))
        if source == destination: continue
        if source.suffix != '.json':
            if destination in final and final[destination] != final[source]:
                raise ValueError(f'Conflicting non-JSON configuration: {source} / {destination}')
            final[destination] = final[source]
        else:
            value = documents[source]
            if destination in final:
                base = json.loads(final[destination].decode('utf-8-sig'))
                relative = destination.relative_to(config).as_posix() if destination.is_relative_to(config) else ''
                if relative in ('ui/flipper_display.json', 'ui/tab_descriptions.json'):
                    value = overlay(base, value, True)
                elif relative == 'operations/flipper_routes.json':
                    value = overlay(base, value)
                # Other readers used the complete override document.
            final[destination] = _encode(value)
        final.pop(source)
        moves[source] = destination

    def merge_into(old, new, field=None):
        source, destination = config / old, config / new
        if source not in final: return
        base = json.loads(final[source].decode('utf-8-sig'))
        current = json.loads(final[destination].decode('utf-8-sig')) if destination in final else {}
        if field:
            current.setdefault(field, base)
            result = current
        else:
            if old == 'operations/defaults/oven.json' and 'photoionization_shutter' not in current and 'shutter' in current:
                current['photoionization_shutter'] = current['shutter']
            result = overlay(base, current)
        final[destination] = _encode(result)
        final.pop(source)
        moves[source] = destination

    merge_into('operations/defaults/oven.json', 'operations/oven.json')
    merge_into('operations/defaults/oven_power.json', 'operations/oven.json', 'power')
    merge_into('ui/defaults.json', 'ui/client_settings.json')
    client = config / 'ui/client_settings.json'
    if client in final:
        data = json.loads(final[client].decode('utf-8-sig'))
        data.pop('server_host', None); data.pop('server_port', None)
        final[client] = _encode(data)

    path_moves = dict(moves)
    for source in moves:
        for parent in source.parents:
            if parent == config or not parent.is_relative_to(config): break
            destination = config / canonical(parent.relative_to(config).as_posix())
            if parent != destination: path_moves[parent] = destination

    def remap(value, owner):
        if isinstance(value, dict): return {k: remap(v, owner) for k, v in value.items()}
        if isinstance(value, list): return [remap(v, owner) for v in value]
        if not isinstance(value, str): return value
        normalized = value.replace('\\', '/')
        for source, destination in path_moves.items():
            candidates = [(source.as_posix(), destination.as_posix())]
            if source.is_relative_to(owner) and destination.is_relative_to(owner):
                candidates.append((source.relative_to(owner).as_posix(), destination.relative_to(owner).as_posix()))
            if source.is_relative_to(config) and destination.is_relative_to(config):
                candidates += [(source.relative_to(config).as_posix(), destination.relative_to(config).as_posix()),
                               (source.relative_to(root).as_posix(), destination.relative_to(root).as_posix())]
                marker = '/labremote/config/'
                if marker in normalized:
                    prefix, suffix = normalized.split(marker, 1)
                    if suffix == source.relative_to(config).as_posix():
                        return prefix + marker + destination.relative_to(config).as_posix()
            for old, new in candidates:
                if normalized.casefold() == old.casefold(): return new
        for old, new in (('/settings.local/', '/settings/'), ('/workflows.local/', '/workflows/')):
            if normalized.startswith(config.as_posix() + '/') and old in normalized:
                return normalized.replace(old, new)
        return value

    for path in tuple(final):
        if path.suffix == '.json':
            value = json.loads(final[path].decode('utf-8-sig'))
            updated = remap(value, path.parent)
            if value != updated: final[path] = _encode(updated)
    writes = {p: raw for p, raw in final.items() if originals.get(p) != raw}
    removals = set(originals) - set(final)
    return originals, writes, removals, moves

def migrate(root, *, backup=None, apply=False):
    root = Path(root).resolve()
    originals, writes, removals, moves = plan(root)
    report = {'writes': [p.relative_to(root).as_posix() for p in sorted(writes)],
              'removed': [p.relative_to(root).as_posix() for p in sorted(removals)],
              'moves': {a.relative_to(root).as_posix(): b.relative_to(root).as_posix() for a,b in moves.items()}}
    if not apply or not (writes or removals): return report
    if backup is None: raise ValueError('Applying requires an external backup directory')
    backup = Path(backup).resolve()
    if backup == root or backup.is_relative_to(root): raise ValueError('Backup must be outside the repository')
    backup.mkdir(parents=True, exist_ok=False)
    hashes = {}
    for source, raw in originals.items():
        target = backup / 'files' / source.relative_to(root)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
        if target.read_bytes() != raw: raise OSError(f'Backup verification failed: {source}')
        hashes[source.relative_to(root).as_posix()] = hashlib.sha256(raw).hexdigest()
    (backup / 'manifest.json').write_bytes(_encode(hashes))
    (backup / 'migration.json').write_bytes(_encode(report))
    for path, raw in originals.items():
        if path.read_bytes() != raw: raise RuntimeError(f'Configuration changed during backup: {path}')
    for path in writes:
        if not path.resolve().is_relative_to(root): raise ValueError('Destination outside project')
        if path not in originals and path.exists(): raise RuntimeError(f'Destination appeared: {path}')
    touched = []
    try:
        for path, raw in writes.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_name(path.name + '.merge.tmp')
            temporary.write_bytes(raw)
            temporary.replace(path); touched.append(path)
            if path.read_bytes() != raw: raise OSError(f'Write verification failed: {path}')
        for source in removals:
            if source.read_bytes() != originals[source]: raise RuntimeError(f'Original changed: {source}')
            source.unlink(); touched.append(source)
    except BaseException:
        for path in reversed(touched):
            if path in originals: path.write_bytes(originals[path])
            elif path.exists(): path.unlink()
        raise
    for path in sorted((root / 'labremote/config').rglob('*.local'), key=lambda p: len(p.parts), reverse=True):
        if path.is_dir() and not any(path.iterdir()): path.rmdir()
    return report

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--backup', type=Path)
    args = parser.parse_args()
    print(json.dumps(migrate(args.root, backup=args.backup, apply=args.apply), ensure_ascii=False, indent=2))

if __name__ == '__main__': main()
