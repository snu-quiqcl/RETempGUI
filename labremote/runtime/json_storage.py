"""Atomic JSON snapshots, coordinated with this process's readers on Windows."""
import json
import os
from pathlib import Path
import tempfile
import threading
import time

_locks=tuple(threading.RLock() for _ in range(64))

def path_lock(path):
    return _locks[hash(os.path.normcase(os.path.abspath(path))) % len(_locks)]

def read_json(path):
    with path_lock(path):
        text=Path(path).read_text(encoding='utf-8-sig')
    return json.loads(text)

def save_json(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    text=json.dumps(value,indent=2,ensure_ascii=False,allow_nan=False)+'\n'
    with path_lock(path):
        fd,name=tempfile.mkstemp(prefix=path.name+'.',suffix='.tmp',dir=path.parent)
        temp=Path(name)
        try:
            with os.fdopen(fd,'w',encoding='utf-8') as stream:stream.write(text)
            # External readers/AV may briefly deny replacement. Never erase the
            # last good snapshot, and never hide a persistent storage failure.
            for attempt in range(8):
                try:temp.replace(path);break
                except PermissionError:
                    if attempt==7:raise
                    time.sleep(min(.01*2**attempt,.2))
        except BaseException:
            # Retain the completed temporary snapshot for recovery/diagnosis.
            raise
