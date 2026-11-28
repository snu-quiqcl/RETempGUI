"""Read a workflow's literal editor declaration without executing its source."""
import ast


def editor_kind(source):
    for node in ast.parse(source).body:
        if isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='WORKFLOW_UI' for t in node.targets):
            value=ast.literal_eval(node.value)
            if not isinstance(value,dict) or set(value)!={'editor'} or value['editor'] not in ('setup','entanglement','entanglement_no_mirror','ion','spam','phase_hold'):raise ValueError('Invalid WORKFLOW_UI declaration')
            return value['editor']
    return None


def spam_uses_chamber_settings(source):
    """Old built-in SPAM calls pass an EA/EC selector to run_spam."""
    for node in ast.walk(ast.parse(source)):
        if not (isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute)
                and node.func.attr=='run_spam'):
            continue
        chamber=node.args[0] if node.args else next((kw.value for kw in node.keywords if kw.arg=='chamber'),None)
        if chamber is not None and not (isinstance(chamber,ast.Constant) and chamber.value is None):
            return True
    return False
