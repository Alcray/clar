"""Exercise the async HTTP contract with real invitation/quota logic, no models."""
import http.client
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

import analysis
import manage_invites
from jobs import JobManager

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('clar_job_test_server', ROOT / 'server.py')
server = importlib.util.module_from_spec(spec)
with patch.dict(os.environ, {}, clear=True), patch.object(Path, 'exists', return_value=False):
    spec.loader.exec_module(server)


class JobAccessTests(unittest.TestCase):
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
        directory = self.enterContext(tempfile.TemporaryDirectory())
        self.invites = Path(directory) / 'invites.json'
        self.usage = Path(directory) / 'usage.json'
        self.alice = manage_invites.create_invite('alice', self.invites)
        self.bob = manage_invites.create_invite('bob', self.invites)
        self.manager = JobManager(workers=2)
        self.addCleanup(self.manager.executor.shutdown, wait=True)
        self.started = threading.Event()
        self.release = threading.Event()
        self.addCleanup(self.release.set)
        self.enterContext(patch.object(server, 'JOBS', self.manager))
        self.enterContext(patch.object(server, 'PUBLIC_MODE', True))
        self.enterContext(patch.object(server, 'PUBLIC_HOST', 'clar.example.test'))
        self.enterContext(patch.object(server, 'ALLOWED_HOSTS', {'clar.example.test', '127.0.0.1'}))
        self.enterContext(patch.object(server, 'INVITES_PATH', self.invites))
        self.enterContext(patch.object(server, 'USAGE_PATH', self.usage))
        self.enterContext(patch.object(server, 'GATE', threading.BoundedSemaphore(2)))
        self.enterContext(patch.dict(os.environ, {'VERTEX_API_KEY': 'fake-test-server-key'}, clear=True))
        self.analyze = self.enterContext(patch.object(analysis, 'analyze', side_effect=self.run_analysis))
        self.precheck = self.enterContext(patch.object(analysis, 'precheck', side_effect=self.run_precheck))

    def run_analysis(self, body, key, model, provider='gemini', progress=None):
        if progress:
            progress('reading', 'done')
            progress('origin', 'done')
            progress('sources', 'running')
        self.started.set()
        self.release.wait(3)
        if progress:
            progress('sources', 'done')
            progress('factchecks', 'skipped')
            progress('formatting', 'done')
        return {'original_text': body['text'], 'overall': {'label': 'UNVERIFIED_CLAIM', 'is_preliminary': False}}

    def run_precheck(self, body, key, model, provider='vertex', progress=None):
        progress('reading', 'done')
        progress('origin', 'done')
        progress('sources', 'skipped')
        progress('factchecks', 'skipped')
        progress('formatting', 'done')
        return {'original_text': body['text'], 'overall': {'label': 'CHECKABLE_CLAIMS', 'is_preliminary': True}}

    def headers(self, invite=None):
        invite = invite or self.alice
        return {'Origin': server.EXTENSION_ORIGIN, 'Authorization': 'Bearer ' + invite['extension_token'],
                'X-CLAR-Extension': server.EXTENSION_ID}

    def request(self, method, path, headers=None, body=None):
        request_headers = {'Host': 'clar.example.test'}
        request_headers.update(headers or {})
        if body is not None:
            request_headers.setdefault('Content-Type', 'application/json')
            body = json.dumps(body)
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=4)
        try:
            conn.request(method, path, body=body, headers=request_headers)
            response = conn.getresponse()
            raw = response.read()
            return response.status, dict(response.getheaders()), json.loads(raw) if raw else None
        finally:
            conn.close()

    def start(self, **changes):
        payload = {'text': 'A factual claim about Moldova.', 'provider': 'vertex', 'language': 'en', **changes}
        status, headers, job = self.request('POST', '/api/jobs', self.headers(), payload)
        self.assertIn(status, (200, 202), job)
        return job

    def complete(self, job):
        self.release.set()
        self.manager.jobs[job['job_id']]['future'].result(timeout=3)
        return self.request('GET', '/api/jobs/' + job['job_id'], self.headers())[2]

    def test_jobs_require_access_and_owner_cannot_read_or_cancel_another_review(self):
        status, _, _ = self.request('POST', '/api/jobs', body={'text': 'A claim.', 'provider': 'vertex'})
        self.assertEqual(status, 401)
        job = self.start()
        self.assertTrue(self.started.wait(2))
        path = '/api/jobs/' + job['job_id']
        self.assertEqual(self.request('GET', path)[0], 401)
        self.assertEqual(self.request('GET', path, self.headers(self.bob))[0], 404)
        self.assertEqual(self.request('POST', path + '/cancel', self.headers(self.bob))[0], 404)
        own = self.request('GET', path, self.headers())
        self.assertEqual(own[0], 200)
        self.assertEqual(own[1]['Access-Control-Allow-Origin'], server.EXTENSION_ORIGIN)
        self.assertEqual(own[2]['status'], 'running')
        self.assertNotIn('original_text', json.dumps(own[2]))
        self.assertEqual(self.request('POST', path + '/cancel', self.headers())[2]['status'], 'cancelled')
        self.assertEqual(self.complete(job)['status'], 'cancelled')
        self.assertEqual(json.loads(self.usage.read_text())['global'], 1)

    def test_retries_and_cookie_extension_views_share_owner_and_one_charge(self):
        job = self.start()
        self.assertTrue(self.started.wait(2))
        retry = self.start(force=True)
        self.assertTrue(retry['reused'])
        self.assertEqual(retry['job_id'], job['job_id'])
        self.assertEqual(json.loads(self.usage.read_text())['global'], 1)
        store = manage_invites.read_store(self.invites)
        cookie = server.issue_session('alice', store['invites']['alice'], store)
        status, _, view = self.request('GET', '/api/jobs/' + job['job_id'], {'Cookie': 'clar_session=' + cookie})
        self.assertEqual(status, 200)
        self.assertEqual(view['job_id'], job['job_id'])
        stages = {step['id']: step['state'] for step in view['progress']['stages']}
        self.assertEqual(stages['sources'], 'running')
        self.assertEqual(stages['formatting'], 'pending')
        complete = self.complete(job)
        self.assertEqual(complete['result']['overall']['label'], 'UNVERIFIED_CLAIM')
        self.assertNotIn('fake-test-server-key', json.dumps(complete))
        cached = self.start()
        self.assertTrue(cached['reused'])
        self.assertEqual(cached['job_id'], job['job_id'])
        self.assertEqual(self.analyze.call_count, 1)
        self.assertEqual(json.loads(self.usage.read_text())['global'], 1)

    def test_revocation_blocks_existing_job_access(self):
        job = self.start()
        self.complete(job)
        manage_invites.revoke_invite('alice', self.invites)
        self.assertEqual(self.request('GET', '/api/jobs/' + job['job_id'], self.headers())[0], 401)
        self.assertEqual(self.request('POST', '/api/jobs/' + job['job_id'] + '/cancel', self.headers())[0], 401)

    def test_precheck_dispatch_progress_and_input_validation_before_quota(self):
        bad_inputs = [{'text': ''}, {'text': 'A claim.', 'task': 'unknown'}, {'text': 'A claim.', 'force': 'yes'},
                      {'text': 'A claim.', 'origin': 'not a structure'}, {'text': 'A claim.', 'provider': 'unknown'}]
        for payload in bad_inputs:
            status, _, _ = self.request('POST', '/api/jobs', self.headers(), {'provider': 'vertex', **payload})
            self.assertEqual(status, 400)
        self.assertFalse(self.usage.exists())
        job = self.start(task='precheck')
        result = self.complete(job)
        self.assertTrue(result['result']['overall']['is_preliminary'])
        stages = {step['id']: step['state'] for step in result['progress']['stages']}
        self.assertEqual(stages['sources'], 'skipped')
        self.assertEqual(stages['factchecks'], 'skipped')
        self.analyze.assert_not_called()
        self.precheck.assert_called_once()

    def test_quota_rejection_and_invalid_request_origin_do_not_enqueue(self):
        with patch.object(server, 'reserve_public_usage', return_value='invite'):
            status, _, data = self.request('POST', '/api/jobs', self.headers(), {'text': 'A claim.', 'provider': 'vertex'})
            self.assertEqual(status, 429)
            self.assertEqual(data['code'], 'daily_limit_reached')
        headers = {**self.headers(), 'Origin': 'https://www.facebook.com'}
        self.assertEqual(self.request('POST', '/api/jobs', headers, {'text': 'A claim.', 'provider': 'vertex'})[0], 403)
        self.assertFalse(self.manager.jobs)
        self.analyze.assert_not_called()

    def test_unlimited_daily_limits_accept_job_after_previous_caps(self):
        import datetime
        day = datetime.datetime.now(datetime.timezone.utc).date().isoformat()
        self.usage.write_text(json.dumps({'day': day, 'global': 90, 'per_invite': {'alice': 30}}))
        with patch.object(server, 'INVITE_DAILY_LIMIT', 0), patch.object(server, 'GLOBAL_DAILY_LIMIT', 0):
            job = self.start()
            self.assertEqual(self.complete(job)['status'], 'complete')
        usage = json.loads(self.usage.read_text())
        self.assertEqual(usage['per_invite']['alice'], 31)
        self.assertEqual(usage['global'], 91)

    def test_job_preflights_only_allow_route_method_pair(self):
        ident = 'x' * 32
        for path, method in (('/api/jobs', 'POST'), ('/api/jobs/' + ident, 'GET'), ('/api/jobs/' + ident + '/cancel', 'POST')):
            headers = {'Origin': server.EXTENSION_ORIGIN, 'Access-Control-Request-Method': method,
                       'Access-Control-Request-Headers': 'content-type, authorization, x-clar-extension'}
            self.assertEqual(self.request('OPTIONS', path, headers)[0], 204)
            headers['Access-Control-Request-Method'] = 'DELETE'
            self.assertEqual(self.request('OPTIONS', path, headers)[0], 403)

    def test_sync_analysis_api_remains_available(self):
        self.release.set()
        status, _, data = self.request('POST', '/api/analyze', self.headers(), {'text': 'A claim.', 'provider': 'vertex'})
        self.assertEqual(status, 200)
        self.assertEqual(data['original_text'], 'A claim.')
        self.assertIn('analysis_seconds', data)
        self.assertFalse(self.manager.jobs)
        self.analyze.assert_called_once()


if __name__ == '__main__':
    unittest.main()
