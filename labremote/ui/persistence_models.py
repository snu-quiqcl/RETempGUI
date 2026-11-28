"""Explicit local UI models. Restoration must never call instrument APIs."""
from copy import deepcopy
import math
import hashlib
from pathlib import Path
from labremote.data_paths import DATA_ROOT
from PyQt5 import QtCore, QtWidgets as W


def supported(widget):
    return type(widget).__name__ in ('ExperimentWorkspace','CalibrationSelector','QueueTab','CCDTab') or hasattr(widget,'halfpi_source')

def archive(snapshot,field):
    if snapshot is None:return None
    raw=snapshot[field]
    digest=hashlib.sha256(raw.encode('utf8')).hexdigest()
    if snapshot['sha256']!=digest:raise ValueError('Calibration snapshot hash mismatch')
    relative=Path('calibration/ui_snapshots')/(digest+('.json' if field=='json' or snapshot.get('kind')=='ramsey_data_interpolation' else '.csv'))
    path=DATA_ROOT/relative
    if path.exists():
        if path.read_text(encoding='utf8')!=raw:raise ValueError('Calibration archive mismatch')
    else:
        path.parent.mkdir(parents=True,exist_ok=True);path.write_text(raw,encoding='utf8',newline='')
    return {**{k:v for k,v in snapshot.items() if k!=field},'archive':relative.as_posix()}

def unarchive(reference,field):
    if reference is None:return None
    snapshot=deepcopy(reference)
    if field not in snapshot:
        path=(DATA_ROOT/snapshot.pop('archive')).resolve()
        if not path.is_relative_to(DATA_ROOT.resolve()):raise ValueError('Calibration archive is outside data')
        snapshot[field]=path.read_text(encoding='utf8')
    return snapshot


def capture(widget):
    name=type(widget).__name__
    if name=='ExperimentWorkspace':
        return {'type':name,'selected':{slot.settings_id:slot.selected for slot in widget.slots}}
    if name=='CalibrationSelector':
        return {'type':name,'snapshot':archive(widget.snapshot,'csv'),'enabled':bool(widget.mode.currentIndex())}
    if name=='QueueTab':
        # An empty queue is a valid saved draft, but not a runnable plan.
        plan=widget.plan() if widget.jobs else dict(schema_version=1,repeat=widget.repeat.value(),jobs=[])
        return {'type':name,'plan':deepcopy(plan),'directory':widget.directory.text()}
    if hasattr(widget,'halfpi_source'):
        return {'type':'halfpi','source':archive(widget.halfpi_source,'json')}
    if name=='CCDTab':
        return {'type':'ccd_view','range':widget.canvas.getViewBox().viewRange()}
    return None


def restore(widget,value):
    kind=value.get('type')
    if kind=='ExperimentWorkspace':
        selected=value['selected']
        if not isinstance(selected,dict) or any(v is not None and not isinstance(v,str) for v in selected.values()):raise ValueError('Invalid FPGA selections')
        for slot in widget.slots:
            if slot.settings_id in selected:
                slot.selected=selected[slot.settings_id]
                with QtCore.QSignalBlocker(slot.choice):
                    index=slot.choice.findData(slot.selected)
                    if index<0 and slot.selected is not None:
                        slot.choice.addItem(slot.selected+' · 연결 끊김',slot.selected);index=slot.choice.count()-1
                    slot.choice.setCurrentIndex(max(0,index))
    elif kind=='CalibrationSelector':
        from labremote.experiments.phase_shifter.calibration import rows
        snapshot=unarchive(value['snapshot'],'csv')
        if snapshot is not None:rows(snapshot)
        with QtCore.QSignalBlocker(widget),QtCore.QSignalBlocker(widget.mode):
            widget.set_table(snapshot)
            widget.mode.setCurrentIndex(int(value['enabled']))
    elif kind=='QueueTab':
        from labremote.runtime.workflow_queue import validate_plan
        plan=deepcopy(value['plan'])
        if isinstance(plan,dict) and plan.get('jobs')==[]:
            if plan.get('schema_version') not in (1,2) or type(plan.get('repeat')) is not int or not 1<=plan['repeat']<=10000:
                raise ValueError('Invalid empty queue draft')
        else:plan=validate_plan(plan)
        with QtCore.QSignalBlocker(widget),QtCore.QSignalBlocker(widget.repeat):
            widget.jobs=plan['jobs'];widget.repeat.setValue(plan['repeat'])
            widget.directory.setText(value['directory']);widget.refresh();widget.dirty=False
    elif kind=='halfpi':
        snapshot=unarchive(value['source'],'json')
        if snapshot is None:widget.halfpi_source=None
        else:
            from labremote.experiments.phase_shifter.halfpi import knots
            knots(snapshot)
            with QtCore.QSignalBlocker(widget):widget.set_source(snapshot)
    elif kind=='ccd_view':
        ranges=value['range']
        if len(ranges)!=2 or any(len(r)!=2 or any(type(v) not in (float,int) or not math.isfinite(v) for v in r) or r[0]>=r[1] for r in ranges):raise ValueError('Invalid CCD view range')
        with QtCore.QSignalBlocker(widget.canvas.getViewBox()):
            widget.canvas.getViewBox().setRange(xRange=ranges[0],yRange=ranges[1],padding=0)


def table_value(widget):
    # Only explicitly editable data tables; queue/result tables are not drafts.
    if widget.editTriggers()==W.QAbstractItemView.NoEditTriggers:return None
    if any(widget.cellWidget(r,c) is not None for r in range(widget.rowCount()) for c in range(widget.columnCount())):
        return None  # Structured dialog editors retain their Save/Cancel transaction.
    headers=[widget.horizontalHeaderItem(c).text() if widget.horizontalHeaderItem(c) else str(c) for c in range(widget.columnCount())]
    values=[[widget.item(r,c).text() if widget.item(r,c) else None for c in range(widget.columnCount())] for r in range(widget.rowCount())]
    return {'kind':'table','value':values,'headers':headers}


def restore_table(widget,saved):
    current=table_value(widget)
    if current is None or current['headers']!=saved.get('headers'):raise ValueError('Table columns changed; saved draft retained')
    values=saved['value']
    if not isinstance(values,list) or len(values)>10000 or any(not isinstance(r,list) or len(r)!=widget.columnCount() for r in values):raise ValueError('Invalid table draft')
    widget.clearContents();widget.setRowCount(len(values))
    for r,row in enumerate(values):
        for c,value in enumerate(row):
            if value is not None:widget.setItem(r,c,W.QTableWidgetItem(str(value)))
