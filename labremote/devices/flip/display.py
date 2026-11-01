"""Local presentation metadata only; never selects hardware or changes routes."""
import json
from pathlib import Path
from labremote.config.paths import CONFIG_ROOT

DEFAULT = CONFIG_ROOT/'ui/flipper_display.json'
LOCAL = CONFIG_ROOT/'ui/flipper_display.local.json'

def load_display():
    result={}
    for path in (DEFAULT,LOCAL):
        if not path.exists():continue
        data=json.loads(path.read_text(encoding='utf-8-sig'))
        if not isinstance(data,dict):raise ValueError('Flipper display must map server names to positions')
        for name,positions in data.items():
            if not isinstance(name,str) or not name.isidentifier() or not isinstance(positions,dict) or set(positions)-{'1','2'}:
                raise ValueError('Invalid flipper display name / position')
            for position,entry in positions.items():
                if not isinstance(entry,dict) or set(entry)-{'label','image'} or any(not isinstance(v,str) for v in entry.values()):
                    raise ValueError('Position display accepts label and image strings only')
                value={**result.get(name,{}).get(position,{}),**entry}
                if entry.get('image'):
                    image=Path(entry['image']).expanduser()
                    value['image']=str(image if image.is_absolute() else path.parent/image)
                result.setdefault(name,{})[position]=value
    return result
