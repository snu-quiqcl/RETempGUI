"""Read-only pre-upload scan. Reports locations, never secret values.

Scans tracked working files and non-ignored new files, not historical commits.
Run before committing in GitHub Desktop. This is a guard, not a complete secret scanner.
"""
import ipaddress
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parent
PRIVATE_FILES = {'local_settings.bat', 'labremote/config/client_settings.json',
                 'labremote/config/local_hardware.json', 'server_deploy_latest/KDC101/serials.local.json'}


def main():
    result = subprocess.run(['git', '-C', str(ROOT), 'ls-files', '--cached', '--others',
                             '--exclude-standard', '-z'], check=True, stdout=subprocess.PIPE)
    names = set(result.stdout.decode('utf-8').split('\0')) - {''}
    private_values = set()
    for name in ('labremote/config/local_hardware.json', 'server_deploy_latest/KDC101/serials.local.json'):
        path = ROOT/name
        if path.exists():
            data = json.loads(path.read_text(encoding='utf-8-sig'))
            private_values.update(str(v) for k,v in data.items() if v is not None and
                                  (k.endswith('_host') or name.endswith('serials.local.json')))
    private_values.difference_update({'127.0.0.1', 'localhost'})
    networks = [ipaddress.ip_network(prefix) for prefix in ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16')]
    findings = set()
    for name in names:
        path = ROOT/name
        if name.split('/')[0] in ('tests', 'server_deploy_latest') or name in PRIVATE_FILES or path.name.endswith(('.local.json', '.local.yml', '.local.yaml')):
            findings.add((name, 0, 'private file selected for Git'))
        if not path.is_file(): continue
        text = path.read_bytes().decode('utf-8', errors='replace')
        for line_no, line in enumerate(text.splitlines(), 1):
            if name != Path(__file__).name:
                for candidate in re.findall(r'(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])', line):
                    try: address = ipaddress.ip_address(candidate)
                    except ValueError: continue
                    if any(address in network for network in networks):
                        findings.add((name, line_no, 'private network address'))
            if any(re.search(r'(?<![\w.])' + re.escape(value) + r'(?![\w.])', line) for value in private_values):
                findings.add((name, line_no, 'local hardware value'))
            if re.search(r'(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{30,}|AKIA[A-Z0-9]{16}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----)', line):
                findings.add((name, line_no, 'credential pattern'))
            if re.search(r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}', line):
                findings.add((name, line_no, 'email address; review attribution before editing'))
    for name, line, kind in sorted(findings): print(f'{name}:{line}: {kind}')
    print(f'Scanned {len(names)} Git candidate files; {len(findings)} findings. History not scanned.')
    return bool(findings)


if __name__ == '__main__': raise SystemExit(main())
