import os,sys,tempfile,shutil,json,hashlib,time,socket,warnings
from pathlib import Path
from copy import deepcopy
from unittest.mock import patch
os.environ['QT_QPA_PLATFORM']='offscreen'
warnings.filterwarnings('ignore',message='Glyph .* missing from font')
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
# Use the same Python environment/dependencies as the normal launcher.
import subprocess
def fail(kind,error,tb):
    import traceback
    traceback.print_exception(kind,error,tb);sys.stderr.flush();sys.stdout.flush();os._exit(1)
sys.excepthook=fail
tracked=subprocess.check_output(['git','ls-files'],cwd=ROOT,text=True).splitlines()
hashes={p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in tracked if (ROOT/p).exists()}
local_hashes={p:hashlib.sha256(p.read_bytes()).hexdigest() for p in (ROOT/'labremote/config').rglob('*') if p.is_file() and '__pycache__' not in p.parts}
temp=tempfile.TemporaryDirectory(prefix='retemp-persistence-')
cfgroot=Path(temp.name)/'config';shutil.copytree(ROOT/'labremote/config',cfgroot)
from labremote.configuration import paths
paths.CONFIG_ROOT=cfgroot
from labremote import data_paths
data_paths.DATA_ROOT=Path(temp.name)/'data'
from PyQt5 import QtWidgets as W,QtCore
app=W.QApplication.instance() or W.QApplication([])
from labremote.ui.main_window import Window
from labremote.configuration.settings import DEFAULTS
from labremote.ui.input_state import InputState,value_of
from labremote.devices.fpga.mapping import scope
from labremote.runtime.discovery import DiscoveryWorker
from labremote.devices.fpga.ports import PortScanner

cfg=deepcopy(DEFAULTS)
cfg['equipment_configuration']=str(cfgroot/'ui/equipment.local.json')
def deny(*a,**k):raise AssertionError('Hardware I/O forbidden in persistence verification')

def make():
    w=Window(deepcopy(cfg));w._discovery_pending=False
    # Instantiate every supported device family, irrespective of saved equipment selection.
    for family in w.family_tabs:
        if not w.family_tabs[family]:w._add_family(family,'audit_'+family)
    if 'fpga_local' not in w.family_tabs['fpga']:w._add_family('fpga','fpga_local')
    fpga=w.family_tabs['fpga']['fpga_local'].worker
    names=[]
    for slot in w.experiment_workspace.slots:
        with scope(fpga.profile):view=slot.factory(fpga,w._bindings)
        slot.views[fpga.name]=view;view.setParent(slot);names.append(slot.settings_id)
    assert len(names)==len(set(names)),names
    w._add_family('fpga','audit_second_fpga')
    second=w.family_tabs['fpga']['audit_second_fpga'].worker
    slot=next(s for s in w.experiment_workspace.slots if s.settings_id=='characterization/EA/Rabi')
    with scope(second.profile):view=slot.factory(second,w._bindings)
    slot.views[second.name]=view;view.setParent(slot)
    w.input_state.restore()
    return w,names

def close(w):
    w.profile_dirty=False;w.queue_tab.dirty=False
    with patch.object(W.QMessageBox,'question',return_value=W.QMessageBox.Discard):
        w.close()
        end=time.monotonic()+10
        while w._running() and time.monotonic()<end:app.processEvents();time.sleep(.01)
        assert not w._running()
        w.close()
    w.deleteLater();QtCore.QCoreApplication.sendPostedEvents(None,QtCore.QEvent.DeferredDelete)

