"""Used sequencer signals shared by experiment forms, Queue and validation.

Paths describe the existing sequence parameter interface, not physical wiring.
On disk these paths are consolidated into one fpga_mapping block.
"""
from dataclasses import dataclass
from copy import deepcopy
from .mapping import CURRENT, Profile, capability, ROLE_KINDS

PULSE = ('PMT','AOM','MW','EOM_7G_1','EOM_7G_2','EOM_2G')
ION_FIXED = ('EOM_7GA1','EOM_7GA2','EOM_7GC1','EOM_7GC2','EOM_2GA','EOM_2GC','MW_A','MW_C')
ENT = ('PMTA','PMTC','SYNC','PMTFA','PMTFC','AOMA','AOMC','AOMB','AOMM',
       *ION_FIXED,'CCD_EA','CCD_EC','TRIG')
@dataclass(frozen=True)
class Route:
    path: tuple
    role: str
    feature: str
    use: str = '측정'
    optional: bool = False

def get(c,path,default=None):
    try:
        for key in path:c=c[key]
        return c
    except (KeyError,IndexError,TypeError):return default

def put(c,path,value):
    node=c
    for key in path[:-1]:
        if isinstance(node,dict):node=node.setdefault(key,[] if isinstance(path[-1],int) else {})
        else:node=node[key]
    if isinstance(node,list):
        while len(node)<=path[-1]:node.append(None)
    node[path[-1]]=value

def routes(experiment,c,mode=None,*,all_fields=False):
    out=[]
    def add(path,role,feature,use='측정',optional=False):out.append(Route(tuple(path),role,feature,use,optional))
    if experiment in ('rabi','ramsey','spin_echo','spam','initialization','fluorescence'):
        selected=list(PULSE) if experiment!='fluorescence' else ['PMT']
        if experiment in ('rabi','spam') and (all_fields or c.get('detector_count',1)==2):selected.insert(1,'PMT2')
        for role in selected:
            counter=role in ('PMT','PMT2')
            add(('roles',role),role,'counter' if counter else 'slow output' if role=='MW' else 'fast output',
                '시작·종료 OFF' if experiment=='initialization' and role=='MW' else '측정' if counter else '측정·종료 복구')
        if all_fields and experiment=='fluorescence':add(('roles','AOM'),'AOM','output','미사용')
    elif experiment=='decay':
        selected=['PMT1','SYNC','AOM','TRIG']
        if all_fields or c.get('mode','').endswith('dual'):selected.insert(1,'PMT2')
        if all_fields or c.get('mode','').startswith('171'):selected+=['EOM_7G1','EOM_7G2','EOM_2G']
        for role in selected:
            add(('roles',role),role,'stopwatch' if role in ('PMT1','PMT2','SYNC') else 'fast output','측정' if role in ('PMT1','PMT2','SYNC') else '측정·종료 복구')
        for role in ('AUX1','AUX2'):
            if all_fields or get(c,('roles',role)):add(('roles',role),role,'slow output','시작·종료 출력',True)
    elif experiment=='hom':
        for role in ('PMTA','PMTC','SYNC'):add(('inputs',role),role,'stopwatch')
        for role in ('AOMA','AOMC','TRIG'):add(('outputs',role),role,'fast output','측정·종료 복구')
        if all_fields or c.get('aomb_enabled'):add(('outputs','AOMB'),'AOMB','output','시작·종료 출력')
    elif experiment in ('entanglement','entanglement_no_mirror'):
        for role in ENT:
            if experiment=='entanglement_no_mirror' and role.startswith('CCD_'):continue
            feature=('stopwatch' if role in ('PMTA','PMTC','SYNC') else 'counter') if ROLE_KINDS[role]=='input' else ROLE_KINDS[role]
            use='시작·종료 OFF' if role.startswith('MW_') and c.get('basis')=='zz' else '측정·종료 복구' if 'output' in feature else '측정'
            add(('fpga_mapping',role),role,feature,use)
    elif experiment=='ion_check':
        for key,role in [('pmt_1','PMT1'),('pmt_2','PMT2'),('laser_a','Laser A'),('laser_b','Laser B'),('laser_c','Laser C')]:
            if key=='pmt_2' and not all_fields and not get(c,('mapping',key)):continue
            add(('mapping',key),role,'counter' if key.startswith('pmt') else 'output','측정',key=='pmt_2')
        for role in ION_FIXED:add(('fpga_mapping',role),role,ROLE_KINDS[role],'시작·종료 OFF' if role.startswith('MW_') else '측정·종료 복구')
    elif experiment in ('micromotion','secular'):
        for key,role,feature in [('trg_pin','SYNC','stopwatch'),('pmt_pin','PMT','counter / stopwatch' if experiment=='secular' else 'stopwatch'),('counter_pin','COUNTER','counter')]:
            if experiment=='secular' and key=='counter_pin':continue
            if all_fields or experiment=='secular' or (key=='counter_pin')==(mode=='input'):add((key,),role,feature)
    elif experiment=='scan':add(('pmt',),'PMT','counter')
    elif experiment=='phase_shifter':
        for i in range(12):add(('phase_outputs',i),'D'+str(i),'slow output','위상 출력')
        if 'outputs' in c:
            for role in ('aom','eom_7g_1','eom_7g_2','eom_2g','microwave'):
                add(('outputs',role),role,'slow output' if role=='microwave' else 'output','측정·종료 복구')
            add(('detector_nickname',),'PMT','counter')
    return out

