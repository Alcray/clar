"""Production ASGI transport for the shared CLAR request service.

Run ``python -m app``. One process owns the bounded in-memory job queue;
multiple Uvicorn workers/replicas require an external job/state store first.
"""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from email.message import Message
import io
import fcntl
import ipaddress
import json
import mimetypes
import os
from pathlib import Path
import re
import threading
import time

import server


class ConfigurationError(RuntimeError):
    pass


def bounded_integer(name, default, minimum, maximum):
    try:
        value = int(os.environ.get(name, str(default)))
    except ValueError as exc:
        raise ConfigurationError(name + ' must be an integer.') from exc
    if not minimum <= value <= maximum:
        raise ConfigurationError('{} must be between {} and {}.'.format(name, minimum, maximum))
    return value


def loopback_host(value):
    if value == 'localhost':
        return True
    try:
        return ipaddress.ip_address(value).is_loopback
    except ValueError:
        return False


def validate_configuration():
    """Fail closed before accepting network traffic; never print credentials."""
    host = os.environ.get('HOST', '127.0.0.1')
    if not loopback_host(host) and not server.PUBLIC_MODE:
        raise ConfigurationError('A non-loopback HOST requires PUBLIC_MODE=1 and reviewer invitations.')
    if not re.fullmatch('[a-p]{32}', server.EXTENSION_ID):
        raise ConfigurationError('CLAR_EXTENSION_ID must be a valid Chrome extension ID.')
    if not server.ALLOWED_HOSTS or '*' in server.ALLOWED_HOSTS:
        raise ConfigurationError('Set explicit ALLOWED_HOSTS; wildcard hosts are not accepted.')
    for host_value in server.ALLOWED_HOSTS:
        try:
            ipaddress.ip_address(host_value)
        except ValueError:
            if not re.fullmatch(r'[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?', host_value):
                raise ConfigurationError('ALLOWED_HOSTS entries must be hostnames without schemes or ports.')
    if server.DEFAULT_PROVIDER not in ('local', 'gemini', 'vertex'):
        raise ConfigurationError('DEFAULT_PROVIDER must be local, gemini or vertex; use LOCAL_PROVIDER for the local adapter.')
    try:
        from model_runtime import config_from_env
        config_from_env(server.DEFAULT_PROVIDER)
    except (ValueError, TypeError) as exc:
        raise ConfigurationError(str(exc)) from None
    bounded_integer('PORT', 8765, 1, 65535)
    bounded_integer('CLAR_INVITE_DAILY_LIMIT', 30, 0, 1000000)
    bounded_integer('CLAR_GLOBAL_DAILY_LIMIT', 90, 0, 1000000)
    if os.environ.get('WEB_CONCURRENCY', '1') != '1':
        raise ConfigurationError('CLAR currently requires WEB_CONCURRENCY=1 for consistent jobs and quotas.')
    if server.PUBLIC_MODE:
        try:
            store = server.manage_invites.read_store(server.INVITES_PATH)
        except server.manage_invites.InviteStoreError as exc:
            raise ConfigurationError('Create a reviewer invitation before starting PUBLIC_MODE=1.') from exc
        if not any(server.manage_invites.active_invite(store, name) for name in store['invites']):
            raise ConfigurationError('PUBLIC_MODE=1 requires at least one active reviewer invitation.')
    server.RUNTIME_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not os.access(server.RUNTIME_DIR, os.W_OK):
        raise ConfigurationError('CLAR_RUNTIME_DIR must be writable by the application user.')
    if not server.PUBLIC_MODE:
        server.ensure_extension_token(server.RUNTIME_DIR / 'owner.env')