with patch.object(DiscoveryWorker,'scan',return_value=None),patch.object(PortScanner,'start'),patch.object(Window,'_scan'),patch.object(socket.socket,'connect',side_effect=deny):
    w,names=make()
    try:
        fields=w.input_state.fields();numbers=0;choices=0;checks=0;texts=0;expected={}
        migrated=0
        for key,old in w.input_state.older_keys.items():
            if old in w.input_state.saved and w.input_state.saved[old]['kind']=='number':
                assert value_of(fields[key])['value']==w.input_state.saved[old]['value'],(key,old)
                migrated+=1
        assert migrated>100,'Legacy FPGA values were not exercised'
        for key,widget in fields.items():
            entry=value_of(widget)
            if entry and entry['kind']=='number' and widget.minimum()<widget.maximum():
                # Signal blockers guarantee this test cannot Apply a setting.
                with QtCore.QSignalBlocker(widget):
                    delta=widget.singleStep() if hasattr(widget,'singleStep') else 1
                    new=widget.value()+delta
                    if new>widget.maximum():new=widget.value()-delta
                    widget.setValue(new)
                numbers+=1
            elif entry and entry['kind']=='check':
                with QtCore.QSignalBlocker(widget):widget.setChecked(not widget.isChecked())
                checks+=1
            elif entry and entry['kind']=='choice' and widget.count()>1 and not hasattr(widget,'route'):
                with QtCore.QSignalBlocker(widget):widget.setCurrentIndex((widget.currentIndex()+1)%widget.count())
                choices+=1
            elif entry and entry['kind']=='text' and key.rsplit('/',1)[-1] in ('name','title','alias'):
                with QtCore.QSignalBlocker(widget):widget.setText(widget.text()+' audit')
                texts+=1
            if key not in w.input_state.pending:expected[key]=value_of(widget)
        # Explicit model/table cases are not represented by ordinary numeric fields.
        dac=next(iter(w.family_tabs['dac'].values()))
        from labremote.devices.dac.sequence import SequenceRow
        dac.sequence_tab.append([SequenceRow(dac.draft(),.123)])
        from labremote.runtime.experiment_jobs import source_job
        from labremote.runtime.workflow_queue import make_group
        job=source_job('def main(devices):\n    return None\n','audit.py','draft',{'delay':.321},None)
        w.queue_tab.jobs=[make_group([job],repeat=3)];w.queue_tab.refresh()
        raw='target_deg,quality,candidate_code,recommended_test_code,model_phase_deg\n0,reference_anchor,0,,0\n360,reference_anchor,0,,0\n'
        snapshot=dict(path='original.csv',csv=raw,sha256=hashlib.sha256(raw.encode()).hexdigest())
        rabi_raw=json.dumps(dict(experiment='phase_rabi',phases=[dict(code=0),dict(code=100)],fits=[dict(phase_index=i,valid=True,frequency_khz=100,error_khz=1) for i in range(2)]))
        rabi_snapshot=dict(path='rabi.json',json=rabi_raw,sha256=hashlib.sha256(rabi_raw.encode()).hexdigest(),method='halfpi_time_linear_v1')
        from labremote.ui.persistence_models import capture
        for widget in w.input_state.model_widgets.values():
            if type(widget).__name__=='CalibrationSelector':widget.set_table(deepcopy(snapshot))
            elif hasattr(widget,'halfpi_source'):widget.set_source(deepcopy(rabi_snapshot))
        slot=next(s for s in w.experiment_workspace.slots if s.settings_id=='characterization/EA/Rabi')
        slot.selected='audit_second_fpga'
        for i,view in enumerate(slot.views.values()):
            numeric=next(v for v in view.fields.values() if isinstance(v,W.QDoubleSpinBox))
            with QtCore.QSignalBlocker(numeric):numeric.setValue(numeric.minimum()+numeric.singleStep()*(i+3))
        # Keep harmless read-only paths valid; do not alter source editors.
        start=time.perf_counter()
        assert w.input_state.save()
        save_seconds=time.perf_counter()-start
        start=time.perf_counter();assert w.input_state.save();idle_save_seconds=time.perf_counter()-start
        original={'inputs':deepcopy(w.input_state.saved),'models':deepcopy(w.input_state.models)}
        model_expected={k:capture(v) for k,v in w.input_state.model_widgets.items()}
        # Snapshot every field as it actually stood at the save boundary.
        expected={k:value_of(v) for k,v in w.input_state.fields().items() if k not in w.input_state.pending}
    finally:close(w)
    w2,names2=make()
    try:
        fields2=w2.input_state.fields();mismatch=[]
        for key,value in expected.items():
            if key not in fields2:mismatch.append((key,'missing'))
            elif key in w2.input_state.pending:mismatch.append((key,'restore pending'))
            elif key not in w2.input_state.pending and value_of(fields2[key])!=value:mismatch.append((key,value,value_of(fields2[key])))
        for key,value in model_expected.items():
            if capture(w2.input_state.model_widgets[key])!=value:mismatch.append((key,'model differs'))
        print(json.dumps({'tabs':len(names),'fields':len(fields),'numeric_roundtrips':numbers,'choice_roundtrips':choices,'check_roundtrips':checks,'model_roundtrips':len(model_expected),'legacy_numeric_values_preserved':migrated,'text_roundtrips':texts,'save_seconds':save_seconds,'idle_save_seconds':idle_save_seconds,'mismatches':mismatch[:35],'pending':list(w2.input_state.pending)[:15]},ensure_ascii=False,indent=2))
        assert not mismatch, f'{len(mismatch)} roundtrip mismatches'
        assert any(r.get('kind')=='table' and r.get('value') for r in original['inputs'].values())
    finally:close(w2)
assert all(hashlib.sha256((ROOT/p).read_bytes()).hexdigest()==h for p,h in hashes.items()),'Tracked file modified by app'
assert all(hashlib.sha256(p.read_bytes()).hexdigest()==h for p,h in local_hashes.items()),'Real local config modified by test'
print('PASS: all instantiated tab roundtrips, shutdown, tracked hashes and original config hashes unchanged')
temp.cleanup()
