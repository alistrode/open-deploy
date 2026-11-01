import hashlib
import importlib.util
import pathlib
import tempfile
import unittest
from unittest.mock import patch
spec=importlib.util.spec_from_file_location('od_usb',pathlib.Path(__file__).resolve().parents[1]/'usb.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

class USBTests(unittest.TestCase):
    def test_regular_disk_paths_are_not_accepted(self):
        with self.assertRaises(ValueError):m.binding('/dev/sda')
        with self.assertRaises(ValueError):m.binding('/tmp/file')
    def test_corrupt_iso_stops_before_any_device_access(self):
        with tempfile.TemporaryDirectory() as d:
            p=pathlib.Path(d)/'iso';p.write_bytes(b'changed')
            with patch.object(m,'binding') as b:
                with self.assertRaises(ValueError):m.write(p,{'path':'unused'},'0'*64)
                b.assert_not_called()
    def test_device_identity_change_stops_before_unmount(self):
        with tempfile.TemporaryDirectory() as d:
            p=pathlib.Path(d)/'iso';p.write_bytes(b'iso')
            with patch.object(m,'binding',return_value={'serial':'different'}),patch.object(m,'unmount') as u:
                with self.assertRaises(ValueError):m.write(p,{'path':'device','serial':'approved'},hashlib.sha256(b'iso').hexdigest())
                u.assert_not_called()
    def test_running_root_is_not_unmounted(self):
        data='{"blockdevices":[{"name":"/dev/test","mountpoints":[],"children":[{"name":"/dev/test1","mountpoints":["/"]}]}]}'
        with patch.object(m,'command',return_value=data),patch.object(m.subprocess,'run') as run:
            with self.assertRaises(ValueError):m.unmount('device')
            run.assert_not_called()

if __name__=='__main__':unittest.main()
