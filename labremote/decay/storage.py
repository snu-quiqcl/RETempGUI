"""Self-contained Decay archives and legacy readers."""
import json
from pathlib import Path
from . import config
from .plotting import Accumulator

def measurement(histograms,programmed_trials,c):
    channels=[c['roles']['PMT'+str(i+1)] for i in range(len(histograms))]
    total=[sum(v) for v in zip(*histograms)]
    decay=[sum(h[c['DECAY_THRESHOLD']:]) for h in histograms]
    prompt=[sum(h[c['SIGNAL_THRESHOLD']:c['DECAY_THRESHOLD']]) for h in histograms]
    divide=lambda v:v/programmed_trials if programmed_trials else None
    return dict(histogram=dict(channel_names=channels,counts=histograms,total=total),
        counts=dict(decay_channels=decay,decay_total=sum(decay),prompt_channels=prompt,prompt_total=sum(prompt)),
        trials=dict(programmed_trials=programmed_trials,valid_sync_trials=None,missing_sync_trials=None,
            normalization_trials=programmed_trials,normalization_basis='programmed_trials'),
        probabilities=dict(decay_channels=[divide(v) for v in decay],decay_total=divide(sum(decay)),
            prompt_channels=[divide(v) for v in prompt],prompt_total=divide(sum(prompt))))


def load_result(path):
    path=Path(path);document=config.read(path)
    if document.get('experiment')!='decay':raise ValueError('Not a decay result')
    if 'schema_version' not in document:
        settings=config.read(path.parent/'configuration.json')['settings']
        return document,settings,config.read(path.parent/'histogram.json')
    if document['schema_version']==3:
        settings=document['configuration']['settings'];acc=Accumulator(settings);seen=set()
        for batch in document['batches']:
            if batch.get('run_id')!=document['run_id']:raise ValueError('Batch run ID differs from result')
            if batch['status']!='completed':continue
            if batch['batch'] in seen:raise ValueError('Duplicate completed batch')
            seen.add(batch['batch'])
            acc.add(dict(batch=batch['batch'],histograms=batch['histogram']['counts'],trials=batch['trials']['normalization_trials'],batch_complete=True,elapsed_s=batch['elapsed_s']))
        report={k:v for k,v in document.items() if k not in ('configuration','axes','batches','final')}
        if report['status']=='running':report['status']='interrupted'
        return report,settings,acc.data()
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
