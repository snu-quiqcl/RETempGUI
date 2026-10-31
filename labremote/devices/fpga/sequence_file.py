"""Trusted local Python builders. Importing a file is not sandboxed."""
import hashlib
import math
from pathlib import Path
from labremote.devices.fpga.vendor.SequencerProgram_v1_08 import SequencerProgram


def validate_request(path,parameters=None,timeout_s=30.,max_rows=4096):
    path=Path(path).expanduser()
    if not path.is_absolute():raise ValueError('Sequence path must be absolute on the UI PC')
    if path.suffix.lower()!='.py' or not path.is_file():raise ValueError('Sequence must be an existing .py file')
    if isinstance(timeout_s,bool) or not isinstance(timeout_s,(int,float)) or not math.isfinite(timeout_s) or not .1<=timeout_s<=600:
        raise ValueError('timeout_s must be between 0.1 and 600 seconds')
    if type(max_rows) is not int or not 0<=max_rows<=65535:raise ValueError('max_rows must be between 0 and 65535')
    if parameters is None:parameters={}
    if not isinstance(parameters,dict):raise ValueError('parameters must be a dict')
    from copy import deepcopy
    return {'path':str(path.resolve()),'parameters':deepcopy(parameters),'timeout_s':float(timeout_s),'max_rows':max_rows}


def build(request):
    path=Path(request['path'])
    raw=path.read_bytes()
    namespace={'__name__':'labremote_sequence_builder','__file__':str(path)}
    # Deliberately do not expose the connected device or execute __main__ blocks.
    exec(compile(raw,str(path),'exec'),namespace)
    factory=namespace.get('build_program')
    if not callable(factory):raise ValueError('Sequence file must define build_program(parameters)')
    program=factory(request['parameters'])
    if not isinstance(program,SequencerProgram):raise TypeError('build_program must return the bundled SequencerProgram')
    if not program.program_list or program.program_list[-1][1]!='stop':raise ValueError('Program must end with stop()')
    return program,hashlib.sha256(raw).hexdigest()
