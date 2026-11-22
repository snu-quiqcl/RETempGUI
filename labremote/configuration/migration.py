"""One-time, lossless migration of private settings; no device I/O."""
import json
from pathlib import Path

PRIVATE_PATHS = {
 'client_settings.json':'ui/client_settings.local.json',
 'equipment.local.json':'ui/equipment.local.json',
 'local_hardware.json':'devices/connections.local.json',
 'fpga_ports.local.json':'devices/fpga/ports.local.json',
 'flip.local.json':'operations/flipper_routes.local.json',
 'oven.local.json':'operations/oven.local.json',
}

def migrate(root):
    root=Path(root)
    pairs=dict(PRIVATE_PATHS)
    pairs.update({p.name:'ui/'+p.name for p in root.glob('scan_*.local.json')})
    # Preflight all conflicts before moving any file.
    for old,new in pairs.items():
        source,target=root/old,root/new
        if source.exists() and target.exists() and source.read_bytes()!=target.read_bytes():
            raise ValueError(f'Configuration migration conflict: {source} / {target}; keep both and choose the intended settings')
    for old,new in pairs.items():
        source,target=root/old,root/new
        if not source.exists():continue
        target.parent.mkdir(parents=True,exist_ok=True)
        if target.exists():source.unlink() # identical bytes were checked above
        else:source.rename(target)
    settings=root/'ui/client_settings.local.json'
    if settings.exists():
        try:data=json.loads(settings.read_text(encoding='utf-8-sig'))
        except (ValueError, OSError):return
        if not isinstance(data,dict):return
        requested=data.get('equipment_configuration')
        if requested and Path(requested)==root/'equipment.local.json':
            data['equipment_configuration']=str(root/'ui/equipment.local.json')
            temp=settings.with_suffix('.tmp')
            temp.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
            temp.replace(settings)
