"""Shared mapping table for the pulse sequence family."""
from labremote.ui.experiment_mapping import MappingEditor
def pin_controls(worker,kind,parent):
    group=MappingEditor(worker,kind,dict(roles={}),parent=parent)
    return group,{path[-1]:box for path,box in group.choices.items()}
