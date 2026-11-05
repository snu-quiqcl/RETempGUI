"""Unified HOM archive reader, with support for the original split files."""
from pathlib import Path
from . import config


def measurement(data,programmed_trials):
    a=data['a'];c=data['c'];h=data['hom'];n=data['trials'];metrics=data['metrics']
    return dict(histogram=dict(a=a,c=c,total=[x+y for x,y in zip(a,c)],hom=h,reference_probability=data['reference_probability']),
        counts=dict(pmta=sum(a),pmtc=sum(c),decay_total=sum(a)+sum(c),coincidences=sum(h)),
        trials=dict(programmed_trials=programmed_trials,valid_sync_trials=n,missing_sync_trials=data['missing_sync'],
            normalization_trials=n,normalization_basis='valid_sync_trials'),probabilities=metrics)


def load_result(path):
    path=Path(path); document=config.read(path)
    if document.get('experiment')!='hom':raise ValueError('This is not a HOM result')
    if 'schema_version' not in document:
        settings=config.validate(config.read(path.parent/'configuration.json')['settings'])
        return document,settings,config.read(path.parent/'histogram.json')
    if document['schema_version']==2:
        from .plotting import Accumulator
        settings=config.validate(document['configuration']['settings']);acc=Accumulator(settings);seen=set()
        for batch in document['batches']:
            if batch.get('run_id')!=document['run_id']:raise ValueError('Batch run ID differs from result')
            if batch['status']!='completed':continue
            if batch['batch'] in seen:raise ValueError('Duplicate completed batch')
            seen.add(batch['batch']);h=batch['histogram'];t=batch['trials']
            acc.add(dict(a=h['a'],c=h['c'],hom=h['hom'],trials=t['valid_sync_trials'],missing_sync=t['missing_sync_trials'],batch=batch['batch'],elapsed_s=batch['elapsed_s']))
        report={k:v for k,v in document.items() if k not in ('configuration','axes','batches','final')}
        if report['status']=='running':report['status']='interrupted'
        return report,settings,acc.data()
    if document['schema_version']!=1:raise ValueError('Unsupported HOM archive version')
    settings=config.validate(document['configuration']['settings'])
    report={key:value for key,value in document.items() if key not in ('configuration','histogram','axes','batches','decay_fit')}
    if report['status']=='running':report['status']='interrupted'
    return report,settings,document['histogram']
