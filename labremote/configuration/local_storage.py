"""Explicit local-file migration. Importing this module never moves files.

Run python -m labremote.configuration.local_storage to preview;
add --apply --backup <external-new-directory> to copy, verify and migrate.
"""
import argparse
import hashlib
import json
import shutil
from pathlib import Path


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def mappings(root):
    root = Path(root).resolve()
    pairs = [
        ('logs', 'labremote/data/logs'),
        ('data', 'labremote/data'),
        ('labremote/phase_shifter/calibrations', 'labremote/data/calibration/phase_shifter'),
        ('labremote/config/devices/fpga/workflows.local', 'labremote/workflow/local'),
        ('labremote/config/devices/fpga/workflows', 'labremote/workflow/local'),
        ('queue.local.json', 'labremote/config/queues/queue.json'),
    ]
    for chamber in ('EA', 'EC'):
        for kind in ('presets', 'sequences'):
            pairs.append((f'labremote/data/dac/{chamber}/{kind}', f'labremote/config/{kind}/dac/{chamber}'))
    pairs += [(str(p.relative_to(root)), 'labremote/config/examples/' + p.name)
              for p in (root/'docs/examples').glob('*') if p.suffix.lower() in ('.json','.yml','.yaml')]
    pairs += [(p.name, 'labremote/data/verification/' + p.name) for p in root.glob('*.png')]
    return [(root / a, root / b) for a, b in pairs]


def plan(root):
    root = Path(root).resolve()
    moves = []
    for source, target in mappings(root):
        if not source.exists():
            continue
        files = sorted(source.rglob('*')) if source.is_dir() else [source]
        for file in files:
            if file.is_symlink() or (getattr(file.stat(), 'st_file_attributes', 0) & 0x400):
                raise ValueError(f'Linked path requires manual migration: {file}')
            if not file.is_file():
                continue
            destination = target / file.relative_to(source) if source.is_dir() else target
            if not file.resolve().is_relative_to(root) or not destination.resolve().is_relative_to(root):
                raise ValueError('Migration path outside project')
            moves.append((file, destination))
    destinations = {}
    for source, target in moves:
        sha = digest(source)
        previous = destinations.setdefault(target, sha)
        if previous != sha or (target.exists() and digest(target) != sha):
            raise ValueError(f'Migration conflict; both originals retained: {source} -> {target}')
    return moves


def remap_paths(value, root, pairs=None):
    """Change only paths pointing into this project's known legacy folders."""
    if pairs is None:
        pairs = sorted(mappings(root), key=lambda pair: len(str(pair[0])), reverse=True)
    if isinstance(value, dict):
        return {k: remap_paths(v, root, pairs) for k, v in value.items()}
    if isinstance(value, list):
        return [remap_paths(v, root, pairs) for v in value]
    if not isinstance(value, str):
        return value
    normalized = value.replace('\\', '/')
    for source, target in pairs:
        for old, new in [(source.as_posix(), target.as_posix()),
                         ('${PROJECT_ROOT}/' + source.relative_to(root).as_posix(), '${PROJECT_ROOT}/' + target.relative_to(root).as_posix())]:
            if normalized.casefold() == old.casefold() or normalized.casefold().startswith(old.casefold() + '/'):
                return new + normalized[len(old):]
    return value


def migrate_storage(root, backup=None, apply=False):
    root = Path(root).resolve()
    moves = plan(root)  # Preflight every conflict before any changes.
    edits = []
    config = root / 'labremote/config'
    for path in sorted(config.rglob('*.json')):
        value = json.loads(path.read_text(encoding='utf-8-sig'))
        changed = remap_paths(value, root)
        if value != changed:
            edits.append((path, changed))
    report = {'moves': [(str(a.relative_to(root)), str(b.relative_to(root))) for a, b in moves],
              'path_updates': [str(p.relative_to(root)) for p, _ in edits]}
    if not apply:
        return report
    if backup is None:
        raise ValueError('--apply requires an external --backup directory')
    backup = Path(backup).resolve()
    if backup == root or backup.is_relative_to(root):
        raise ValueError('Backup must be outside the repository')
    backup.mkdir(parents=True, exist_ok=False)
    originals = {p for p, _ in moves} | {p for p in config.rglob('*') if p.is_file()}
    hashes = {}
    for source in sorted(originals):
        rel = source.relative_to(root)
        target = backup / 'files' / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        sha = digest(source)
        shutil.copy2(source, target)
        if digest(target) != sha or digest(source) != sha:
            raise OSError(f'Backup validation failed: {source}')
        hashes[rel.as_posix()] = sha
    (backup / 'manifest.json').write_text(json.dumps(hashes, indent=2), encoding='utf-8')
    (backup / 'migration.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    # Copy and verify the entire batch before removing any original.
    for source, target in moves:
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            shutil.copy2(source, target)
        if digest(source) != hashes[source.relative_to(root).as_posix()] or digest(target) != digest(source):
            raise OSError(f'Migration validation failed: {source}')
    for source, target in moves:
        if digest(source) != digest(target):
            raise OSError(f'File changed during migration: {source}')
        source.unlink()
    for path, value in edits:
        temporary = path.with_name(path.name + '.migration.tmp')
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        temporary.replace(path)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--backup', type=Path)
    args = parser.parse_args()
    report = migrate_storage(args.root, args.backup, args.apply)
    print(json.dumps({'files': len(report['moves']), 'path_updates': report['path_updates'],
                      'applied': args.apply, 'backup': str(args.backup) if args.backup else None}, indent=2))


if __name__ == '__main__':
    main()
