"""Local storage regression checks; no hardware and no real settings writes."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from labremote.configuration.local_storage import migrate_storage, plan
from labremote.configuration import startup, micromotion


class LocalStorageTests(unittest.TestCase):
    def fixture(self, root):
        paths = {
            'labremote/data/dac/EA/presets/test.json': b'{"voltage": 0.16}',
            'labremote/phase_shifter/calibrations/a.csv': b'angle,code\n90,1024\n',
            'logs/operations/run/result.json': b'{"unchanged": true}',
            'docs/examples/queue.json': b'{"jobs":[]}',
            'docs/examples/example.py': b'print("keep tracked")',
        }
        for name, value in paths.items():
            p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(value)
        cfg=root/'labremote/config/ui/dac.local.json';cfg.parent.mkdir(parents=True)
        cfg.write_text(json.dumps({'gain':7,'preset_folder':str(root/'labremote/data/dac/EA/presets')}))
        return paths, cfg

    def test_dry_run_and_verified_migration_are_lossless_and_idempotent(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'repo';root.mkdir();paths,cfg=self.fixture(root)
            self.assertEqual(len(migrate_storage(root)['moves']),4)
            self.assertTrue((root/'logs/operations/run/result.json').exists())
            backup=Path(temp)/'backup'
            result=migrate_storage(root,backup,apply=True)
            for source,target in result['moves']:
                self.assertEqual((root/target).read_bytes(),paths[Path(source).as_posix()])
                self.assertFalse((root/source).exists())
                self.assertEqual((backup/'files'/source).read_bytes(),(root/target).read_bytes())
            saved=json.loads(cfg.read_text());self.assertEqual(saved['gain'],7)
            self.assertEqual(Path(saved['preset_folder']),root/'labremote/config/presets/dac/EA')
            self.assertEqual(plan(root),[])
            self.assertEqual(migrate_storage(root)['path_updates'],[])
            self.assertTrue((root/'docs/examples/example.py').exists())

    def test_conflict_preserves_both_and_makes_no_backup(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'repo';root.mkdir();self.fixture(root)
            target=root/'labremote/config/presets/dac/EA/test.json';target.parent.mkdir(parents=True);target.write_bytes(b'new')
            backup=Path(temp)/'backup'
            with self.assertRaises(ValueError):migrate_storage(root,backup,apply=True)
            self.assertFalse(backup.exists());self.assertEqual(target.read_bytes(),b'new')
            self.assertTrue((root/'labremote/data/dac/EA/presets/test.json').exists())

    def test_apply_requires_external_backup(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);self.fixture(root)
            with self.assertRaises(ValueError):migrate_storage(root,apply=True)
            with self.assertRaises(ValueError):migrate_storage(root,root/'backup',apply=True)
            self.assertTrue((root/'logs/operations/run/result.json').exists())

    def test_missing_bundle_has_actionable_error(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(startup,'CONFIG_ROOT',Path(temp)):
            with self.assertRaisesRegex(FileNotFoundError,'Restore this PC'):
                startup.require_local_configuration()

    def test_two_rf_defaults_are_read_from_local_files(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(micromotion,'CONFIG_ROOT',Path(temp)):
            for chamber, low, high in [('EA',.16,.9),('EC',.1,.19)]:
                path=micromotion.two_rf_settings_path(chamber);path.parent.mkdir(parents=True,exist_ok=True)
                path.write_text(json.dumps(dict(rf_low=low,rf_high=high)))
                self.assertEqual(micromotion.two_rf_settings(chamber)['rf_high'],high)
            path.write_text('{"rf_low":0.13,"rf_high":0.24}')
            self.assertEqual(micromotion.two_rf_settings('EC')['rf_high'],.24)


if __name__ == '__main__':unittest.main()
