"""One self-contained results.json plus raw FIFO and a final plot."""
from . import config
from .plotting import Accumulator, decay_fits, decay_counts, decay_reference

def measurement(data, c):
    counts=decay_counts(data,c); n=data['attempts']
    return dict(state_readout_histograms=data['state_readout_histograms'],actual_trials=n,decay_counts_per_actual_trial={k:v/n if n else None for k,v in counts.items()},
        decay_reference=decay_reference(data,c),histogram=dict(a=data['a'],c=data['c'],total=[a+b for a,b in zip(data['a'],data['c'])],coincidence=data['coincidence']),
        decay_counts=decay_counts(data,c),attempts=data['attempts'],heralds=data['heralds'],state_counts=data['states'],metrics=data['metrics'],decay_fit=decay_fits(data,c))

def load_result(path):
    document=config.read(path)
    if document.get('experiment')!='entanglement' or document.get('schema_version') not in (1,2):
        raise ValueError('Not a supported entanglement result')
    c=config.validate(document['configuration']['settings']); acc=Accumulator(c)
    for b in document['batches']:
        if b['status']=='completed':acc.add(b['measurement'])
    return document,c,acc.data()
