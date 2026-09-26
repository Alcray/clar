"""Public Funnel invitations protect model calls and extension pairing."""

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


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
SERVER_PATH = ROOT / 'server.py'
spec = importlib.util.spec_from_file_location('clar_public_test_server', SERVER_PATH)
server = importlib.util.module_from_spec(spec)
with patch.dict(os.environ, {}, clear=True), patch.object(Path, 'exists', return_value=False):
    spec.loader.exec_module(server)

import manage_invites  # noqa: E402


class PublicAccessTests(unittest.TestCase):
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
        self.directory = self.enterContext(tempfile.TemporaryDirectory())
        self.invites_path = Path(self.directory) / 'invites.json'
        self.usage_path = Path(self.directory) / 'usage.json'
        self.feedback_path = Path(self.directory) / 'feedback.jsonl'
        self.created = manage_invites.create_invite('reviewer-1', self.invites_path)
        self.owner_token = 'private-owner-token-do-not-use-publicly'
        self.local_analyze = Mock(return_value={'verdict': 'test result'})
        self.enterContext(patch.object(server, 'PUBLIC_MODE', True))
        self.enterContext(patch.object(server, 'PUBLIC_HOST', 'clar.example.org'))
        self.enterContext(patch.object(server, 'INVITES_PATH', self.invites_path))
        self.enterContext(patch.object(server, 'USAGE_PATH', self.usage_path))
        self.enterContext(patch.object(server, 'FEEDBACK_PATH', self.feedback_path))
        self.enterContext(patch.object(server, 'ALLOWED_HOSTS', {
            '127.0.0.1', 'localhost', 'private.clar.example.org', 'clar.example.org',
        }))
        self.enterContext(patch.dict(os.environ, {'EXTENSION_TOKEN': self.owner_token}, clear=True))
        self.enterContext(patch.object(server, 'local_status', return_value=True))
        self.enterContext(patch.dict(sys.modules, {
            'analysis': types.SimpleNamespace(
                analyze=Mock(return_value={'verdict': 'test result'}),
                AnalysisError=type('AnalysisError', (Exception,), {}),
            ),
            'local_analysis': types.SimpleNamespace(analyze_local=self.local_analyze),
        }))

    def request(self, method, path, headers=None, body=None):
        request_headers = {'Host': 'clar.example.org'}
        request_headers.update(headers or {})
        if body is not None:
            request_headers.setdefault('Content-Type', 'application/json')
            body = json.dumps(body)
        connection = http.client.HTTPConnection('127.0.0.1', self.port, timeout=4)
        try:
            connection.request(method, path, body=body, headers=request_headers)
            response = connection.getresponse()
            raw = response.read()
            response_headers = dict(response.getheaders())
            data = json.loads(raw) if raw and response_headers.get('Content-Type', '').startswith('application/json') else raw
            return response.status, response_headers, data
        finally:
            connection.close()

    def sign_in(self, headers=None, code=None):
        status, response_headers, data = self.request('POST', '/api/access', headers, {
            'code': self.created['access_code'] if code is None else code,
        })
        self.assertEqual(status, 200, data)
        return response_headers['Set-Cookie'].split(';', 1)[0], response_headers, data

    def extension_headers(self, token=None):
        return {
            'Origin': server.EXTENSION_ORIGIN,
            'X-CLAR-Extension': server.EXTENSION_ID,
            'Authorization': 'Bearer ' + (token if token is not None else self.created['extension_token']),
        }

    def test_anonymous_public_health_and_static_download_but_no_analysis_or_pairing(self):
        status, _, health = self.request('GET', '/api/health')
        self.assertEqual(status, 200)
        self.assertTrue(health['public_access_required'])
        self.assertFalse(health['access_granted'])
        self.assertNotIn('token', json.dumps(health).lower())
        self.assertEqual(self.request('GET', '/')[0], 200)
        self.assertEqual(self.request('GET', '/clar-extension.zip')[0], 200)
        for headers in ({}, {'Origin': 'https://clar.example.org'},
                        {'Host': '127.0.0.1:' + str(self.port)}):
            with self.subTest(headers=headers):
                status, _, data = self.request('POST', '/api/analyze', headers, {'provider': 'local'})
                self.assertEqual(status, 401)
                self.assertEqual(data['code'], 'access_required')
        status, _, data = self.request('GET', '/api/extension-setup', {'Sec-Fetch-Site': 'same-origin'})
        self.assertEqual(status, 401)
        self.assertNotIn('token', data)
        self.local_analyze.assert_not_called()

    def test_access_code_sets_secure_signed_cookie_and_grants_web_analysis(self):
        cookie, headers, data = self.sign_in({'Origin': 'https://clar.example.org',
                                              'Host': 'private.clar.example.org:8766'})
        self.assertEqual(data['name'], 'reviewer-1')
        self.assertIn('Secure', headers['Set-Cookie'])
        self.assertIn('HttpOnly', headers['Set-Cookie'])
        self.assertIn('SameSite=Lax', headers['Set-Cookie'])
        self.assertIn('Max-Age=604800', headers['Set-Cookie'])
        self.assertNotIn(self.created['access_code'], headers['Set-Cookie'])
        status, _, health = self.request('GET', '/api/health', {'Cookie': cookie})
        self.assertEqual(status, 200)
        self.assertTrue(health['access_granted'])
        status, _, result = self.request('POST', '/api/analyze',
                                         {'Cookie': cookie, 'Origin': 'https://clar.example.org',
                                          'Host': 'private.clar.example.org:8766'},
                                         {'provider': 'local'})
        self.assertEqual(status, 200, result)
        self.local_analyze.assert_called_once()
        self.assertEqual(self.usage_path.stat().st_mode & 0o777, 0o600)
        status, _, setup = self.request('GET', '/api/extension-setup', {
            'Cookie': cookie, 'Sec-Fetch-Site': 'same-origin',
        })
        self.assertEqual(status, 200, setup)
        self.assertEqual(setup['token'], self.created['extension_token'])
        self.assertNotEqual(setup['token'], self.owner_token)

    def test_invalid_code_bad_cookies_and_revocation_fail_closed(self):
        status, _, data = self.request('POST', '/api/access', body={'code': 'wrong-code'})
        self.assertEqual(status, 401)
        self.assertEqual(data['code'], 'invalid_access_code')
        cookie, _, _ = self.sign_in()
        name, value = cookie.split('=', 1)
        tampered = name + '=' + value[:-1] + ('A' if value[-1] != 'A' else 'B')
        for candidate in (tampered, cookie + '; ' + cookie, 'clar_session=garbage'):
            with self.subTest(candidate=candidate):
                self.assertEqual(self.request('POST', '/api/analyze', {'Cookie': candidate}, {'provider': 'local'})[0], 401)
        self.assertIsNone(server.verify_session(value, manage_invites.read_store(self.invites_path),
                                                 now=server.time.time() + server.SESSION_SECONDS + 1))
        self.assertTrue(manage_invites.revoke_invite('reviewer-1', self.invites_path))
        self.assertEqual(self.request('POST', '/api/analyze', {'Cookie': cookie}, {'provider': 'local'})[0], 401)
        self.assertEqual(self.request('POST', '/api/access', body={'code': self.created['access_code']})[0], 401)
        self.assertEqual(self.request('POST', '/api/analyze', self.extension_headers(), {'provider': 'local'})[0], 401)
        self.local_analyze.assert_not_called()

    def test_extension_uses_own_token_and_owner_token_is_rejected(self):
        status, headers, result = self.request('POST', '/api/analyze', self.extension_headers(), {'provider': 'local'})
        self.assertEqual(status, 200, result)
        self.assertEqual(headers['Access-Control-Allow-Origin'], server.EXTENSION_ORIGIN)
        self.local_analyze.assert_called_once()
        status, _, health = self.request('GET', '/api/health', self.extension_headers())
        self.assertEqual(status, 200)
        self.assertTrue(health['access_granted'])
        for token in (self.owner_token, self.created['access_code'], 'wrong'):
            with self.subTest(token=token):
                status, _, data = self.request('POST', '/api/analyze', self.extension_headers(token), {'provider': 'local'})
                self.assertEqual(status, 401)
                self.assertEqual(data['code'], 'extension_pairing_required')
        self.assertEqual(self.local_analyze.call_count, 1)

    def test_public_limit_is_per_invite_and_global_and_persists(self):
        reviewer_two = manage_invites.create_invite('reviewer-2', self.invites_path)
        reviewer_three = manage_invites.create_invite('reviewer-3', self.invites_path)
        reviewer_four = manage_invites.create_invite('reviewer-4', self.invites_path)
        for reviewer in (self.created, reviewer_two, reviewer_three):
            headers = self.extension_headers(reviewer['extension_token'])
            for _ in range(server.INVITE_DAILY_LIMIT):
                self.assertEqual(self.request('POST', '/api/analyze', headers, {'provider': 'local'})[0], 200)
            status, _, data = self.request('POST', '/api/analyze', headers, {'provider': 'local'})
            self.assertEqual(status, 429)
            self.assertEqual(data['code'], 'daily_limit_reached')
        status, _, data = self.request('POST', '/api/analyze', self.extension_headers(reviewer_four['extension_token']), {'provider': 'local'})
        self.assertEqual(status, 429)
        self.assertIn('all reviewers', data['error'])
        self.assertEqual(self.local_analyze.call_count, server.GLOBAL_DAILY_LIMIT)
        usage = json.loads(self.usage_path.read_text())
        self.assertEqual(usage['global'], server.GLOBAL_DAILY_LIMIT)

    def test_private_owner_path_remains_available(self):
        with patch.object(server, 'PUBLIC_MODE', False):
            private_host = {'Host': '127.0.0.1:' + str(self.port)}
            status, _, health = self.request('GET', '/api/health', private_host)
            self.assertEqual(status, 200)
            self.assertFalse(health['public_access_required'])
            self.assertTrue(health['access_granted'])
            status, _, result = self.request('POST', '/api/analyze', private_host, {'provider': 'local'})
            self.assertEqual(status, 200, result)
            status, _, setup = self.request('GET', '/api/extension-setup', {
                **private_host, 'Sec-Fetch-Site': 'same-origin',
            })
            self.assertEqual(status, 200)
            self.assertEqual(setup['token'], self.owner_token)
            status, _, result = self.request('POST', '/api/analyze', {
                **private_host, **self.extension_headers(self.owner_token),
            }, {'provider': 'local'})
            self.assertEqual(status, 200, result)
        self.assertFalse(self.usage_path.exists())

    def test_feedback_is_authenticated_validated_and_private(self):
        note = {'category': 'accuracy', 'message': 'The cited source does not support this date.',
                'post_url': 'https://www.facebook.com/example/posts/123', 'source': 'web'}
        self.assertEqual(self.request('POST', '/api/feedback', body=note)[0], 401)
        cookie, _, _ = self.sign_in()
        status, _, data = self.request('POST', '/api/feedback', {'Cookie': cookie}, note)
        self.assertEqual(status, 201, data)
        self.assertEqual(data, {'ok': True})
        self.assertEqual(stat.S_IMODE(self.feedback_path.stat().st_mode), 0o600)
        saved = json.loads(self.feedback_path.read_text().splitlines()[0])
        self.assertEqual(saved['reviewer'], 'reviewer-1')
        self.assertEqual(saved['message'], note['message'])
        self.assertEqual(set(saved), {'received_at', 'reviewer', 'category', 'message', 'post_url', 'source'})
        extension_note = {'category': 'design', 'message': 'Show the source near the verdict.',
                          'source': 'extension'}
        self.assertEqual(self.request('POST', '/api/feedback', self.extension_headers(), extension_note)[0], 201)
        for bad in (
            {**note, 'category': 'unsafe'},
            {**note, 'message': ''},
            {**note, 'post_url': 'https://attacker.example/post'},
            {**note, 'post_url': 'javascript:alert(1)'},
            {**note, 'analyzed_post': 'full text should not be stored'},
        ):
            with self.subTest(bad=bad):
                self.assertEqual(self.request('POST', '/api/feedback', {'Cookie': cookie}, bad)[0], 400)
        self.assertEqual(len(self.feedback_path.read_text().splitlines()), 2)

    def test_feedback_daily_limit(self):
        cookie, _, _ = self.sign_in()
        note = {'category': 'suggestion', 'message': 'A clear suggestion.', 'source': 'web'}
        for _ in range(server.FEEDBACK_DAILY_LIMIT):
            self.assertEqual(self.request('POST', '/api/feedback', {'Cookie': cookie}, note)[0], 201)
        status, _, data = self.request('POST', '/api/feedback', {'Cookie': cookie}, note)
        self.assertEqual(status, 429)
        self.assertEqual(data['code'], 'feedback_daily_limit')
        self.assertEqual(len(self.feedback_path.read_text().splitlines()), server.FEEDBACK_DAILY_LIMIT)


class InviteManagementTests(unittest.TestCase):
    def test_private_store_lists_without_secrets_and_revokes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'invites.json'
            created = manage_invites.create_invite('reviewer-1', path)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            raw = path.read_text()
            self.assertNotIn(created['access_code'], raw)
            self.assertIn(created['extension_token'], raw)
            listing = manage_invites.list_invites(path)
            self.assertEqual(listing[0]['status'], 'active')
            self.assertNotIn('token', json.dumps(listing))
            self.assertNotIn('code', json.dumps(listing))
            with self.assertRaises(ValueError):
                manage_invites.create_invite('reviewer-1', path)
            path.chmod(0o644)
            with self.assertRaises(manage_invites.InviteStoreError):
                manage_invites.read_store(path)
            path.chmod(0o600)
            self.assertTrue(manage_invites.revoke_invite('reviewer-1', path))
            self.assertEqual(manage_invites.list_invites(path)[0]['status'], 'revoked')


if __name__ == '__main__':
    unittest.main()
