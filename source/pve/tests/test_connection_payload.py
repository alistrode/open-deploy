import hashlib
import importlib.util
import json
import pathlib
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).parents[1]
sys.path.insert(0, str(ROOT))
import media_payload as payload
spec = importlib.util.spec_from_file_location('preserve_connection', ROOT/'windows/preserve_connection.py')
backup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backup)


class ConnectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.tmp.name)
        self.source = self.root/'source'
        self.source.mkdir()
        self.target = self.root/'installed'
        self.live = self.root/'live'
        self.plan = {'id': 'test-plan', 'host': {'disk_serial': 'test'}}
        self.write(self.source/'plan.json', self.plan)
        digest = hashlib.sha256(json.dumps(self.plan, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        self.write(self.source/'state.json', {'plan_sha256': digest, 'phase': 'media_ready'})
        for name in payload.IDENTITY:
            path = self.source/'relay-state'/name
            path.parent.mkdir(exist_ok=True)
            path.write_text(name)
        node = self.source/'relay/SSH-Remote-Linux/runtime/node'
        node.parent.mkdir(parents=True)
        node.write_text('test runtime')

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value))

    def install(self):
        payload.install(self.source, self.target, self.live)

    def test_retry_preserves_progress_and_identity(self):
        self.install()
        self.write(self.target/'state.json', {'phase': 'host.done'})
        self.install()
        self.assertEqual(json.loads((self.target/'state.json').read_text())['phase'], 'host.done')
        (self.source/'relay-state/host_key').write_text('different')
        with self.assertRaisesRegex(ValueError, 'identity differs'):
            self.install()
        self.assertEqual((self.target/'relay-state/host_key').read_text(), 'host_key')

    def test_corrupt_archive_never_publishes_partial_payload(self):
        (self.source/'relay.tar.gz').write_bytes(b'bad archive')
        with self.assertRaisesRegex(ValueError, 'archive differs'):
            self.install()
        self.assertFalse(self.target.exists())
        self.assertFalse(list(self.root.glob('.opendeploy-*')))

    def test_interruption_before_publish_can_retry(self):
        with patch.object(payload.os, 'rename', side_effect=OSError('interrupted')):
            with self.assertRaises(OSError): self.install()
        self.assertFalse(self.target.exists())
        self.install()
        self.assertTrue(self.target.exists())

    def test_live_identity_mismatch_does_not_publish(self):
        self.live.mkdir()
        for name in payload.IDENTITY: (self.live/name).write_text('other')
        with self.assertRaisesRegex(ValueError, 'Running relay identity differs'):
            self.install()
        self.assertFalse(self.target.exists())

    def test_plan_state_mismatch_does_not_publish(self):
        self.write(self.source/'state.json', {'plan_sha256': 'wrong'})
        with self.assertRaisesRegex(ValueError, 'plan and state differ'):
            self.install()
        self.assertFalse(self.target.exists())

    def test_backup_is_verified_and_conflicts_preserved(self):
        job, usb = self.root/'job', self.root/'usb'
        usb.mkdir()
        self.write(job/'plan.json', self.plan)
        identity = dict(broker='test', session='s', secret='private', user='relay', fingerprint='fingerprint', clientPrivateKey='client_key')
        for name in backup.FILES:
            p = job/'ai-private'/name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(name)
        self.write(job/'ai-private/connection-private.json', identity)
        self.write(job/'media/payload/relay-state/remote.json', identity)
        saved = backup.preserve(job, usb)
        backup.preserve(job, usb)
        (job/'ai-private/client_key').write_text('new key')
        with self.assertRaisesRegex(ValueError, 'private key.*differ'):
            backup.preserve(job, usb)
        self.assertEqual((saved/'client_key').read_text(), 'client_key')


if __name__ == '__main__': unittest.main()
