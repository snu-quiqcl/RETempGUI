"""Validate this checkout without connecting real instruments.

Each test module gets a separate process to isolate Qt/global runtime state.
Default: source/config/document checks (also available in a fresh clone).
core/all/--module require the separately copied tests/ and server_deploy_latest/.
Generated reports live in .verification/, which is excluded from Git.
"""
import argparse
import ast
import json
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
CORE = ['test_v7_ccd', 'test_v6_runtime', 'test_v6_workflow_editor',
        'test_v6_architecture', 'test_v6_review_regressions']


def environment():
    env = os.environ.copy()
    env.update(QT_QPA_PLATFORM='offscreen', PYTHONIOENCODING='utf-8', PYTHONDONTWRITEBYTECODE='1')
    candidates = [Path(env['IS_ROOT'])] if env.get('IS_ROOT') else []
    for parent in ROOT.parents:
        candidates.extend([parent/'instrumentserver-remote_entanglement/instrumentserver-remote_entanglement',
                           parent/'instrumentserver-remote_entanglement'])
    for path in candidates:
        if (path/'instrumentserver/__init__.py').is_file():
            env['PYTHONPATH'] = str(path)+os.pathsep+env.get('PYTHONPATH', '')
            break
    return env


def checks():
    parsed = 0
    for folder in ('labremote', 'tests', 'server_deploy_latest'):
        for path in (ROOT/folder).rglob('*.py'):
            ast.parse(path.read_text(encoding='utf-8-sig'), filename=str(path))
            parsed += 1
    from labremote.config.device_config import preload_device_configs
    from labremote.runtime.parameters import registry
    preload_device_configs()
    registry()
    from labremote.config.roles import scan_roles
    from labremote.config import equipment
    from labremote.config.paths import CONFIG_ROOT
    from labremote.devices.flip.settings import validate_settings
    scan_roles()
    equipment.load(CONFIG_ROOT/'ui/equipment.json')
    validate_settings(json.loads((CONFIG_ROOT/'operations/flipper_routes.json').read_text(encoding='utf-8')))
    missing = []
    for path in [ROOT/'README.md', * (ROOT/'docs').glob('*.md')]:
        for target in re.findall(r'\]\(([^)]+)\)', path.read_text(encoding='utf-8')):
            if '://' in target or target.startswith('#'): continue
            target = target.split('#')[0]
            if target and not (path.parent/target).exists(): missing.append(str(path.relative_to(ROOT))+': '+target)
    if missing: raise ValueError('Broken document links: '+str(missing))
    return {'parsed_python_files': parsed, 'device_configs': 'valid', 'document_links': 'valid',
            'local_support_folders': {name: (ROOT/name).is_dir() for name in ('tests', 'server_deploy_latest')}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--suite', choices=('checks', 'core', 'all', 'ccd-gui'), default='checks')
    parser.add_argument('--timeout', type=int, default=180, help='Maximum seconds per test module')
    parser.add_argument('--module', action='append', help='Rerun a named test module (without tests. prefix)')
    args = parser.parse_args()
    if args.module or args.suite in ('core', 'all'):
        required = ('tests', 'server_deploy_latest')
        missing = [name for name in required if not (ROOT/name).is_dir()]
        if missing:
            parser.error('Local regression tests require tests/ and server_deploy_latest/. '
                         'Copy both folders privately to this checkout; they are excluded from Git. '
                         'Without them, use --suite checks or --suite ccd-gui.')
        if not any((ROOT/'tests').glob('test_*.py')):
            parser.error('Local tests/ contains no test modules; restore the local test bundle.')
    os.chdir(ROOT)
    output = ROOT/'.verification'; output.mkdir(exist_ok=True)
    report = {'checks': checks(), 'suite': args.suite, 'modules': []}
    env = environment()
    modules = CORE if args.suite == 'core' else sorted(p.stem for p in (ROOT/'tests').glob('test_*.py')) if args.suite == 'all' else []
    if args.module:
        if any(not name.isidentifier() or not (ROOT/'tests'/(name+'.py')).is_file() for name in args.module):
            parser.error('Unknown test module')
        modules = args.module
        report['suite'] = 'selected'
    runs = [(name, [sys.executable, '-B', '-c',
        'import faulthandler,unittest,sys; faulthandler.dump_traceback_later('+str(max(10,args.timeout-5))+',exit=True); unittest.main(module=None,argv=["unittest","-v",sys.argv[1]])',
        'tests.'+name]) for name in modules]
    if args.suite == 'ccd-gui': runs.append(('ccd_gui', [sys.executable, '-B', 'verify_ccd_v7.py']))
    for name, command in runs:
        try:
            result = subprocess.run(command, cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    text=True, encoding='utf-8', errors='replace', timeout=args.timeout)
            status, text, code = 'passed' if result.returncode == 0 else 'failed', result.stdout, result.returncode
        except subprocess.TimeoutExpired as exc:
            status, text, code = 'timeout', exc.stdout or b'', None
            if isinstance(text, bytes): text = text.decode('utf-8', errors='replace')
        (output/(name+'.log')).write_text(text, encoding='utf-8')
        count = re.search(r'Ran (\d+) tests?', text)
        item = {'module': name, 'status': status, 'tests': int(count[1]) if count else None, 'exit_code': code}
        report['modules'].append(item)
        print(json.dumps(item), flush=True)
    report['passed'] = all(item['status'] == 'passed' for item in report['modules'])
    (output/(report['suite']+'.json')).write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps({'checks': report['checks'], 'passed': report['passed']}), flush=True)
    return 0 if report['passed'] else 1


if __name__ == '__main__': raise SystemExit(main())
