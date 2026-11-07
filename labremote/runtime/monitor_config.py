"""Explicit presentation settings stored on Queue jobs, separate from parameters."""
import ast

KINDS = ('none', 'ion', 'spam', 'ent')

def suggested(job):
    found = set()
    try:
        for node in ast.walk(ast.parse(job.get('source', ''))):
            if isinstance(node, ast.Call):
                name = getattr(node.func, 'attr', getattr(node.func, 'id', ''))
                kind = {'run_ion_check':'ion', 'run_spam':'spam', 'run_entanglement':'ent'}.get(name)
                if kind: found.add(kind)
    except (ValueError, SyntaxError): pass
    if job.get('filename', '').replace('\\', '/').endswith('/ion_check_workflow.py'): found.add('ion')
    return dict(kind=next(iter(found)) if len(found)==1 else 'none', title='', view='cumulative')

def validate(value):
    if not isinstance(value, dict) or set(value)-{'charts'} != {'kind','title','view'}:
        raise ValueError('Invalid Monitor settings')
    if value['kind'] not in KINDS or value['view'] not in ('cumulative','latest'):
        raise ValueError('Invalid Monitor kind/view')
    if not isinstance(value['title'], str): raise ValueError('Monitor title must be text')
    # Legacy Queue files may contain a chart subset. Always show the complete
    # RE plot and omit the retired option when normalizing/saving the Queue.
    return {key:value[key] for key in ('kind','title','view')}

def settings(job):
    return validate(job['monitor']) if 'monitor' in job else suggested(job)