class MemoryRequest(server.RequestService):
    """Translate one already bounded ASGI request to the shared service."""
    runtime_models = True
    def __init__(self, scope, body):
        self.command = scope['method']
        self.path = scope['path']
        self.headers = Message()
        for name, value in scope.get('headers', []):
            self.headers[name.decode('latin-1')] = value.decode('latin-1')
        # ASGI has already decoded HTTP framing; supply the actual bounded length.
        del self.headers['Content-Length']
        self.headers['Content-Length'] = str(len(body))
        self.rfile, self.wfile = io.BytesIO(body), io.BytesIO()
        self.status = 500
        self.response_headers = []

    def send_response(self, status):
        self.status = status
        self.response_headers = []

    def send_header(self, name, value):
        self.response_headers.append((name.lower().encode('ascii'), str(value).encode('latin-1')))

    def finish_headers(self):
        pass

    def serve_static(self, head=False):
        # Paths are explicitly allowlisted before this call; no directory browsing,
        # untrusted path joining, encoded traversal, or symlinked static files.
        name = 'index.html' if self.path == '/' else self.path.lstrip('/')
        path = server.ROOT / 'public' / name
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 20_000_000:
            return self.send_json(404, {'error': 'Not found.'})
        raw = path.read_bytes()
        self.send_response(200)
        self.send_header('Content-Type', mimetypes.guess_type(name)[0] or 'application/octet-stream')
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        if not head:
            self.wfile.write(raw)

    def dispatch(self):
        try:
            if not server.allowed_host(self.headers):
                self.send_json(403, {'error': 'This server address is not allowed.'})
            elif self.command not in ('GET', 'HEAD', 'POST', 'OPTIONS'):
                self.send_json(405, {'error': 'Method not allowed.'}, [('Allow', 'GET, HEAD, POST, OPTIONS')])
            else:
                getattr(self, 'do_' + self.command)()
        except Exception:
            # Model exceptions, filesystem paths and credentials stay out of HTTP.
            self.wfile = io.BytesIO()
            self.send_json(500, {'error': 'The request could not finish. Please try again.'})
        return self.status, self.response_headers, self.wfile.getvalue()


async def respond(send, status, data, method='GET'):
    raw = json.dumps(data, ensure_ascii=False).encode('utf-8')
    await send({'type': 'http.response.start', 'status': status, 'headers': [
        (b'content-type', b'application/json; charset=utf-8'),
        (b'content-length', str(len(raw)).encode()), (b'cache-control', b'no-store'),
        (b'x-content-type-options', b'nosniff'),
    ]})
    await send({'type': 'http.response.body', 'body': b'' if method == 'HEAD' else raw})


