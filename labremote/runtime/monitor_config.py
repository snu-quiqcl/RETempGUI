"""Monitor identity follows the experiment, independent of acquisition settings."""
import ast

RE_KINDS = ('ent_with_mirror', 'ent_without_mirror')
LABELS = {'none':'없음','ion':'Ion Check','spam':'SPAM',
          'ent_with_mirror':'RE with flip mirror','ent_without_mirror':'RE without flip mirror',
          'ent':'RE (기존 자동 구분)'}
KINDS = tuple(LABELS)

def is_ent(kind):
    return kind in (*RE_KINDS,'ent')

def result_kind(experiment):
    return {'entanglement':'ent_with_mirror','entanglement_no_mirror':'ent_without_mirror'}[experiment]

def matches(monitor, result):
    return monitor==result or monitor=='ent' and is_ent(result)

def detected(job):
    found=set()
    try:
        for node in ast.walk(ast.parse(job.get('source',''))):
            if isinstance(node,ast.Call):
                name=getattr(node.func,'attr',getattr(node.func,'id',''))
                kind={'run_ion_check':'ion','run_spam':'spam','run_entanglement':'ent_with_mirror',
                      'run_entanglement_no_mirror':'ent_without_mirror'}.get(name)
                if kind:found.add(kind)
        from .re_workflows import experiment
        exp=experiment(job)
        if exp:found.add(result_kind(exp))
    except (ValueError,SyntaxError):pass
    if job.get('parameters',{}).get('kind')=='IonCheckTab':found.add('ion')
    if job.get('filename','').replace('\\','/').endswith('/ion_check_workflow.py'):found.add('ion')
    return found

def suggested(job):
    found=detected(job)
    kind=next(iter(found)) if len(found)==1 else 'ent' if found and found<=set(RE_KINDS) else 'none'
    return dict(kind=kind,title='',view='cumulative')

def validate(value):
    if not isinstance(value,dict) or set(value)-{'charts'}!={'kind','title','view'}:
        raise ValueError('Invalid Monitor settings')
    if value['kind'] not in KINDS or value['view'] not in ('cumulative','latest'):
        raise ValueError('Invalid Monitor kind/view')
    if not isinstance(value['title'],str):raise ValueError('Monitor title must be text')
    return {key:value[key] for key in ('kind','title','view')}

def settings(job):
    value=validate(job['monitor']) if 'monitor' in job else suggested(job)
    # Old plans keep their source, acquisition settings, title and view.
    # Only their generic RE monitor is resolved to a known experiment.
    if value['kind']=='ent':
        inferred=suggested(job)['kind']
        if inferred in RE_KINDS:value=dict(value,kind=inferred)
    return value
