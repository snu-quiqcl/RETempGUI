"""File-only experiment series archive. Never queries or controls instruments."""
import csv
import hashlib
import json
import shutil
import sys
import uuid
from importlib.metadata import version,PackageNotFoundError
from datetime import datetime,timezone
from pathlib import Path
from .config import save


def utc():return datetime.now(timezone.utc).isoformat()


def fingerprint(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):h.update(block)
    return h.hexdigest()


class ExperimentArchive:
    """One unique series directory, frozen recipe, append-only point directories.

    Recipe and external conditions must be JSON data supplied by the caller.
    This is a record of known conditions, not a claim to read all lab hardware.
    """
    def __init__(self,directory,*,recipe,external_conditions=None,workflow_file=None):
        # Serialize before creating anything; freeze callers' mutable dictionaries.
        frozen=json.loads(json.dumps(dict(recipe=recipe,external_conditions=external_conditions or {}),allow_nan=False))
        self.folder=Path(directory).expanduser().resolve()/(datetime.now().strftime('%Y%m%d_%H%M%S')+'_series_'+uuid.uuid4().hex)
        self.folder.mkdir(parents=True,exist_ok=False)
        self.state=dict(schema_version=1,started_utc=utc(),status='running',python=sys.version,points=[],**frozen)
        self.state['packages']={}
        for name in ('numpy','scipy','matplotlib','PyQt5','qcodes','pyserial'):
            try:self.state['packages'][name]=version(name)
            except PackageNotFoundError:self.state['packages'][name]=None
        save(self.folder/'series.json',self.state)
        # Copy executable source, not credentials, local configs, or hardware addresses.
        root=Path(__file__).resolve().parents[1]
        sources=[p for relative in ('characterization','operation/fpga','devices/fpga/vendor') for p in (root/relative).rglob('*.py')]
        sources += [root/'devices/fpga/controller.py',root/'api/devices.py']
        self.state['sources']={}
        for source in sources:
            relative=Path('source')/source.relative_to(root);dest=self.folder/relative
            dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,dest)
            self.state['sources'][relative.as_posix()]=fingerprint(dest)
        if workflow_file is not None:
            dest=self.folder/'workflow.py';shutil.copyfile(workflow_file,dest);self.state['sources']['workflow.py']=fingerprint(dest)
        save(self.folder/'series.json',self.state)

    def begin_point(self,coordinate):
        coordinate=json.loads(json.dumps(coordinate,allow_nan=False))
        index=len(self.state['points']);relative=f'points/{index:05d}'
        path=self.folder/relative;path.mkdir(parents=True,exist_ok=False)
        self.state['points'].append(dict(index=index,coordinate=coordinate,directory=relative,status='running',started_utc=utc()))
        save(self.folder/'series.json',self.state)
        return path

    def finish_point(self,path,report=None,*,error=None):
        from labremote.runtime.errors import OperationCancelled
        path=Path(path).resolve();relative=path.relative_to(self.folder).as_posix()
        point=next(p for p in self.state['points'] if p['directory']==relative)
        if point['status']!='running':raise ValueError('Point already finalized')
        point.update(status=report['status'] if report else 'cancelled' if isinstance(error,OperationCancelled) else 'failed',finished_utc=utc(),error=str(error) if error else '')
        if report:
            result_folder=Path(report['folder']).resolve()
            point['result']=str((result_folder/'result.json').relative_to(self.folder)).replace('\\','/')
            point['run_id']=report['run_id']
        point['files']={p.relative_to(self.folder).as_posix():dict(bytes=p.stat().st_size,sha256=fingerprint(p)) for p in sorted(path.rglob('*')) if p.is_file()}
        save(self.folder/'series.json',self.state)
        # Convenience index; series.json is authoritative and preserves arbitrary coordinates.
        with (self.folder/'index.csv').open('w',newline='',encoding='utf-8') as stream:
            writer=csv.writer(stream);writer.writerow(['index','coordinate_json','status','result','error'])
            for p in self.state['points']:writer.writerow([p['index'],json.dumps(p['coordinate']),p['status'],p.get('result',''),p.get('error','')])

    def __enter__(self):return self

    def __exit__(self,typ,error,tb):
        from labremote.runtime.errors import OperationCancelled
        for point in self.state['points']:
            if point['status']=='running':self.finish_point(self.folder/point['directory'],error=error or 'Point not finalized')
        self.state.update(finished_utc=utc(),status='cancelled' if isinstance(error,OperationCancelled) else 'failed' if error or any(p['status']!='completed' for p in self.state['points']) else 'completed',error=str(error) if error else '')
        save(self.folder/'series.json',self.state)
        return False
