"""Per-tab drafts, with a read-only legacy fallback and conflict detection."""
import hashlib
import json
import os
import re
from pathlib import Path

def component(value):
    safe=re.sub(r'[^a-zA-Z0-9_.-]', '_', value)
    if safe!=value or not safe or safe.upper().split('.')[0] in {'CON','PRN','AUX','NUL',*(f'COM{i}' for i in range(10)),*(f'LPT{i}' for i in range(10))} or safe in ('.','..'):
        safe=(safe[:60] or 'tab')+'-'+hashlib.sha256(value.encode()).hexdigest()[:12]
    return safe

class TabStateStore:
    def __init__(self,root):
        self.root=Path(root);self.original={};self.documents={};self.locations={}

    def load(self):
        inputs={};models={}
        for path in sorted(self.root.rglob('*.json')):
            raw=path.read_bytes();doc=json.loads(raw.decode('utf-8-sig'))
            if doc.get('schema_version')!=1:raise ValueError(f'Invalid tab state schema: {path}')
            for section,target in (('inputs',inputs),('models',models)):
                values=doc.get(section,{})
                if not isinstance(values,dict):raise ValueError(f'Invalid {section}: {path}')
                for key,value in values.items():
                    if key in target:raise ValueError(f'Duplicate tab state key: {key}')
                    target[key]=value;self.locations[(section,key)]=path
            self.original[path]=raw;self.documents[path]=doc
        return inputs,models

    def destination(self,key,roots):
        scope=next((r for r in sorted(roots,key=len,reverse=True) if key==r or key.startswith(r+'/')),'legacy')
        if scope.startswith('device/'):
            parts=scope.split('/')[1:3]
        elif scope.startswith('experiment/'):
            parts=['experiments']+[p for p in scope.split('/')[1:] if p]
        else:parts=['common',scope]
        return Path(str(self.root.joinpath(*(component(p) for p in parts)))+'.json')

    def save(self,inputs,models,roots):
        docs={p:dict(d,inputs=dict(d.get('inputs',{})),models=dict(d.get('models',{}))) for p,d in self.documents.items()}
        locations=dict(self.locations)
        for section,values in (('inputs',inputs),('models',models)):
            for key,value in values.items():
                path=locations.get((section,key)) or self.destination(key,roots)
                doc=docs.setdefault(path,dict(schema_version=1,inputs={},models={}))
                doc[section][key]=value;locations[(section,key)]=path
        # Detect any external writer before changing any file.
        for path in docs:
            if (path.read_bytes() if path.exists() else None)!=self.original.get(path):
                raise ValueError(f'Tab settings changed outside this window; original retained: {path}')
        for path,doc in docs.items():
            raw=(json.dumps(doc,ensure_ascii=False,indent=2,allow_nan=False)+'\n').encode('utf8')
            if raw!=self.original.get(path):
                path.parent.mkdir(parents=True,exist_ok=True)
                temporary=path.with_name(path.name+'.tmp');temporary.write_bytes(raw);os.replace(temporary,path)
            self.original[path]=raw
        self.documents=docs;self.locations=locations
