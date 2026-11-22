"""Actual window restart regression, with isolated config and no device connections."""
import hashlib,json,os,shutil,socket,subprocess,sys,tempfile,time,warnings
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
os.environ['QT_QPA_PLATFORM']='offscreen';warnings.filterwarnings('ignore',message='Glyph .* missing from font')
def fail(kind,error,tb):
    import traceback
    traceback.print_exception(kind,error,tb);sys.stderr.flush();sys.stdout.flush();os._exit(1)
sys.excepthook=fail
tracked=subprocess.check_output(['git','ls-files','-z'],cwd=ROOT).decode().split('\0')
originals={ROOT/p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in tracked if p and (ROOT/p).is_file()}
originals.update({p:hashlib.sha256(p.read_bytes()).hexdigest() for p in (ROOT/'labremote/config').rglob('*') if p.is_file() and '__pycache__' not in p.parts})
with tempfile.TemporaryDirectory(prefix='retemp-endpoint-') as temporary:
    config=Path(temporary)/'config';shutil.copytree(ROOT/'labremote/config',config)
    from labremote.configuration import paths
    paths.CONFIG_ROOT=config
    from labremote import data_paths
    data_paths.DATA_ROOT=Path(temporary)/'data'
    local=config/'devices/connections.local.json';document=json.loads(local.read_text(encoding='utf8'))
    # Deliberately create all stale sources that previously defeated the real IP.
    for name in ('ui/defaults.json','ui/client_settings.local.json'):
        path=config/name;data=json.loads(path.read_text(encoding='utf8')) if path.exists() else {}
        data.update(server_host='127.0.0.1',server_port=1);path.write_text(json.dumps(data))
    bad_key='connection_settings_window/qt/QScrollArea[0]/qt_scrollarea_viewport/QGroupBox[0]/QLineEdit[0]'
    for name in ('ui/input_defaults.json','ui/input_state.local.json'):
        path=config/name;data=json.loads(path.read_text(encoding='utf8'));data.setdefault('inputs',{})[bad_key]={'kind':'text','value':'127.0.0.1'};path.write_text(json.dumps(data))
    modern=config/'ui/tabs/common/connection_settings_window.local.json';modern.parent.mkdir(parents=True,exist_ok=True)
    modern.write_text(json.dumps(dict(schema_version=1,inputs={bad_key:dict(kind='text',value='127.0.0.1')},models={})))
    from PyQt5 import QtWidgets as W,QtCore
    app=W.QApplication.instance() or W.QApplication([])
    from labremote.ui.main_window import Window
    from labremote.configuration.settings import load_settings
    from labremote.runtime.discovery import DiscoveryWorker
    from labremote.devices.fpga.ports import PortScanner
    scans=[]
    def no_io(*a,**k):raise AssertionError('Device connection forbidden')
    def make(override=None):
        cfg=load_settings();cfg['equipment_configuration']=str(config/'ui/equipment.local.json')
        if override:cfg.update(server_host=override[0],server_port=override[1])
        window=Window(cfg);window.input_state.restore();app.processEvents();return window
    def close(w):
        w.profile_dirty=False;w.queue_tab.dirty=False
        with patch.object(W.QMessageBox,'question',return_value=W.QMessageBox.Discard):
            w.close();end=time.monotonic()+10
            while w._running() and time.monotonic()<end:app.processEvents();time.sleep(.01)
            assert not w._running();w.close()
        w.deleteLater();QtCore.QCoreApplication.sendPostedEvents(None,QtCore.QEvent.DeferredDelete)
    with patch.object(DiscoveryWorker,'scan',side_effect=lambda *args:scans.append(args)),patch.object(PortScanner,'start'),patch.object(socket.socket,'connect',side_effect=no_io):
        w=make()
        try:
            initial=(document['server_host'],document['server_port'])
            assert w._endpoint()==initial,(w._endpoint(),initial)
            assert scans[-1]==initial,scans
            assert w.input_state.save(),'Empty queue blocked general UI save'
            assert w.discovery_host not in w.input_state.fields().values()
            assert w.discovery_port not in w.input_state.fields().values()
            w.discovery_host.setText('new-server.example');w.discovery_port.setValue(6007)
            w.discovery_host.editingFinished.emit()
            saved=json.loads(local.read_text());assert (saved['server_host'],saved['server_port'])==('new-server.example',6007)
            assert {k:v for k,v in saved.items() if k.startswith('motor_')}=={k:v for k,v in document.items() if k.startswith('motor_')}
        finally:close(w)
        w=make()
        try:
            assert w._endpoint()==('new-server.example',6007)
            assert scans[-1]==('new-server.example',6007)
            assert w.input_state.save()
        finally:close(w)
        cli=('session-only.example',6008);before=local.read_bytes();w=make(cli)
        try:assert w._endpoint()==cli;assert scans[-1]==cli
        finally:close(w)
        assert local.read_bytes()==before,'CLI override unexpectedly persisted'
    client=json.loads((config/'ui/client_settings.local.json').read_text())
    assert 'server_host' not in client and 'server_port' not in client
assert all(p.is_file() and hashlib.sha256(p.read_bytes()).hexdigest()==h for p,h in originals.items()),'Test changed real config or tracked source'
print(json.dumps(dict(stale_localhost_ignored=True,initial_endpoint=initial,ui_edit_survives_restart=True,cli_override_session_only=True,motor_values_preserved=True,actual_discovery_calls=scans,real_config_and_tracked_hashes_unchanged=True),indent=2))
