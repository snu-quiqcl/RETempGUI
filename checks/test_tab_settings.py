"""Offline persistence regression checks; no hardware or repository config writes."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PyQt5 import QtWidgets as W
from labremote.configuration.tab_state import TabStateStore
from labremote.ui.input_state import InputState
APP=W.QApplication.instance() or W.QApplication([])

class TabSettingsTests(unittest.TestCase):
    def test_two_pc_values_survive_reload(self):
        with tempfile.TemporaryDirectory() as folder:
            for pc,number in [('EA',.16),('EC',.19)]:
                store=TabStateStore(Path(folder)/pc);store.load()
                key='device/sg384/trap/voltage';roots={'device/sg384/trap':None}
                store.save({key:{'kind':'number','value':number}},{},roots)
                # Reload is equivalent to replacing only application source on this PC.
                self.assertEqual(TabStateStore(store.root).load()[0][key]['value'],number)

    def test_external_change_rejects_all_writes(self):
        with tempfile.TemporaryDirectory() as folder:
            store=TabStateStore(folder);store.load();roots={'main':None}
            store.save({'main/a':1},{},roots)
            path=next(Path(folder).rglob('*.json'));external=path.read_bytes()+b' '
            path.write_bytes(external)
            with self.assertRaises(ValueError):store.save({'main/a':2},{},roots)
            self.assertEqual(path.read_bytes(),external)

    def test_device_names_do_not_collide(self):
        with tempfile.TemporaryDirectory() as folder:
            store=TabStateStore(folder)
            names=['rf.a','rf.b','CON','a/b','a_b','..','EA trap']
            roots={f'device/sg384/{n}':None for n in names}
            paths=[store.destination(k+'/value',roots) for k in roots]
            self.assertEqual(len(paths),len(set(paths)))
            self.assertTrue(all(p.resolve().is_relative_to(Path(folder).resolve()) for p in paths))

    def test_corrupt_file_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'input_state.local.json';path.write_text('{broken')
            w=W.QMainWindow();w.value=W.QSpinBox(w)
            with self.assertLogs('labremote.ui.input_state',level='WARNING'):state=InputState(w,path)
            state.restore();self.assertFalse(state.save());self.assertEqual(path.read_text(),'{broken')
            state.stop();w.deleteLater()

    def test_out_of_range_saved_value_is_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'state.json';key='main/value'
            path.write_text(json.dumps(dict(schema_version=1,inputs={key:dict(kind='number',value=1000)})))
            w=W.QMainWindow();w.value=W.QSpinBox(w);w.value.setRange(0,10)
            state=InputState(w,path)
            with self.assertLogs('labremote.ui.input_state',level='WARNING'):state.restore()
            self.assertIn(key,state.pending);self.assertTrue(state.save())
            self.assertEqual(json.loads(path.read_text())['inputs'][key]['value'],1000)
            w.value.setValue(7);w.value.editingFinished.emit();state.save()
            self.assertEqual(json.loads(path.read_text())['inputs'][key]['value'],7)
            state.stop();w.deleteLater()

    def test_legacy_migration_and_unknown_keys_are_lossless(self):
        with tempfile.TemporaryDirectory() as folder:
            config=Path(folder);(config/'ui').mkdir()
            legacy=config/'ui/input_state.local.json'
            legacy.write_text(json.dumps(dict(schema_version=1,inputs={'main/value':dict(kind='number',value=8),'unopened/tab':dict(kind='text',value='retain')},future={'a':1})))
            original=legacy.read_bytes()
            with patch('labremote.ui.input_state.CONFIG_ROOT',config):
                w=W.QMainWindow();w.value=W.QSpinBox(w);state=InputState(w);state.restore()
                self.assertEqual(w.value.value(),8);w.value.setValue(9);self.assertTrue(state.save());state.stop()
                self.assertEqual(legacy.read_bytes(),original)
                second=InputState(w);second.restore();self.assertEqual(w.value.value(),9)
                self.assertEqual(second.saved['unopened/tab']['value'],'retain');second.stop();w.deleteLater()

    def test_two_fpga_two_rf_fallback_is_validated(self):
        from labremote.configuration import micromotion
        with tempfile.TemporaryDirectory() as folder:
            config=Path(folder);base=config/'operations/micromotion';base.mkdir(parents=True)
            (base/'EA.two_rf.local.json').write_text(json.dumps(dict(rf_low=.9,rf_high=.16)))
            with patch.object(micromotion,'CONFIG_ROOT',config),patch.object(micromotion,'two_rf_settings_path',return_value=config/'isolated.local.json'):
                with self.assertRaises(ValueError):micromotion.two_rf_settings('EA')
                (base/'EA.two_rf.local.json').write_text(json.dumps(dict(rf_low=.16,rf_high=.9)))
                self.assertEqual(micromotion.two_rf_settings('EA')['rf_high'],.9)

    def test_manual_presets_are_scoped_per_fpga(self):
        from labremote.configuration import preset_paths
        from labremote.devices.fpga import mapping
        first=mapping.Profile(mapping.default_document('fpga_local'))
        second=mapping.Profile(mapping.default_document('test_other'))
        with tempfile.TemporaryDirectory() as folder:
            config=Path(folder)
            with patch.object(preset_paths,'CONFIG_ROOT',config),patch.object(mapping,'CONFIG_ROOT',config),patch.object(mapping,'ROOT',config/'devices/fpga'):
                with mapping.scope(first):a=preset_paths.experiment_preset_path('phase_shifter','ramsey.local.json')
                with mapping.scope(second):b=preset_paths.experiment_preset_path('phase_shifter','ramsey.local.json')
                self.assertNotEqual(a,b);self.assertTrue(a.parent.exists() and b.parent.exists())
                self.assertTrue(a.is_relative_to(config) and b.is_relative_to(config))

    def test_atomic_files_keep_extension_and_no_temp_remains(self):
        with tempfile.TemporaryDirectory() as folder:
            store=TabStateStore(folder);store.load();store.save({'device/rf/trap.a/f':1},{},{'device/rf/trap.a':None})
            path=Path(folder)/'rf/trap.a.local.json'
            self.assertTrue(path.exists());self.assertEqual(list(Path(folder).rglob('*.tmp')),[])

if __name__=='__main__':unittest.main()
