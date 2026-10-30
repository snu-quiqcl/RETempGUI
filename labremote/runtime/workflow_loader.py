"""Load the fixed main(devices) entry point from a frozen source snapshot."""
import ast
import inspect
from contextlib import contextmanager
from pathlib import Path
import sys
from types import ModuleType
from uuid import uuid4


def validate_workflow(source, filename='<workflow>'):
    """Check the fixed entry point without executing any file-level code."""
    tree = ast.parse(source, filename=filename)
    entries = [node for node in tree.body
               if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == 'main']
    if len(entries) != 1 or not isinstance(entries[0], ast.FunctionDef):
        raise ValueError('Workflow must define one synchronous main(devices) function')
    args = entries[0].args
    positional = args.posonlyargs + args.args
    if (len(positional) != 1 or positional[0].arg != 'devices'
            or args.vararg or args.kwarg or args.kwonlyargs):
        raise ValueError('Workflow entry point must be main(devices)')


@contextmanager
def load_workflow(source, filename):
    validate_workflow(source, filename)
    path = Path(filename).resolve()
    workflow_root = Path(__file__).resolve().parents[1] / 'workflow'
    package = 'labremote.workflow' if path.parent == workflow_root else ''
    name = (package + '.' if package else '') + '_selected_' + uuid4().hex
    module = ModuleType(name)
    module.__file__, module.__package__ = str(path), package
    sys.modules[name] = module
    try:
        exec(compile(source, str(path), 'exec'), module.__dict__)
        function = getattr(module, 'main')
        if not callable(function): raise ValueError('main must be callable')
        if inspect.isgeneratorfunction(function) or inspect.iscoroutinefunction(function):
            raise ValueError('Workflow must be a synchronous function, not a generator or coroutine')
        inspect.signature(function).bind(object())
        yield function
    finally:
        sys.modules.pop(name, None)
