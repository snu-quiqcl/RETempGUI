"""Fail before GUI/device imports when the local configuration bundle is absent."""
from .paths import CONFIG_ROOT

def require_local_configuration():
    required = ('ui/defaults.json', 'ui/equipment.json', 'devices/connections.json',
                'ui/input_defaults.json')
    missing = [name for name in required if not (CONFIG_ROOT / name).is_file()]
    if not list(CONFIG_ROOT.glob('operations/*/parameter_registry.yml')):
        missing.append('operations/*/parameter_registry.yml')
    if missing:
        raise FileNotFoundError(
            'Local configuration is missing. Restore this PC\'s config backup to '
            + str(CONFIG_ROOT) + '\nMissing: ' + ', '.join(missing)
            + '\nSee docs/configuration/LOCAL_STORAGE.md. No device connection was started.')
