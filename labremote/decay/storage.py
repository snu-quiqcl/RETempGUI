"""Decay archive v2 and legacy archive reader; no fitted values are persisted."""
import json
from pathlib import Path
from . import config
from .plotting import Accumulator

def load_result(path):
    path=Path(path);document=config.read(path)
    if document.get('experiment')!='decay':raise ValueError('Not a decay result')
    if 'schema_version' not in document:
        settings=config.read(path.parent/'configuration.json')['settings']
        return document,settings,config.read(path.parent/'histogram.json')
    if document['schema_version']!=2:raise ValueError('Unsupported decay result version')
    settings=document['configuration']['settings'];acc=Accumulator(settings)
    lines=(path.parent/'batches.jsonl').read_text(encoding='utf-8').splitlines()
    seen=set()
    for index,line in enumerate(lines):
        if not line.strip():continue
        try:event=json.loads(line)
        except json.JSONDecodeError:
            if index==len(lines)-1:break  # Interrupted final append; earlier records remain usable.
            raise
        if event.get('run_id')!=document['run_id']:raise ValueError('Batch run ID differs from result')
        if event.get('event')!='finished' or event.get('status')!='completed':continue
        batch=event['batch']
        if batch in seen:raise ValueError('Duplicate completed batch')
        seen.add(batch)
        acc.add(dict(batch=batch,histograms=event['histograms'],trials=event['programmed_trials'],
                     batch_complete=True,elapsed_s=event['elapsed_s']))
    # Reconstruct from the append-only journal, including a batch completed just
    # before a crash prevented replacing the results checkpoint.
    report={k:v for k,v in document.items() if k not in ('configuration','histogram')}
    report['completed_batches']=len(seen)
    if report['status']=='running':report['status']='interrupted'
    return report,settings,acc.data()
