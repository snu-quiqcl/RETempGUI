"""Read a workflow's literal editor declaration without executing its source."""
import ast


def editor_kind(source):
    for node in ast.parse(source).body:
        if isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='WORKFLOW_UI' for t in node.targets):
            value=ast.literal_eval(node.value)
            if not isinstance(value,dict) or set(value)!={'editor'} or value['editor'] not in ('setup','entanglement','ion','spam','phase_hold'):raise ValueError('Invalid WORKFLOW_UI declaration')
            return value['editor']
    return None