class ClarASGI:
    def __init__(self):
        self.body_limit = bounded_integer('CLAR_MAX_BODY_BYTES', 8000000, 1024, 8000000)
        self.body_timeout = bounded_integer('CLAR_BODY_TIMEOUT', 15, 1, 120)
        self.request_timeout = bounded_integer('CLAR_REQUEST_TIMEOUT', 300, 5, 900)
        self.workers = bounded_integer('CLAR_HTTP_THREADS', 16, 2, 64)
        self.shutdown_timeout = bounded_integer('CLAR_SHUTDOWN_TIMEOUT', 30, 1, 120)
        self.slots = threading.BoundedSemaphore(self.workers)
        self.executor = ThreadPoolExecutor(max_workers=self.workers, thread_name_prefix='clar-http')
        self.ready = False
        self.runtime_lock = None
        self.readiness_at = 0
        self.readiness_value = False

    async def __call__(self, scope, receive, send):
        if scope['type'] == 'lifespan':
            return await self.lifespan(receive, send)
        if scope['type'] != 'http':
            return
        method = scope.get('method', 'GET')
        headers = Message()
        for key, value in scope.get('headers', []):
            headers[key.decode('latin-1')] = value.decode('latin-1')
        client = scope.get('client')
        if not server.PUBLIC_MODE and client and not loopback_host(client[0]):
            return await respond(send, 403, {'error': 'Remote access requires authenticated public mode.'}, method)
        if not server.allowed_host(headers):
            return await respond(send, 403, {'error': 'This server address is not allowed.'}, method)
        if not self.ready:
            return await respond(send, 503, {'error': 'The service is restarting.'}, method)
        if scope['path'] == '/healthz' and method in ('GET', 'HEAD'):
            return await respond(send, 200, {'status': 'ok'}, method)
        if scope['path'] == '/readyz' and method in ('GET', 'HEAD'):
            # Probe at most once per five seconds; readiness never sends content or
            # starts inference. Liveness is separate so a missing model is visible.
            if time.monotonic() - self.readiness_at > 5:
                self.readiness_at = time.monotonic()
                self.readiness_value = await asyncio.to_thread(self.provider_ready)
            return await respond(send, 200 if self.readiness_value else 503,
                                 {'status': 'ready' if self.readiness_value else 'model_unavailable'}, method)
        lengths = headers.get_all('Content-Length', [])
        if len(lengths) > 1 or (lengths and not re.fullmatch('[0-9]+', lengths[0])):
            return await respond(send, 400, {'error': 'Invalid request length.'}, method)
        if lengths and int(lengths[0]) > self.body_limit:
            return await respond(send, 413, {'error': 'The request is too large.'}, method)
        if not self.slots.acquire(blocking=False):
            return await respond(send, 503, {'error': 'The service is busy. Please retry shortly.', 'code': 'service_busy'}, method)
        transferred = False
        try:
            body = bytearray()
            async def read_body():
                while True:
                    event = await receive()
                    if event['type'] == 'http.disconnect':
                        return False
                    if event['type'] != 'http.request':
                        continue
                    body.extend(event.get('body', b''))
                    if len(body) > self.body_limit:
                        return 'large'
                    if not event.get('more_body', False):
                        return True
            try:
                outcome = await asyncio.wait_for(read_body(), timeout=self.body_timeout)
            except asyncio.TimeoutError:
                return await respond(send, 408, {'error': 'Request body timed out.'}, method)
            if outcome is False:
                return
            if outcome == 'large':
                return await respond(send, 413, {'error': 'The request is too large.'}, method)
            if lengths and len(body) != int(lengths[0]):
                return await respond(send, 400, {'error': 'Request length does not match its body.'}, method)
            request = MemoryRequest(scope, bytes(body))
            future = self.executor.submit(request.dispatch)
            # Release only after the real work ends, even if a client or timeout
            # stops awaiting it; timed-out requests cannot grow unbounded threads.
            future.add_done_callback(lambda _result: self.slots.release())
            transferred = True
            try:
                status, response_headers, raw = await asyncio.wait_for(
                    asyncio.shield(asyncio.wrap_future(future)), timeout=self.request_timeout)
            except asyncio.TimeoutError:
                return await respond(send, 504, {'error': 'The request timed out. Use the job API to resume a check.', 'code': 'request_timeout'}, method)
            await send({'type': 'http.response.start', 'status': status, 'headers': response_headers})
            await send({'type': 'http.response.body', 'body': raw})
        finally:
            if not transferred:
                self.slots.release()

    @staticmethod
    def provider_ready():
        if server.DEFAULT_PROVIDER == 'local':
            return server.local_status()
        if server.DEFAULT_PROVIDER == 'vertex':
            return bool(os.environ.get('VERTEX_API_KEY'))
        return bool(os.environ.get('GEMINI_API_KEY') or os.environ.get('GOOGLE_API_KEY'))

    async def lifespan(self, receive, send):
        while True:
            event = await receive()
            if event['type'] == 'lifespan.startup':
                try:
                    validate_configuration()
                    flags = os.O_CREAT | os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0)
                    descriptor = os.open(server.RUNTIME_DIR / 'service.lock', flags, 0o600)
                    try:
                        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    except OSError:
                        os.close(descriptor)
                        raise ConfigurationError('Another CLAR process owns this runtime directory. Use one process and one replica.')
                    self.runtime_lock = descriptor
                except (ConfigurationError, OSError) as exc:
                    await send({'type': 'lifespan.startup.failed', 'message': str(exc)})
                    return
                self.ready = True
                await send({'type': 'lifespan.startup.complete'})
            elif event['type'] == 'lifespan.shutdown':
                self.ready = False
                with server.JOBS.lock:
                    futures = []
                    for job in server.JOBS.jobs.values():
                        if job['status'] in ('queued', 'running'):
                            job['cancelled'].set()
                            job['status'] = 'cancelled'
                            job['future'].cancel()
                        if job.get('future'):
                            futures.append(asyncio.wrap_future(job['future']))
                if futures:
                    await asyncio.wait(futures, timeout=self.shutdown_timeout)
                server.JOBS.executor.shutdown(wait=False, cancel_futures=True)
                self.executor.shutdown(wait=False, cancel_futures=True)
                if self.runtime_lock is not None:
                    fcntl.flock(self.runtime_lock, fcntl.LOCK_UN)
                    os.close(self.runtime_lock)
                    self.runtime_lock = None
                await send({'type': 'lifespan.shutdown.complete'})
                return


def create_app():
    return ClarASGI()


def main():
    import uvicorn
    validate_configuration()
    uvicorn.run('app:create_app', factory=True,
                host=os.environ.get('HOST', '127.0.0.1'),
                port=bounded_integer('PORT', 8765, 1, 65535), workers=1,
                access_log=False, server_header=False, proxy_headers=False,
                limit_concurrency=bounded_integer('CLAR_CONNECTION_LIMIT', 64, 8, 512),
                limit_max_requests=100000, timeout_keep_alive=5,
                timeout_graceful_shutdown=bounded_integer('CLAR_SHUTDOWN_TIMEOUT', 30, 1, 120))


if __name__ == '__main__':
    main()
