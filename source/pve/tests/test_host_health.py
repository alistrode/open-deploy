import importlib.util
import pathlib
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('host_health', ROOT / 'host_health.py')
health = importlib.util.module_from_spec(spec)
spec.loader.exec_module(health)


class Response:
    def __init__(self, status, body):
        self.status, self.body = status, body

    def read(self):
        return self.body


class HostHealthTests(unittest.TestCase):
    def plan(self):
        return {'host': {'fqdn': 'opendeploy.home.arpa'},
                'host_password': 'Private<&Password'}

    def test_http_auth_failure_never_reports_ready_or_leaks_password(self):
        with patch.object(health.ssl, 'create_default_context'), \
             patch.object(health.http.client, 'HTTPSConnection') as connection:
            connection.return_value.getresponse.return_value = Response(401, b'Unauthorized')
            with self.assertRaisesRegex(RuntimeError, 'HTTPS readiness timed out') as caught:
                health.verify_api(self.plan(), timeout=0)
            self.assertNotIn(self.plan()['host_password'], str(caught.exception))
            connection.return_value.close.assert_called_once()

    def test_service_without_valid_api_version_is_not_healthy(self):
        with patch.object(health.ssl, 'create_default_context'), \
             patch.object(health.http.client, 'HTTPSConnection') as connection:
            connection.return_value.getresponse.side_effect = [
                Response(200, b'{"data":{"ticket":"test-ticket"}}'),
                Response(200, b'{"data":{}}')]
            with self.assertRaises(RuntimeError):
                health.verify_api(self.plan(), timeout=0)


if __name__ == '__main__':
    unittest.main()
