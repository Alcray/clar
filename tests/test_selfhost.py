"""Production HTTP transport: real request decisions, fake model calls only."""
import asyncio
from email.message import Message
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

with patch.dict(os.environ, {'CLAR_LOAD_DOTENV': '0'}):
    import app
import manage_invites
from jobs import JobManager


class SelfHostTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.folder = self.enterContext(tempfile.TemporaryDirectory())
        self.root = Path(self.folder)
        self.invites = self.root / 'invites.json'
        self.alice = manage_invites.create_invite('alice', self.invites)
        self.bob = manage_invites.create_invite('bob', self.invites)
        self.enterContext(patch.dict(os.environ, {'CLAR_LOAD_DOTENV': '0', 'HOST': '127.0.0.1',
                                                  'VERTEX_API_KEY': 'test-not-a-secret'}, clear=True))
        self.enterContext(patch.object(app.server, 'PUBLIC_MODE', True))
        self.enterContext(patch.object(app.server, 'PUBLIC_HOST', 'clar.example.org'))
        self.enterContext(patch.object(app.server, 'ALLOWED_HOSTS', {'clar.example.org', '127.0.0.1'}))
        self.enterContext(patch.object(app.server, 'INVITES_PATH', self.invites))
        self.enterContext(patch.object(app.server, 'USAGE_PATH', self.root / 'usage.json'))
        self.enterContext(patch.object(app.server, 'RUNTIME_DIR', self.root))
        self.enterContext(patch.object(app.server, 'local_status', return_value=True))
        self.manager = JobManager()
        self.enterContext(patch.object(app.server, 'JOBS', self.manager))
        self.app = app.ClarASGI()
        self.app.ready = True
        self.addCleanup(self.app.executor.shutdown, wait=True, cancel_futures=True)
        self.addCleanup(self.manager.executor.shutdown, wait=True, cancel_futures=True)

    def extension_headers(self, invite=None):
        invite = invite or self.alice
        return {'Origin': app.server.EXTENSION_ORIGIN, 'X-CLAR-Extension': app.server.EXTENSION_ID,
                'Authorization': 'Bearer ' + invite['extension_token']}

    async def request(self, method, path, headers=None, body=None, events=None):
        pairs = [('Host', 'clar.example.org')]
        if isinstance(headers, list):
            pairs.extend(headers)
        elif headers:
            pairs.extend(headers.items())
        raw = b''
        if body is not None:
            pairs.append(('Content-Type', 'application/json'))
            raw = json.dumps(body).encode()
        scope = {'type': 'http', 'method': method, 'path': path,
                 'headers': [(str(k).lower().encode(), str(v).encode()) for k, v in pairs]}
        queue = list(events or [{'type': 'http.request', 'body': raw}])
        async def receive():
            return queue.pop(0)
        sent = []
        async def send(event):
            sent.append(event)
        await self.app(scope, receive, send)
        if not sent:
            return None
        status = sent[0]['status']
        out_headers = {k.decode(): v.decode() for k, v in sent[0]['headers']}
        raw = sent[1]['body']
        parsed = json.loads(raw) if raw and out_headers.get('content-type', '').startswith('application/json') else raw
        return status, out_headers, parsed

    async def test_authentication_precedes_job_creation(self):
        with patch.object(app.server, 'run_pipeline') as pipeline:
            status, _, error = await self.request('POST', '/api/jobs', body={'text': 'A claim.'})
            self.assertEqual(status, 401)
            self.assertEqual(error['code'], 'access_required')
            pipeline.assert_not_called()
            self.assertFalse(self.manager.jobs)

    async def test_job_access_is_scoped_and_uses_production_dispatch(self):
        def checked(body, provider, task, key, progress=None, runtime_models=False):
            self.assertTrue(runtime_models)
            progress('reading', 'done')
            return {'original_text': body['text'], 'overall': {'label': 'UNVERIFIED_CLAIM'}}
        with patch.object(app.server, 'run_pipeline', side_effect=checked):
            status, headers, result = await self.request('POST', '/api/jobs', self.extension_headers(),
                                                        {'text': 'A public claim.', 'provider': 'vertex'})
            self.assertEqual(status, 202, result)
            self.assertEqual(headers['access-control-allow-origin'], app.server.EXTENSION_ORIGIN)
            path = '/api/jobs/' + result['job_id']
            await asyncio.to_thread(self.manager.jobs[result['job_id']]['future'].result, 3)
            self.assertEqual((await self.request('GET', path, self.extension_headers(self.bob)))[0], 404)
            result = await self.request('GET', path, self.extension_headers())
            self.assertEqual(result[2]['status'], 'complete')
            self.assertEqual(json.loads((self.root / 'usage.json').read_text())['global'], 1)
            manage_invites.revoke_invite('alice', self.invites)
            self.assertEqual((await self.request('GET', path, self.extension_headers()))[0], 401)

    async def test_cookie_access_and_extension_cors(self):
        status, headers, _ = await self.request('POST', '/api/access', body={'code': self.alice['access_code']})
        self.assertEqual(status, 200)
        self.assertIn('Secure; HttpOnly; SameSite=Lax', headers['set-cookie'])
        cookie = headers['set-cookie'].split(';')[0]
        setup = await self.request('GET', '/api/extension-setup', {'Cookie': cookie, 'Sec-Fetch-Site': 'same-origin'})
        self.assertEqual(setup[2]['token'], self.alice['extension_token'])
        denied = await self.request('POST', '/api/jobs', {**self.extension_headers(), 'Origin': 'https://attacker.example'}, {'text': 'A claim'})
        self.assertEqual(denied[0], 403)
        preflight = await self.request('OPTIONS', '/api/jobs', {'Origin': app.server.EXTENSION_ORIGIN,
            'Access-Control-Request-Method': 'POST', 'Access-Control-Request-Headers': 'content-type,authorization,x-clar-extension'})
        self.assertEqual(preflight[0], 204)

    async def test_bounds_frame_validation_disconnect_and_head_allowlist(self):
        self.app.body_limit = 10
        oversized = await self.request('POST', '/api/jobs', events=[
            {'type': 'http.request', 'body': b'123456', 'more_body': True},
            {'type': 'http.request', 'body': b'789012', 'more_body': False}])
        self.assertEqual(oversized[0], 413)
        self.assertEqual((await self.request('POST', '/api/jobs', {'Content-Length': '11'}))[0], 413)
        self.assertEqual((await self.request('POST', '/api/jobs', [('Content-Length', '1'), ('Content-Length', '1')]))[0], 400)
        self.assertEqual((await self.request('POST', '/api/jobs', {'Content-Length': '3'}))[0], 400)
        self.assertIsNone(await self.request('POST', '/api/jobs', events=[{'type': 'http.disconnect'}]))
        self.assertEqual((await self.request('HEAD', '/.env'))[0], 404)
        self.assertEqual((await self.request('HEAD', '/index.html'))[0], 200)
        self.assertEqual((await self.request('GET', '/../../.env'))[0], 404)
        self.assertEqual((await self.request('DELETE', '/'))[0], 405)

    async def test_rebinding_duplicate_host_and_duplicate_auth_are_rejected(self):
        self.assertEqual((await self.request('GET', '/healthz', [('Host', 'attacker.example')]))[0], 403)
        self.assertEqual((await self.request('POST', '/api/jobs', list(self.extension_headers().items()) + [('Authorization', 'Bearer second')], {'text': 'Claim'}))[0], 403)

    async def test_liveness_readiness_busy_and_restart(self):
        self.assertEqual((await self.request('GET', '/healthz'))[2], {'status': 'ok'})
        with patch.object(self.app, 'provider_ready', return_value=False):
            self.assertEqual((await self.request('GET', '/readyz'))[0], 503)
        self.app.slots = threading.BoundedSemaphore(1)
        self.app.slots.acquire()
        self.assertEqual((await self.request('GET', '/'))[0], 503)
        self.assertEqual((await self.request('GET', '/healthz'))[0], 200)
        self.app.slots.release()
        self.app.ready = False
        self.assertEqual((await self.request('GET', '/healthz'))[0], 503)

    async def test_worker_slot_survives_client_timeout_until_work_finishes(self):
        release = threading.Event()
        self.addCleanup(release.set)
        self.app.slots = threading.BoundedSemaphore(1)
        self.app.request_timeout = 0.01
        def blocked(_request):
            release.wait(2)
            return 200, [], b''
        with patch.object(app.MemoryRequest, 'dispatch', blocked):
            self.assertEqual((await self.request('GET', '/'))[0], 504)
            self.assertEqual((await self.request('GET', '/'))[0], 503)
            release.set()
            for _ in range(100):
                if self.app.slots.acquire(blocking=False):
                    self.app.slots.release()
                    break
                await asyncio.sleep(0.001)
            else:
                self.fail('Timed-out work did not return its admission slot.')

    async def test_runtime_lock_rejects_second_process(self):
        descriptor = os.open(self.root / 'service.lock', os.O_RDWR | os.O_CREAT, 0o600)
        try:
            app.fcntl.flock(descriptor, app.fcntl.LOCK_EX | app.fcntl.LOCK_NB)
            sent = []
            async def receive():
                return {'type': 'lifespan.startup'}
            async def send(event):
                sent.append(event)
            await self.app({'type': 'lifespan'}, receive, send)
            self.assertEqual(sent[0]['type'], 'lifespan.startup.failed')
            self.assertIn('one process', sent[0]['message'])
        finally:
            os.close(descriptor)

    async def test_startup_fails_without_public_invite(self):
        with patch.object(app.server, 'INVITES_PATH', self.root / 'missing.json'):
            with self.assertRaisesRegex(app.ConfigurationError, 'Create a reviewer'):
                app.validate_configuration()
        manage_invites.revoke_invite('alice', self.invites)
        manage_invites.revoke_invite('bob', self.invites)
        with self.assertRaisesRegex(app.ConfigurationError, 'active reviewer'):
            app.validate_configuration()

    async def test_binding_config_and_runtime_token(self):
        with patch.object(app.server, 'PUBLIC_MODE', False), patch.dict(os.environ, {'HOST': '0.0.0.0'}):
            with self.assertRaisesRegex(app.ConfigurationError, 'non-loopback'):
                app.validate_configuration()
        with patch.dict(os.environ, {'WEB_CONCURRENCY': '2'}):
            with self.assertRaisesRegex(app.ConfigurationError, 'WEB_CONCURRENCY=1'):
                app.validate_configuration()
        with patch.object(app.server, 'PUBLIC_MODE', False):
            app.validate_configuration()
            token = os.environ.get('EXTENSION_TOKEN')
            self.assertGreater(len(token), 30)
            self.assertEqual((self.root / 'owner.env').stat().st_mode & 0o777, 0o600)

    async def test_body_timeout_and_shutdown(self):
        self.app.body_timeout = 0.01
        async def receive():
            await asyncio.sleep(1)
        sent = []
        async def send(event):
            sent.append(event)
        await self.app({'type': 'http', 'method': 'POST', 'path': '/api/jobs',
                        'headers': [(b'host', b'clar.example.org')]}, receive, send)
        self.assertEqual(sent[0]['status'], 408)
        events = [{'type': 'lifespan.shutdown'}]
        async def receive_shutdown():
            return events.pop(0)
        sent.clear()
        await self.app({'type': 'lifespan'}, receive_shutdown, send)
        self.assertFalse(self.app.ready)
        self.assertEqual(sent, [{'type': 'lifespan.shutdown.complete'}])


