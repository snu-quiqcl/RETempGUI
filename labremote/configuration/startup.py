"""Validate the PC configuration before importing GUI or device modules."""
from .paths import CONFIG_ROOT

def require_local_configuration():
    legacy = sorted(p for p in CONFIG_ROOT.rglob('*') if p.is_file() and ('.local.' in p.name or any(part.endswith('.local') for part in p.relative_to(CONFIG_ROOT).parts)))
    old_defaults = [CONFIG_ROOT/'ui/defaults.json', CONFIG_ROOT/'operations/defaults/oven.json',
                    CONFIG_ROOT/'operations/defaults/oven_power.json']
    if legacy or any(p.exists() for p in old_defaults):
        raise ValueError('Configuration consolidation is required. Close the GUI and run '
                         'python -B -m labremote.configuration.migration --apply --backup <external-backup-directory>. '
                         'Existing values are backed up before consolidation; no device connection was started.')
    required = ('ui/client_settings.json', 'ui/equipment.json', 'ui/input_defaults.json',
                'devices/connections.json', 'operations/oven.json')
    missing = [name for name in required if not (CONFIG_ROOT/name).is_file()]
    if not list(CONFIG_ROOT.glob('operations/*/parameter_registry.yml')):
        missing.append('operations/*/parameter_registry.yml')
    profiles = ('phase_ramsey','phase_rabi','dac_timing','hom','entanglement','ion_check')
    profiles += tuple(prefix+'_'+c for c in ('EA','EC') for prefix in ('micromotion','secular','rabi','initialization','ramsey','spin_echo','spam'))
    profiles += tuple('decay_'+c+'_'+m for c in ('EA','EC') for m in ('171_single','174_single','171_dual','174_dual'))
    missing.extend('operations/defaults/'+name+'.json' for name in profiles if not (CONFIG_ROOT/'operations/defaults'/(name+'.json')).is_file())
    if missing:
        raise FileNotFoundError('Restore this PC configuration backup to '+str(CONFIG_ROOT)+'\nMissing: '+', '.join(missing))
    from .local_hardware import server_endpoint
    server_endpoint()
    from labremote.devices.oven.settings import load_settings
    load_settings()
