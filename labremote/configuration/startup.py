"""Fail before GUI/device imports when the local configuration bundle is absent."""
from .paths import CONFIG_ROOT

def require_local_configuration():
    required = ('ui/defaults.json', 'ui/equipment.json', 'devices/connections.json',
                'ui/input_defaults.json')
    missing = [name for name in required if not (CONFIG_ROOT / name).is_file()]
    if not list(CONFIG_ROOT.glob('operations/*/parameter_registry.yml')):
        missing.append('operations/*/parameter_registry.yml')
    profiles=('phase_ramsey','phase_rabi','oven','oven_power','dac_timing','hom','entanglement','ion_check')
    profiles+=tuple(prefix+'_'+c for c in ('EA','EC') for prefix in ('micromotion','secular','rabi','initialization','ramsey','spin_echo','spam'))
    profiles+=tuple('decay_'+c+'_'+m for c in ('EA','EC') for m in ('171_single','174_single','171_dual','174_dual'))
    missing.extend('operations/defaults/'+name+'.json' for name in profiles if not (CONFIG_ROOT/'operations/defaults'/(name+'.json')).is_file())
    if missing:
        raise FileNotFoundError(
            'Local configuration is missing. Restore this PC\'s config backup to '
            + str(CONFIG_ROOT) + '\nMissing: ' + ', '.join(missing)
            + '\nSee docs/configuration/TAB_SETTINGS.md (export the old PC defaults before updating). No device connection was started.')
