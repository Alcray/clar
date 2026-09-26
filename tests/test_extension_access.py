"""Exercise extension trust boundaries without loading credentials or calling models."""
from contextlib import ExitStack
import http.client
import importlib.util
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import threading
import types
import unittest
from unittest.mock import Mock, patch


SERVER_PATH = Path(__file__).resolve().parents[1] / 'server.py'
spec = importlib.util.spec_from_file_location('clar_extension_test_server', SERVER_PATH)
server = importlib.util.module_from_spec(spec)
# server.py normally loads the developer's .env on import. These tests never do.
with patch.dict(os.environ, {}, clear=True), patch.object(Path, 'exists', return_value=False):
    spec.loader.exec_module(server)


class ExtensionAccessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = server.ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()
        cls.port = cls.httpd.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join(timeout=2)

    def setUp(self):
        self._contexts = ExitStack()
        self.addCleanup(self._contexts.close)
        self.token = 'test-only-pairing-token'
        self.analyze = Mock(return_value={'verdict': 'test result'})
        self.local_analyze = Mock(return_value={'verdict': 'test result'})
        self.status = Mock(return_value=True)
        self._contexts.enter_context(patch.dict(os.environ, {'EXTENSION_TOKEN': self.token}, clear=True))
        self._contexts.enter_context(patch.object(server, 'local_status', self.status))
        self._contexts.enter_context(patch.dict(sys.modules, {
            'analysis': types.SimpleNamespace(analyze=self.analyze, AnalysisError=type('AnalysisError', (Exception,), {})),
            'local_analysis': types.SimpleNamespace(analyze_local=self.local_analyze),
        }))

    def request(self, method, path, headers=None, body=None):
        request_headers = {'Host': '127.0.0.1:' + str(self.port)}
        request_headers.update(headers or {})
        if body is not None:
            request_headers.setdefault('Content-Type', 'application/json')
            body = json.dumps(body)
        connection = http.client.HTTPConnection('127.0.0.1', self.port, timeout=3)
        try:
            connection.request(method, path, body=body, headers=request_headers)
            response = connection.getresponse()
            raw = response.read()
            response_headers = dict(response.getheaders())
            data = json.loads(raw) if raw and response_headers.get('Content-Type', '').startswith('application/json') else raw
            return response.status, response_headers, data
        finally:
            connection.close()

    def extension_headers(self, origin=True, marker=False):
        headers = {'Authorization': 'Bearer ' + self.token}
        if origin:
            headers['Origin'] = server.EXTENSION_ORIGIN
        if marker:
            headers['X-CLAR-Extension'] = server.EXTENSION_ID
        return headers

    def assert_no_model_call(self):
        self.analyze.assert_not_called()
        self.local_analyze.assert_not_called()

    def test_valid_extension_post_and_cors(self):
        status, headers, data = self.request('POST', '/api/analyze', self.extension_headers(), {'provider': 'local'})
        self.assertEqual(status, 200)
        self.assertEqual(headers.get('Access-Control-Allow-Origin'), server.EXTENSION_ORIGIN)
        self.assertEqual(headers.get('Vary'), 'Origin')
        self.assertEqual(data['verdict'], 'test result')
        self.local_analyze.assert_called_once()

    def test_origin_authentication_matrix_never_invokes_analysis(self):
        cases = [
            ({'Origin': server.EXTENSION_ORIGIN}, 401, True),
            ({'Origin': server.EXTENSION_ORIGIN, 'Authorization': 'Bearer wrong'}, 401, True),
            ({'Origin': server.EXTENSION_ORIGIN, 'Authorization': 'Bearer \u00ff'}, 401, True),
            ({'Origin': 'chrome-extension://' + 'b' * 32, 'Authorization': 'Bearer ' + self.token}, 403, False),
            ({'Origin': 'https://www.facebook.com', 'Authorization': 'Bearer ' + self.token}, 403, False),
            ({'Origin': 'null'}, 403, False),
            ({'Origin': server.EXTENSION_ORIGIN + '/', 'Authorization': 'Bearer ' + self.token}, 403, False),
            ({'Origin': server.EXTENSION_ORIGIN, 'X-CLAR-Extension': 'wrong', 'Authorization': 'Bearer ' + self.token}, 403, True),
            ({'Authorization': 'Bearer ' + self.token}, 403, False),
            ({'X-CLAR-Extension': server.EXTENSION_ID}, 401, False),
            ({'X-CLAR-Extension': 'wrong', 'Authorization': 'Bearer ' + self.token}, 403, False),
        ]
        for request_headers, expected_status, cors in cases:
            with self.subTest(headers=request_headers):
                status, headers, _ = self.request('POST', '/api/analyze', request_headers, {'provider': 'local'})
                self.assertEqual(status, expected_status)
                self.assertEqual(headers.get('Access-Control-Allow-Origin'), server.EXTENSION_ORIGIN if cors else None)
                self.assert_no_model_call()

    def test_originless_extension_health_requires_marker_and_token(self):
        status, headers, data = self.request('GET', '/api/health', self.extension_headers(origin=False, marker=True))
        self.assertEqual(status, 200)
        self.assertTrue(data['local_ready'])
        self.assertNotIn('token', data)
        self.assertNotIn('Access-Control-Allow-Origin', headers)
        for request_headers in ({'X-CLAR-Extension': server.EXTENSION_ID}, {'Authorization': 'Bearer ' + self.token}):
            with self.subTest(headers=request_headers):
                self.assertIn(self.request('GET', '/api/health', request_headers)[0], (401, 403))
        self.assertEqual(self.status.call_count, 1)

    def test_missing_server_token_fails_closed(self):
        os.environ.pop('EXTENSION_TOKEN')
        self.assertEqual(self.request('POST', '/api/analyze', self.extension_headers(), {'provider': 'local'})[0], 401)
        self.assert_no_model_call()

    def test_extension_routes_are_limited(self):
        for method, path in [('GET', '/api/extension-setup'), ('GET', '/clar-extension.zip'), ('GET', '/'), ('GET', '/api/analyze'), ('POST', '/api/health'), ('HEAD', '/')]:
            with self.subTest(method=method, path=path):
                self.assertEqual(self.request(method, path, self.extension_headers(marker=True))[0], 403)
        self.assert_no_model_call()

    def test_preflight_needs_no_token_and_only_allows_explicit_routes(self):
        for path, method in server.EXTENSION_ROUTES.items():
            with self.subTest(path=path):
                status, headers, body = self.request('OPTIONS', path, {
                    'Origin': server.EXTENSION_ORIGIN,
                    'Access-Control-Request-Method': method,
                    'Access-Control-Request-Headers': 'content-type, Authorization, X-CLAR-Extension',
                })
                self.assertEqual(status, 204)
                self.assertEqual(body, b'')
                self.assertEqual(headers.get('Access-Control-Allow-Origin'), server.EXTENSION_ORIGIN)
                self.assertEqual(headers.get('Access-Control-Allow-Methods'), method)
                self.assertEqual(headers.get('Access-Control-Allow-Headers'), 'Content-Type, Authorization, X-CLAR-Extension')
                self.assertNotIn('Access-Control-Allow-Credentials', headers)
        self.assert_no_model_call()
        self.status.assert_not_called()

    def test_rejected_preflights(self):
        cases = [
            ('/api/analyze', 'https://www.facebook.com', 'POST', 'content-type'),
            ('/api/analyze', 'chrome-extension://' + 'b' * 32, 'POST', 'authorization'),
            ('/api/analyze', server.EXTENSION_ORIGIN, 'DELETE', 'authorization'),
            ('/api/analyze', server.EXTENSION_ORIGIN, 'POST', 'x-other-header'),
            ('/api/health', server.EXTENSION_ORIGIN, 'POST', 'authorization'),
            ('/api/extension-setup', server.EXTENSION_ORIGIN, 'GET', 'authorization'),
        ]
        for path, origin, method, requested_headers in cases:
            with self.subTest(path=path, origin=origin, method=method, requested_headers=requested_headers):
                status, headers, _ = self.request('OPTIONS', path, {
                    'Origin': origin, 'Access-Control-Request-Method': method,
                    'Access-Control-Request-Headers': requested_headers,
                })
                self.assertEqual(status, 403)
                self.assertEqual(headers.get('Access-Control-Allow-Origin'), server.EXTENSION_ORIGIN if origin == server.EXTENSION_ORIGIN else None)
                self.assertNotIn('Access-Control-Allow-Methods', headers)
        self.assert_no_model_call()

    def test_existing_same_origin_and_originless_web_analysis(self):
        for origin in (None, 'http://127.0.0.1:' + str(self.port), 'https://127.0.0.1:' + str(self.port)):
            with self.subTest(origin=origin):
                headers = {} if origin is None else {'Origin': origin}
                status, response_headers, _ = self.request('POST', '/api/analyze', headers, {'provider': 'local'})
                self.assertEqual(status, 200)
                self.assertNotIn('Access-Control-Allow-Origin', response_headers)
        self.assertEqual(self.local_analyze.call_count, 3)

    def test_same_origin_setup_and_extension_denial(self):
        for headers in ({'Sec-Fetch-Site': 'same-origin'}, {'Origin': 'http://127.0.0.1:' + str(self.port)}):
            status, response_headers, data = self.request('GET', '/api/extension-setup', headers)
            self.assertEqual(status, 200)
            self.assertEqual(data, {'extension_id': server.EXTENSION_ID, 'token': self.token, 'download_url': '/clar-extension.zip'})
            self.assertEqual(response_headers.get('Cache-Control'), 'no-store')
        for headers in ({}, {'Sec-Fetch-Site': 'cross-site'}, {'Sec-Fetch-Site': 'same-site'}, {'Origin': 'https://attacker.example'}, self.extension_headers(), self.extension_headers(origin=False, marker=True)):
            with self.subTest(headers=headers):
                status, _, data = self.request('GET', '/api/extension-setup', headers)
                self.assertEqual(status, 403)
                self.assertNotIn('token', data)

    def test_host_allowlist_blocks_rebinding_before_analysis(self):
        for host in ('attacker.example:' + str(self.port), '127.0.0.1.attacker.example', 'attacker.example@127.0.0.1', '127.0.0.1:invalid'):
            with self.subTest(host=host):
                request_headers = {**self.extension_headers(), 'Host': host}
                self.assertEqual(self.request('POST', '/api/analyze', request_headers, {'provider': 'local'})[0], 403)
        self.assert_no_model_call()
        for host in ('localhost:' + str(self.port), '[::1]:8765'):
            self.assertEqual(self.request('GET', '/api/health', {'Host': host})[0], 200)

    def test_configurable_host_allowlist(self):
        with patch.object(server, 'ALLOWED_HOSTS', {'clar.internal'}):
            self.assertEqual(self.request('GET', '/api/health', {'Host': 'clar.internal:12345'})[0], 200)
            self.assertEqual(self.request('GET', '/api/health')[0], 403)


