"""Group exports for other built-in FPGA measurements, pooled only at equal settings."""
from collections import defaultdict
from copy import deepcopy
from pathlib import Path
import numpy as np
from .json_storage import read_json
from .queue_monitor_data import settings_key
from .queue_archive import save_figure

def hom_fits(data,c):
    from labremote.decay.plotting import fit_decay
    output={};m=c['MAX_TIME_DIFFERENCE']
    for key,src in [('accumulated',data),('latest_batch',data.get('latest') or dict(a=[0]*m,c=[0]*m))]:
        a=np.asarray(src['a']);b=np.asarray(src['c']);fits={};t=np.arange(m)*1.25
        for values,label,lower in ((a,'PMTA',c['THRESHOLD_A']),(b,'PMTC',c['THRESHOLD_C']),(a+b,'Total',max(c['THRESHOLD_A'],c['THRESHOLD_C']))):
            start=lower+int(np.argmax(values[lower:]));fits[label]=dict(fit_decay(t[start:],values[start:]),start_bin=start)
        output[key]=fits
    return output

def merge_points(rows):
    merged={}
    for row in rows:
        key=row['index']
        if key not in merged:merged[key]=deepcopy(row);continue
        dst=merged[key];dst['counts'].extend(row['counts'])
        for name in ('attempts','successes','received_rows'):
            if name in row:dst[name]+=row[name]
        if 'complete' in row:dst['complete']=dst['complete'] and row['complete']
    return [merged[k] for k in sorted(merged)]

