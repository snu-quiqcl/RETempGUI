"""Canonical endpoints must not be replaced by old GUI state or defaults."""
import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from labremote.configuration import local_hardware as hardware,settings

class ConnectionSettingsTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);(self.root/'devices').mkdir()
        self.local=self.root/'devices/connections.json'
        self.base=self.root/'devices/connections.json';self.base.write_text('{}')
        (self.root/'client.json').write_text('{}')
        for target,name,value in ((hardware,'CONFIG_ROOT',self.root),(hardware,'LOCAL_HARDWARE',self.local),(settings,'SETTINGS',self.root/'client.json')):
            p=patch.object(target,name,value);p.start();self.addCleanup(p.stop)
    def seed(self,**values):
        self.local.write_text(json.dumps(dict(server_host='server.example',server_port=5555,motor_host='motor.example',motor_port=6001,**values)))
    def test_canonical_overrides_both_old_sources(self):
        self.seed();settings.SETTINGS.write_text(json.dumps(dict(server_host='127.0.0.1',server_port=1)))
        with patch.dict(settings.DEFAULTS,server_host='127.0.0.1',server_port=2):
            result=settings.load_settings()
        self.assertEqual((result['server_host'],result['server_port']),('server.example',5555))
    def test_missing_host_is_not_a_localhost_fallback(self):
        for values in ({},{'server_port':5555},{'server_host':'server.example'}):
            self.base.write_text(json.dumps(values))
            with self.subTest(values=values),self.assertRaisesRegex(ValueError,'server_host and server_port'):
                settings.load_settings()
    def test_save_retains_motor_endpoint_and_is_atomic(self):
        self.seed();hardware.save_server_endpoint('new.example',6002,expected=('server.example',5555))
        data=json.loads(self.local.read_text());self.assertEqual(data['server_host'],'new.example');self.assertEqual(data['server_port'],6002)
        self.assertEqual((data['motor_host'],data['motor_port']),('motor.example',6001));self.assertFalse(list(self.local.parent.glob('*.tmp')))
    def test_external_edit_is_preserved(self):
        self.seed();original=self.local.read_bytes()
        with self.assertRaisesRegex(ValueError,'outside this window'):hardware.save_server_endpoint('bad.example',7000,expected=('stale.example',5555))
        self.assertEqual(self.local.read_bytes(),original)
    def test_bad_edits_never_touch_disk(self):
        self.seed();original=self.local.read_bytes()
        for host,port in [('',5555),('bad host',5555),('host',True),('host',0),('host',65536)]:
            with self.subTest(host=host,port=port),self.assertRaises(ValueError):hardware.save_server_endpoint(host,port)
            self.assertEqual(self.local.read_bytes(),original)
    def test_ui_save_omits_endpoints(self):
        self.seed();original=self.local.read_bytes()
        settings.save_settings(dict(server_host='127.0.0.1',server_port=123,ccd_options={'gain':2}))
        self.assertEqual(json.loads(settings.SETTINGS.read_text()),{'ccd_options':{'gain':2}});self.assertEqual(self.local.read_bytes(),original)
    def test_explicit_localhost_remains_supported(self):
        self.seed();hardware.save_server_endpoint('127.0.0.1',5555)
        self.assertEqual(hardware.server_endpoint(),('127.0.0.1',5555))
    def test_populated_base_is_used_only_when_local_missing(self):
        self.base.write_text(json.dumps(dict(server_host='base.example',server_port=5556)))
        self.assertEqual(hardware.server_endpoint(),('base.example',5556))
        self.seed();self.assertEqual(hardware.server_endpoint(),('server.example',5555))

if __name__=='__main__':unittest.main()