class ProductionSocketTests(unittest.TestCase):
    def test_uvicorn_entrypoint_invite_auth_static_and_shutdown(self):
        import http.client
        import importlib.util
        import socket
        import subprocess
        import sys
        import time
        if importlib.util.find_spec('uvicorn') is None:
            self.skipTest('Install requirements-server.txt to exercise the Uvicorn socket.')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            created = manage_invites.create_invite('socket-test', root / 'invites.json')
            with socket.socket() as sock:
                sock.bind(('127.0.0.1', 0))
                port = sock.getsockname()[1]
            env = {**os.environ, 'CLAR_LOAD_DOTENV': '0', 'HOST': '127.0.0.1', 'PORT': str(port),
                   'PUBLIC_MODE': '1', 'PUBLIC_HOST': '', 'ALLOWED_HOSTS': '127.0.0.1,localhost',
                   'DEFAULT_PROVIDER': 'local', 'LOCAL_PROVIDER': 'ollama', 'LOCAL_MODEL': 'test-only',
                   'OLLAMA_BASE_URL': 'http://127.0.0.1:1', 'CLAR_RUNTIME_DIR': directory,
                   'CLAR_INVITES_FILE': str(root / 'invites.json'), 'WEB_CONCURRENCY': '1',
                   'VERTEX_API_KEY': '', 'GEMINI_API_KEY': '', 'GOOGLE_API_KEY': ''}
            process = subprocess.Popen([sys.executable, '-m', 'app'], env=env,
                cwd=Path(__file__).resolve().parents[1], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            def request(method, path, body=None, headers=None):
                conn = http.client.HTTPConnection('127.0.0.1', port, timeout=3)
                try:
                    conn.request(method, path, body=json.dumps(body) if body is not None else None,
                                 headers={'Content-Type': 'application/json', **(headers or {})})
                    response = conn.getresponse()
                    return response.status, dict(response.getheaders()), response.read()
                finally:
                    conn.close()
            try:
                deadline = time.monotonic() + 10
                while True:
                    if process.poll() is not None:
                        self.fail('Uvicorn failed to start: ' + process.stderr.read().decode())
                    try:
                        if request('GET', '/healthz')[0] == 200:
                            break
                    except (OSError, http.client.HTTPException):
                        pass
                    if time.monotonic() >= deadline:
                        self.fail('Uvicorn did not become live.')
                    time.sleep(0.05)
                self.assertEqual(request('GET', '/')[0], 200)
                self.assertEqual(request('HEAD', '/.env')[0], 404)
                self.assertEqual(request('GET', '/readyz')[0], 503)
                self.assertEqual(request('POST', '/api/jobs', {'text': 'A claim.'})[0], 401)
                signed = request('POST', '/api/access', {'code': created['access_code']})
                self.assertEqual(signed[0], 200)
                cookie = next(v for k, v in signed[1].items() if k.lower() == 'set-cookie')
                result = request('POST', '/api/jobs', {'text': 'A claim.', 'provider': 'unsupported'},
                                 {'Cookie': cookie.split(';')[0]})
                self.assertEqual(result[0], 400)
                self.assertFalse((root / 'usage.json').exists())
                self.assertEqual(request('GET', '/', headers={'Host': 'attacker.example'})[0], 403)
            finally:
                process.terminate()
                try:
                    process.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=3)
                shutdown_log = process.stderr.read().decode()
                process.stderr.close()
            self.assertIn(process.returncode, (0, -15))
            self.assertIn('Application shutdown complete', shutdown_log)
            self.assertNotIn(created['access_code'], shutdown_log)


if __name__ == '__main__':
    unittest.main()
