"""Exercise a built release image without network access, model weights or keys.

Use a disposable container and volume. Only resources created by this invocation
are removed. Docker must be running; use DOCKER_HOST for a remote Docker engine.
"""
import argparse
import json
import subprocess
import sys
import uuid
from urllib.parse import urlsplit


PROBE = r'''
import io
import json
from pathlib import Path
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from zipfile import ZipFile

def request(path, body=None, headers=None):
    req = urllib.request.Request('http://127.0.0.1:8765' + path,
        data=json.dumps(body).encode() if body is not None else None,
        headers={'Content-Type': 'application/json', 'Host': urllib.parse.urlsplit(BACKEND).netloc, **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=5) as response:
            return response.status, response.headers, response.read()
    except urllib.error.HTTPError as response:
        return response.code, response.headers, response.read()

for attempt in range(50):
    try:
        if request('/healthz')[0] == 200:
            break
    except OSError:
        pass
    time.sleep(.1)
assert request('/healthz')[0] == 200, 'Liveness failed'
assert request('/readyz')[0] == 503, 'A missing model must not be ready'
assert request('/healthz', headers={'Host': 'unconfigured.invalid'})[0] == 403
assert request('/api/jobs', {'text': 'I prefer tea.'})[0] == 401
assert request('/.env')[0] == 404
assert request('/presentation.js')[0] == 200

status, _, raw = request('/clar-extension.zip')
assert status == 200, 'Extension download failed'
with ZipFile(io.BytesIO(raw)) as archive:
    config = archive.read('build-config.js').decode()
    origins = json.loads(re.search(r'backends: Object.freeze\((\[[^\n]+\])\)', config)[1])
    assert origins == [BACKEND], 'Container extension has incorrect backend origins'
    assert 'defaultProvider: "local"' in config
    manifest = json.loads(archive.read('manifest.json'))
    assert BACKEND in manifest['content_security_policy']['extension_pages']
    for name in ('LICENSE', 'NOTICE'):
        assert archive.read(name) == Path('/app', name).read_bytes()
    identity = json.loads(archive.read('identity.json'))['id']

status, headers, _ = request('/api/access', {'code': INVITE['access_code']})
assert status == 200, 'Invitation login failed'
cookie_header = headers.get('Set-Cookie')
assert all(flag in cookie_header for flag in ('Secure', 'HttpOnly', 'SameSite=Lax'))
cookie = cookie_header.split(';')[0]
status, _, raw = request('/api/extension-setup', headers={'Cookie': cookie, 'Sec-Fetch-Site': 'same-origin'})
assert status == 200 and json.loads(raw)['token'] == INVITE['extension_token']
auth = {'Authorization': 'Bearer ' + INVITE['extension_token'],
        'X-CLAR-Extension': identity, 'Origin': 'chrome-extension://' + identity}
assert request('/api/jobs', {'text': 'I prefer tea.'}, {**auth, 'Origin': 'https://unconfigured.invalid'})[0] == 403

class MockModel(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        self.reply({'models': [{'name': 'qwen2.5vl:3b'}]})

    def do_POST(self):
        data = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        properties = data.get('format', {}).get('properties', {})
        if 'statements' in properties:
            answer = {'statements': [{'id': 'C1', 'kind': 'opinion',
                'context': 'Personal preference', 'explanation': 'A preference.', 'retrieval_terms': []}]}
        else:
            answer = {'purpose': {'category': 'unclear', 'explanation': 'Personal preference', 'quote': ''},
                'desired_response': {'description': 'No clear action', 'quote': ''},
                'signals': [], 'reading_tip': 'Read the context.', 'limitations': 'Synthetic fixture'}
        self.reply({'done': True, 'done_reason': 'stop', 'model': 'qwen2.5vl:3b',
                    'message': {'content': json.dumps(answer)}})

    def reply(self, data):
        raw = json.dumps(data).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

mock = HTTPServer(('127.0.0.1', 11434), MockModel)
threading.Thread(target=mock.serve_forever, daemon=True).start()
payload = {'text': 'I prefer tea.', 'language': 'en', 'provider': 'local'}
status, _, raw = request('/api/jobs', payload, auth)
assert status in (200, 202), 'Authenticated job admission failed'
job = json.loads(raw)
job_id = job['job_id']
for attempt in range(100):
    if job['status'] not in ('queued', 'running'):
        break
    time.sleep(.1)
    status, _, raw = request('/api/jobs/' + job_id, headers=auth)
    assert status == 200, 'Job polling failed'
    job = json.loads(raw)
assert job['status'] == 'complete', 'Mock model job did not complete'
assert job['result']['overall']['label'] == 'OPINION'
status, _, raw = request('/api/jobs', payload, auth)
assert status in (200, 202) and json.loads(raw)['job_id'] == job_id, 'Retry must reuse the job'
assert request('/api/jobs', {**payload, 'text': 'I prefer coffee.'}, auth)[0] == 429, 'Daily quota was not enforced'
for attempt in range(65):
    if request('/readyz')[0] == 200:
        break
    time.sleep(.1)
assert request('/readyz')[0] == 200, 'Configured mock model must become ready'
mock.shutdown()
print('PASS: liveness/readiness, invitation/cookie/token auth, origin checks, quotas, retry, job completion and packaged extension')
'''


def stderr_detail(stderr, redactions=()):
    if isinstance(stderr, bytes):
        stderr = stderr.decode('utf-8', errors='replace')
    detail = stderr or ''
    for value in redactions:
        if value:
            detail = detail.replace(value, '[redacted]')
    detail = ''.join(character for character in detail if character.isprintable() or character in '\n\t')
    return detail.strip()[-4000:]