class ExtensionTokenTests(unittest.TestCase):
    def setUp(self):
        self._contexts = ExitStack()
        self.addCleanup(self._contexts.close)
        self._contexts.enter_context(patch.dict(os.environ, {}, clear=True))
        self.directory = self._contexts.enter_context(tempfile.TemporaryDirectory())
        self.path = Path(self.directory) / '.env'

    def test_startup_persists_token_and_preserves_existing_settings(self):
        existing = '# existing configuration\nLOCAL_MODEL=example-model\nOTHER_SETTING=keep-this'
        self.path.write_text(existing)
        self.path.chmod(0o644)
        token = server.ensure_extension_token(self.path)
        self.assertGreaterEqual(len(token), 40)
        self.assertEqual(self.path.read_text(), existing + '\nEXTENSION_TOKEN=' + token + '\n')
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)
        os.environ.pop('EXTENSION_TOKEN')
        self.assertEqual(server.ensure_extension_token(self.path), token)
        self.assertEqual(self.path.read_text().count('EXTENSION_TOKEN='), 1)

    def test_existing_token_is_reused_without_rewriting_other_values(self):
        existing = "OTHER_SETTING=keep\nEXTENSION_TOKEN='existing-test-token'\n"
        self.path.write_text(existing)
        with patch.object(server.secrets, 'token_urlsafe') as generate:
            self.assertEqual(server.ensure_extension_token(self.path), 'existing-test-token')
            generate.assert_not_called()
        self.assertEqual(self.path.read_text(), existing)
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)

    def test_environment_token_is_honored(self):
        os.environ['EXTENSION_TOKEN'] = 'configured-test-token'
        self.path.write_text('OTHER_SETTING=keep\n')
        self.assertEqual(server.ensure_extension_token(self.path), 'configured-test-token')
        self.assertEqual(self.path.read_text(), 'OTHER_SETTING=keep\n')
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)

    def test_empty_token_setting_can_be_recovered_on_later_startup(self):
        self.path.write_text('EXTENSION_TOKEN=\nOTHER_SETTING=keep\n')
        token = server.ensure_extension_token(self.path)
        os.environ['EXTENSION_TOKEN'] = ''
        self.assertEqual(server.ensure_extension_token(self.path), token)


if __name__ == '__main__':
    unittest.main()