def accepts(feature,pin):
    if not pin:return False
    actual=capability(pin)
    return all(part.strip() in actual for part in feature.split('/'))

def direct(token,experiment,profile=None):
    profile=profile or (CURRENT.get()[0] if CURRENT.get() else None)
    if not token:return token
    if profile is None:return token
    exp=None if experiment in ('phase_shifter','scan','micromotion','secular') else experiment
    pin=profile.resolve(token,exp)
    if pin is None:return None
    name=profile.document()['pins'][pin]
    return name if experiment in ('phase_shifter','scan') else 'signal:'+name

def normalize(c,experiment,mode=None,profile=None):
    c=deepcopy(c)
    profile=profile or (CURRENT.get()[0] if CURRENT.get() else None)
    for r in routes(experiment,c,mode,all_fields=True):
        token=get(c,r.path)
        if r.path[0]=='fpga_mapping' and r.role not in c.get('fpga_mapping',{}):
            token=r.role
        try:token=direct(token,experiment,profile)
        except ValueError:
            # Retain unresolved text for explicit correction; never choose a pin.
            pass
        put(c,r.path,token)
    return c

def validate(c,experiment,mode=None):
    state=CURRENT.get()
    if state is None:raise ValueError('Select an FPGA before validating its mapping')
    profile=state[0]
    for r in routes(experiment,c,mode):
        token=get(c,r.path)
        if r.optional and not token:continue
        exp=None if experiment in ('phase_shifter','scan','micromotion','secular') else experiment
        pin=profile.resolve(token,exp)
        if not accepts(r.feature,pin):raise ValueError(r.role+': select a '+r.feature+' nickname')

def settings_profile(profile,experiment,c):
    """Old fixed-role sequencers execute the settings snapshot, not live bindings."""
    if experiment not in ('entanglement','entanglement_no_mirror','ion_check') or not isinstance(c,dict):return profile
    values=c.get('fpga_mapping')
    if not isinstance(values,dict):return profile # old saved workflows
    doc=profile.document()
    target=doc['role_bindings'][experiment]
    for role in (ENT if experiment in ('entanglement','entanglement_no_mirror') else ION_FIXED):
        if experiment=='entanglement_no_mirror' and role.startswith('CCD_'):continue
        token=values.get(role)
        pin=profile.resolve(token,None)
        target[role]=doc['pins'][pin] if pin else None
    return Profile(doc)

def scoped(experiment):
    from functools import wraps
    from .mapping import scope
    def decorate(fn):
        @wraps(fn)
        def call(c,*args,**kwargs):
            state=CURRENT.get()
            if state is None:return fn(c,*args,**kwargs)
            with scope(settings_profile(state[0],experiment,c),experiment):
                return fn(c,*args,**kwargs)
        return call
    return decorate
