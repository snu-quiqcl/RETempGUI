"""One self-contained results.json plus raw FIFO and a final plot."""
from labremote.experiments.entanglement import config
from labremote.experiments.entanglement.plotting import Accumulator, decay_fits, decay_counts, decay_reference

def measurement(data, c):
    counts=decay_counts(data,c); n=data['attempts']
    return dict(**({key:data[key] for key in ('state_readout_histograms_by_pmt',) if key in data}),state_readout_histograms=data['state_readout_histograms'],actual_trials=n,decay_counts_per_actual_trial={k:v/n if n else None for k,v in counts.items()},
        decay_reference=decay_reference(data,c),histogram=dict(a=data['a'],c=data['c'],total=[a+b for a,b in zip(data['a'],data['c'])],coincidence=data['coincidence']),
        decay_counts=decay_counts(data,c),attempts=data['attempts'],heralds=data['heralds'],state_counts=data['states'],metrics=data['metrics'],decay_fit=decay_fits(data,c))

def load_result(path):
    document=config.read(path)
    if document.get('experiment') not in ('entanglement','entanglement_no_mirror') or document.get('schema_version') not in (1,2):
        raise ValueError('Not a supported entanglement result')
    selected=config
    if document['experiment']=='entanglement_no_mirror':
        from labremote.experiments.entanglement_no_mirror import config as selected
    from labremote.devices.fpga.mapping import editing_settings
    with editing_settings():c=selected.validate(document['configuration']['settings'])
    acc=Accumulator(c)
    for b in document['batches']:
        if b['status']=='completed':acc.add(b['measurement'])
    return document,c,acc.data()