def export(root,steps,partial):
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    buckets=defaultdict(list);destinations={};seen=set()
    for step in steps:
        if 'directory' not in step:continue
        folder=root/step['directory']
        dest=folder.parent.parent if folder.name.startswith('run_') else folder.parent
        for path in sorted([*folder.rglob('result.json'),*folder.rglob('results.json')]):
            if path in seen:continue
            seen.add(path);doc=read_json(path);kind=doc.get('experiment');base=path.parent
            if kind in ('entanglement','spam') or 'dac' in doc:continue
            cfg=doc.get('configuration',{})
            if (base/'configuration.json').exists():cfg=read_json(base/'configuration.json')
            c=doc.get('settings',cfg.get('settings',cfg))
            if not kind:
                kind='scan' if (base/'heatmap.npz').exists() else 'fluorescence' if (base/'analysis.npz').exists() else 'rabi' if (base/'points.json').exists() else None
            if kind not in ('hom','decay','ramsey','spin_echo','initialization','rabi','fluorescence','scan','micromotion','spam_2d'):continue
            # Frequency and route are part of scientific identity, not run IDs.
            identity=dict(settings=c,frequency_hz=cfg.get('frequency_hz'),mapping=cfg.get('mapping'),mode=doc.get('mode'))
            key=(step['job_id'],kind,settings_key(identity))
            buckets[key].append((path,doc,c,cfg));destinations[key]=dest
    paths=[]
    for key,rows in buckets.items():
        job,kind,profile=key;c=rows[0][2];fig=Figure(figsize=(12,12));FigureCanvasAgg(fig)
        if kind=='hom':
            from labremote.hom.plotting import Accumulator,HOMPlot
            acc=Accumulator(c)
            for path,d,_,cfg in rows:
                for b in d['batches']:
                    if b['status']=='completed':
                        h=b['histogram'];t=b['trials']
                        acc.add(dict(a=h['a'],c=h['c'],hom=h['hom'],trials=t['valid_sync_trials'],missing_sync=t['missing_sync_trials'],batch=len(acc.batches),elapsed_s=b['elapsed_s']))
            if not acc.batches:continue
            HOMPlot(fig,c).update(acc.data())
        elif kind=='decay':
            from labremote.decay.storage import load_result
            from labremote.decay.plotting import Accumulator,DecayPlot
            acc=Accumulator(c)
            for path,d,_,cfg in rows:
                _,_,data=load_result(path)
                for b in data['batches']:
                    if b['complete']:acc.add(dict(batch=len(acc.batches),histograms=b['histograms'],trials=b['trials'],batch_complete=True,elapsed_s=b['elapsed_s']))
            if not acc.batches:continue
            DecayPlot(fig,c).update(acc.data())
        elif kind in ('ramsey','spin_echo','initialization','rabi'):
            points=merge_points([p for path,d,_,cfg in rows if d['status']=='completed' for p in read_json(path.parent/'points.json')])
            if not points:continue
            if kind=='rabi':
                from labremote.characterization.rabi import analyze,draw
                draw(fig,analyze(points,c,rows[0][3].get('frequency_hz')))
            else:
                from labremote.characterization.pulse_experiment import analyze,draw
                draw(fig,analyze(kind,points,c))
        elif kind=='fluorescence':
            from labremote.characterization.fluorescence import analyze,draw
            counts=[]
            for path,d,_,cfg in rows:
                with np.load(path.parent/'analysis.npz') as data:counts.extend(data['counts'].tolist())
            if not counts:continue
            draw(fig,analyze(counts,c['exposure_ms']))
        elif kind=='scan':
            arrays=[];xs=ys=None
            for path,d,_,cfg in rows:
                with np.load(path.parent/'heatmap.npz') as data:
                    x,y=data['x_um'],data['y_um']
                    if xs is not None and (not np.array_equal(xs,x) or not np.array_equal(ys,y)):raise ValueError('Scan axes differ within pooled settings')
                    xs,ys=x,y;arrays.append(data['counts'])
            total=np.nansum(arrays,axis=0);valid=np.isfinite(arrays).sum(axis=0);total=np.where(valid,total,np.nan)
            planes=total[None,...] if total.ndim==2 else total
            axes=fig.subplots(len(planes),1,squeeze=False).ravel()
            for index,(ax,plane) in enumerate(zip(axes,planes)):
                mesh=ax.pcolormesh(xs,ys,plane,shading='auto');fig.colorbar(mesh,ax=ax,label='Sum of per-run mean counts')
                ax.set(xlabel='X (um)',ylabel='Y (um)',title=f'Plane {index}')
        elif kind=='micromotion':
            from labremote.micromotion.analysis import fit_histogram,fit_valley
            from labremote.micromotion.plotting import draw
            doc=deepcopy(rows[0][1]);points={}
            if doc.get('mode')=='input':
                counts=[v for _,d,_,_ in rows for v in (d.get('rf_test') or {}).get('counts',[])]
                if not counts:continue
                doc['rf_test'].update(counts=counts,mean=float(np.mean(counts)),std=float(np.std(counts)))
            else:
                for _,d,_,_ in rows:
                    for p in d.get('points',[]):
                        coordinate=(p.get('left'),p.get('right'))
                        if coordinate not in points:points[coordinate]=deepcopy(p)
                        else:
                            target=points[coordinate];target['histogram']=(np.asarray(target['histogram'])+p['histogram']).tolist()
                            for n in ('attempts','accepted','elapsed_s'):target[n]+=p[n]
                if not points:continue
                for p in points.values():p['fit']=fit_histogram(p['histogram'],c)
                doc['points']=list(points.values());doc['valley']=fit_valley(doc['points']) if doc.get('mode')=='scan' else {'valid':False}
            draw(fig,doc)
        elif kind=='spam_2d':
            from labremote.characterization import spam_scan as model,pulse_experiment
            points={};axes=rows[0][3]['axis_values']
            for path,d,_,cfg in rows:
                if cfg['axis_values']!=axes:raise ValueError('SPAM scan axes differ')
                for point in read_json(path.parent/'points.json'):
                    if point['status']!='completed':continue
                    coordinate=(point['ix'],point['iy'])
                    saved,shots=points.setdefault(coordinate,(deepcopy(point),[]))
                    if (saved['x'],saved['y'])!=(point['x'],point['y']):raise ValueError('SPAM scan readbacks differ')
                    shots.extend(read_json(path.parent/point['folder']/'points.json'))
            merged=[]
            for point,shots in points.values():
                settings=model.settings_at(c,axes['x'][point['ix']],axes['y'][point['iy']])
                point['metrics']=model.metrics(pulse_experiment.analyze('spam',shots,settings));merged.append(point)
            if not merged:continue
            model.draw_map(fig,c,merged,axis_values=axes)
        variants=sum(k[0]==job for k in buckets)>1
        name=('partial' if partial else 'final')+('_'+kind+'_'+profile if variants else '')+'.png'
        destination=destinations[key]/name
        # Other result kinds within the same workflow may already own final.png.
        if destination.exists():destination=destination.with_name(destination.stem+'_'+kind+'_'+profile+'.png')
        save_figure(fig,destination,partial);paths.append(str(destination.relative_to(root)))
    return paths