def docker(*args, input_text=None, timeout=45, redactions=()):
    command = ' '.join(args[:2])
    try:
        result = subprocess.run(['docker', *args], input=input_text, text=True,
                                capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired as error:
        detail = stderr_detail(error.stderr, redactions)
        raise RuntimeError('Docker command timed out: ' + command + ('\n' + detail if detail else '')) from None
    if result.returncode:
        # Do not print captured stdout: some commands return invitation secrets.
        detail = stderr_detail(result.stderr, redactions)
        raise RuntimeError('Docker command failed: ' + command + ('\n' + detail if detail else ''))
    return result.stdout


def inspect(container):
    return json.loads(docker('inspect', container))[0]


def cleanup_resources(label):
    """Discover by this run's label even when a create command timed out."""
    errors = []
    for listing, removal in (
        (('ps', '-aq', '--filter', 'label=' + label), ('rm', '-f', '-v')),
        (('volume', 'ls', '-q', '--filter', 'label=' + label), ('volume', 'rm')),
    ):
        try:
            resources = docker(*listing, timeout=30).splitlines()
        except (OSError, subprocess.SubprocessError, RuntimeError) as error:
            errors.append(str(error))
            continue
        for resource in resources:
            try:
                docker(*removal, resource, timeout=30)
            except (OSError, subprocess.SubprocessError, RuntimeError) as error:
                errors.append(str(error))
    return errors


def smoke(image, backend):
    suffix = uuid.uuid4().hex
    label = 'clar.smoke=' + suffix
    container = 'clar-release-test-' + suffix
    empty_container = container + '-empty'
    seed_container = container + '-seed'
    volume = container + '-data'
    common = ['--label', label, '--network', 'none', '--read-only', '--tmpfs', '/tmp:rw,noexec,nosuid,size=64m',
              '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges:true',
              '--pids-limit', '128', '--memory', '1g']
    try:
        docker('run', '-d', '--name', empty_container, *common, image)
        exit_code = docker('wait', empty_container, timeout=15).strip()
        assert exit_code != '0', 'Public startup without an invitation must fail'
        logs = subprocess.run(['docker', 'logs', empty_container], capture_output=True, text=True, timeout=10)
        assert 'Create a reviewer invitation' in logs.stdout + logs.stderr, 'Expected invitation startup error'
        print('PASS: public startup fails closed without an invitation')

        docker('volume', 'create', '--label', label, volume)
        seed = docker('run', '--rm', '--name', seed_container, '--label', label,
            '--network', 'none', '-v', volume + ':/data', image,
            'python', '-c', 'import json, manage_invites; print(json.dumps(manage_invites.create_invite("release-test")))')
        invite = json.loads(seed)
        docker('run', '-d', '--name', container, *common, '-v', volume + ':/data',
            '-e', 'PUBLIC_HOST=' + str(urlsplit(backend).hostname),
            '-e', 'DEFAULT_PROVIDER=local', '-e', 'LOCAL_MODEL=qwen2.5vl:3b',
            '-e', 'OLLAMA_BASE_URL=http://127.0.0.1:11434',
            '-e', 'CLAR_INVITE_DAILY_LIMIT=1', '-e', 'CLAR_GLOBAL_DAILY_LIMIT=1', image)
        info = inspect(container)
        assert info['Config']['User'] == '10001:10001', 'Container must run as the application user'
        assert info['HostConfig']['ReadonlyRootfs'], 'Container root must be read-only'
        prefix = 'INVITE = ' + repr(invite) + '\nBACKEND = ' + repr(backend) + '\n'
        secrets = (invite['access_code'], invite['extension_token'])
        print(docker('exec', '-i', container, 'python', '-', input_text=prefix + PROBE, redactions=secrets), end='')
        docker('stop', '--time', '10', container)
        assert inspect(container)['State']['ExitCode'] == 0, 'Graceful shutdown failed'
        docker('start', container)
        # Invitations and charged quota must survive the application restart.
        restart = r'''
import json, time, urllib.request, urllib.error
for attempt in range(50):
    try:
        with urllib.request.urlopen('http://127.0.0.1:8765/healthz', timeout=2) as response:
            if response.status == 200: break
    except OSError: pass
    time.sleep(.1)
request = urllib.request.Request('http://127.0.0.1:8765/api/access',
    data=json.dumps({'code': INVITE['access_code']}).encode(), headers={'Content-Type': 'application/json'})
with urllib.request.urlopen(request, timeout=5) as response:
    assert response.status == 200
assert json.loads(open('/data/usage.json').read())['global'] == 1
print('PASS: non-root/read-only execution, graceful shutdown and persistent invitations/usage after restart')
'''
        print(docker('exec', '-i', container, 'python', '-', input_text=prefix + restart, redactions=secrets), end='')
    finally:
        original_error = sys.exc_info()[1]
        cleanup_errors = cleanup_resources(label)
        if cleanup_errors:
            message = 'Container smoke cleanup failed:\n' + '\n'.join(cleanup_errors)
            if original_error is None:
                raise RuntimeError(message)
            print(message, file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', default='clar:ci', help='Already-built image to test')
    parser.add_argument('--backend', default='https://clar.example.test', help='CLAR_BACKEND used when building this image')
    args = parser.parse_args()
    try:
        smoke(args.image, args.backend)
    except (OSError, subprocess.SubprocessError, AssertionError, RuntimeError, ValueError) as error:
        print('Container smoke failed: ' + str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
