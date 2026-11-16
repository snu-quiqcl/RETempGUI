"""Readable Queue output directories; step IDs remain stable execution identities."""
import re
import unicodedata
from pathlib import PurePosixPath


def component(name):
    name=unicodedata.normalize('NFC',name)
    name=re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', name).strip().rstrip('.')
    name=name[:60].rstrip(' .') or 'unnamed'
    if re.fullmatch(r'(?i)(CON|PRN|AUX|NUL|COM[1-9¹²³]|LPT[1-9¹²³])',name.split('.')[0]):
        name='_'+name
    return name


def allocate(name,used):
    base=component(name);candidate=base;number=2
    while candidate.casefold() in used:
        candidate=f'{base}__{number:02d}';number+=1
    used.add(candidate.casefold())
    return candidate


def directories(plan,steps):
    from .workflow_queue import is_group
    group_names={};job_names={};groups_used=set();jobs_used={}
    # Reserve the synthetic group before naming real groups to avoid collisions.
    if any(not is_group(item) for item in plan['jobs']):
        group_names[None]=allocate('Ungrouped',groups_used)
    for item in plan['jobs']:
        group=item['id'] if is_group(item) else None
        if group is not None:group_names[group]=allocate(item['name'],groups_used)
        used=jobs_used.setdefault(group,set())
        for job in item['jobs'] if is_group(item) else [item]:
            job_names[job['id']]=(allocate(job['name'],used),job['repeat'])
    result={}
    for step in steps:
        group=step.get('group_id');name,repeats=job_names[step['job_id']]
        path=PurePosixPath('groups',group_names[group])
        if plan['repeat']>1:path/=f"queue_repeat_{step['iteration']:04d}"
        path/=name
        path/=f"repeat_{step.get('group_iteration',step['job_repeat']):04d}"
        if group is not None and repeats>1:path/=f"run_{step['job_repeat']:04d}"
        result[step['step_id']]=path.as_posix()
    return result
