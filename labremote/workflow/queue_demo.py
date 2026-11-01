"""No hardware I/O. Use Queue parameters {"value": 1, "fail": false}."""
def main(devices):
    from pathlib import Path
    from labremote.runtime.workflow_queue import save
    p=devices.parameters
    paths=[]
    if devices.run_directory:
        path=Path(devices.run_directory)/'demo.json'
        save(path,p);paths.append(str(path))
    return {'status':'failed' if p.get('fail',False) else 'completed',
            'reason':'Demo requested failure' if p.get('fail',False) else '',
            'result_paths':paths,'metrics':{'value':p.get('value',1)},
            'cleanup_status':'not_required'}
