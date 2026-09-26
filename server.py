"""CLAR request service and compatibility preview transport.

Production deployments use ``python -m app`` (Uvicorn/ASGI).
"""
import json
import hmac
import hashlib
import base64
import os
import secrets
from pathlib import Path
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse
import urllib.request
import threading
import time
import datetime
import tempfile
import re

import manage_invites
from jobs import JOBS, ANALYSIS_VERSION, JobError

ROOT = Path(__file__).resolve().parent


def load_env():
    if os.environ.get('CLAR_LOAD_DOTENV', '1') != '1':
        return
    path = Path(os.environ.get('CLAR_ENV_FILE', ROOT / '.env'))
    if path.exists():
        for line in path.read_text().splitlines():
            if line.strip() and not line.lstrip().startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_env()
EXTENSION_ID = os.environ.get('CLAR_EXTENSION_ID', 'ajlgkaeeokegabffalnaoncikpgniaci')
EXTENSION_ORIGIN = 'chrome-extension://' + EXTENSION_ID
EXTENSION_ROUTES = {'/api/health': 'GET', '/api/analyze': 'POST', '/api/feedback': 'POST'}
EXTENSION_HEADERS = {'content-type', 'authorization', 'x-clar-extension'}
JOB_PATH = re.compile(r'^/api/jobs/([A-Za-z0-9_-]{20,64})(/cancel)?$')


def api_method(path):
    if path == '/api/jobs':
        return 'POST'
    match = JOB_PATH.fullmatch(path)
    if match:
        return 'POST' if match.group(2) else 'GET'
    return EXTENSION_ROUTES.get(path)
ALLOWED_HOSTS = {
    host.strip().lower()
    for host in os.environ.get(
        'ALLOWED_HOSTS', 'localhost,127.0.0.1,::1'
    ).split(',') if host.strip()
}
PUBLIC_HOST = os.environ.get('PUBLIC_HOST', '').strip().lower()
PUBLIC_MODE = os.environ.get('PUBLIC_MODE', '') == '1'
if PUBLIC_HOST:
    ALLOWED_HOSTS.add(PUBLIC_HOST)
RUNTIME_DIR = Path(os.environ.get('CLAR_RUNTIME_DIR', ROOT / '.runtime'))
INVITES_PATH = Path(os.environ.get('CLAR_INVITES_FILE', RUNTIME_DIR / 'invites.json'))
USAGE_PATH = Path(os.environ.get('CLAR_USAGE_FILE', RUNTIME_DIR / 'usage.json'))
USAGE_LOCK = threading.Lock()
FEEDBACK_PATH = Path(os.environ.get('CLAR_FEEDBACK_FILE', RUNTIME_DIR / 'feedback.jsonl'))
FEEDBACK_LOCK = threading.Lock()
FEEDBACK_DAILY_LIMIT = 20
FEEDBACK_FILE_LIMIT = 10_000_000
INVITE_DAILY_LIMIT = int(os.environ.get('CLAR_INVITE_DAILY_LIMIT', '30'))
GLOBAL_DAILY_LIMIT = int(os.environ.get('CLAR_GLOBAL_DAILY_LIMIT', '90'))
SESSION_SECONDS = 7 * 24 * 60 * 60
MODEL = os.environ.get('GEMINI_MODEL', 'gemini-3.5-flash')
VERTEX_MODEL = os.environ.get('VERTEX_MODEL', 'gemini-3.5-flash')
LOCAL_MODEL = os.environ.get('LOCAL_MODEL', 'qwen2.5vl:3b')
LOCAL_LOCATION = os.environ.get('LOCAL_MODEL_LOCATION', 'the configured model server')
OLLAMA_BASE_URL = os.environ.get('OLLAMA_BASE_URL', 'http://127.0.0.1:11434').rstrip('/')
DEFAULT_PROVIDER = os.environ.get('DEFAULT_PROVIDER', 'local')
GATE = threading.BoundedSemaphore(2)
LOCAL_GATE = threading.BoundedSemaphore(1)


def _url64(raw):
    return base64.urlsafe_b64encode(raw).rstrip(b'=').decode('ascii')


def _unurl64(value):
    return base64.urlsafe_b64decode(value + '=' * (-len(value) % 4))


def issue_session(name, invite, data, now=None):
    """Sign a host-only, time-limited session bound to this invite generation."""
    now = int(time.time() if now is None else now)
    payload = _url64(json.dumps({
        'name': name, 'id': invite['id'], 'expires': now + SESSION_SECONDS,
    }, separators=(',', ':')).encode('utf-8'))
    signature = _url64(hmac.new(data['signing_key'].encode('ascii'),
                                 payload.encode('ascii'), hashlib.sha256).digest())
    return payload + '.' + signature


def verify_session(value, data, now=None):
    if not isinstance(value, str) or len(value) > 512:
        return None
    try:
        payload, supplied = value.split('.')
        expected = _url64(hmac.new(data['signing_key'].encode('ascii'),
                                    payload.encode('ascii'), hashlib.sha256).digest())
        if not hmac.compare_digest(supplied, expected):
            return None
        claims = json.loads(_unurl64(payload))
        if not isinstance(claims, dict) or not isinstance(claims.get('name'), str):
            return None
        expires = claims.get('expires')
        if not isinstance(expires, int) or expires <= int(time.time() if now is None else now):
            return None
        invite = manage_invites.active_invite(data, claims['name'], claims.get('id'))
        return (claims['name'], invite) if invite else None
    except (ValueError, UnicodeError, KeyError, TypeError):
        return None


def reserve_public_usage(name, path=None, now=None):
    """Persist a UTC-day reservation before calling a billable model."""
    path = Path(path) if path is not None else USAGE_PATH
    day = datetime.datetime.fromtimestamp(
        time.time() if now is None else now, datetime.timezone.utc
    ).date().isoformat()
    with USAGE_LOCK:
        if path.exists():
            try:
                if path.is_symlink() or path.stat().st_size > 1_000_000:
                    raise ValueError('Invalid usage file.')
                usage = json.loads(path.read_text(encoding='utf-8'))
                if not isinstance(usage, dict) or not isinstance(usage.get('per_invite'), dict):
                    raise ValueError('Invalid usage file.')
            except (OSError, ValueError, UnicodeError) as exc:
                raise RuntimeError('Daily usage could not be checked.') from exc
        else:
            usage = {'day': day, 'global': 0, 'per_invite': {}}
        if usage.get('day') != day:
            usage = {'day': day, 'global': 0, 'per_invite': {}}
        per_invite = usage['per_invite']
        try:
            invite_count = int(per_invite.get(name, 0))
            global_count = int(usage['global'])
        except (KeyError, TypeError, ValueError) as exc:
            raise RuntimeError('Daily usage could not be checked.') from exc
        if INVITE_DAILY_LIMIT and invite_count >= INVITE_DAILY_LIMIT:
            return 'invite'
        if GLOBAL_DAILY_LIMIT and global_count >= GLOBAL_DAILY_LIMIT:
            return 'global'
        per_invite[name] = invite_count + 1
        usage['global'] = global_count + 1
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=path.parent,
                                             prefix='.usage-', delete=False) as output:
                temporary = Path(output.name)
                os.fchmod(output.fileno(), 0o600)
                json.dump(usage, output, separators=(',', ':'), sort_keys=True)
                output.write('\n')
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, path)
            path.chmod(0o600)
        except OSError as exc:
            raise RuntimeError('Daily usage could not be saved.') from exc
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        return None


def save_feedback(reviewer, body, path=None, now=None):
    """Append only the submitted review fields; never persist analyzed content."""
    path = Path(path) if path is not None else FEEDBACK_PATH
    day = datetime.datetime.fromtimestamp(
        time.time() if now is None else now, datetime.timezone.utc
    ).date().isoformat()
    item = {
        'received_at': datetime.datetime.fromtimestamp(
            time.time() if now is None else now, datetime.timezone.utc
        ).isoformat(),
        'reviewer': reviewer,
        'category': body['category'],
        'message': body['message'],
        'post_url': body.get('post_url') or '',
        'source': body['source'],
    }
    raw = (json.dumps(item, ensure_ascii=False, separators=(',', ':')) + '\n').encode('utf-8')
    with FEEDBACK_LOCK:
        try:
            if path.is_symlink():
                raise ValueError('Invalid feedback file.')
            size = path.stat().st_size if path.exists() else 0
            if size + len(raw) > FEEDBACK_FILE_LIMIT:
                return 'full'
            count = 0
            if size:
                with path.open('r', encoding='utf-8') as existing:
                    for line in existing:
                        saved = json.loads(line)
                        if saved.get('reviewer') == reviewer and str(saved.get('received_at', '')).startswith(day):
                            count += 1
            if count >= FEEDBACK_DAILY_LIMIT:
                return 'daily'
            path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            with os.fdopen(descriptor, 'ab') as output:
                os.fchmod(output.fileno(), 0o600)
                output.write(raw)
                output.flush()
                os.fsync(output.fileno())
        except (OSError, UnicodeError, ValueError, TypeError, AttributeError) as exc:
            raise RuntimeError('Feedback could not be saved.') from exc
    return None


def ensure_extension_token(path=None):
    """Create the pairing secret at server startup, never during module import."""
    path = Path(path) if path is not None else ROOT / '.env'
    token = os.environ.get('EXTENSION_TOKEN', '').strip()
    if token:
        os.environ['EXTENSION_TOKEN'] = token
        if path.exists():
            path.chmod(0o600)
        return token
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT | os.O_APPEND, 0o600)
    with os.fdopen(descriptor, 'a+', encoding='utf-8') as env_file:
        os.fchmod(env_file.fileno(), 0o600)
        env_file.seek(0)
        existing = env_file.read()
        # Recover a persisted token even if an earlier empty setting was loaded.
        for line in existing.splitlines():
            if line.strip() and not line.lstrip().startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                if key.strip() == 'EXTENSION_TOKEN':
                    token = value.strip().strip('\"').strip("'") or token
        if not token:
            token = secrets.token_urlsafe(32)
            separator = '\n' if existing and not existing.endswith('\n') else ''
            env_file.write(separator + 'EXTENSION_TOKEN=' + token + '\n')
    os.environ['EXTENSION_TOKEN'] = token
    return token


def local_status():
    try:
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *args, **kwargs):
                return None
        opener = urllib.request.build_opener(NoRedirect())
        if os.environ.get('LOCAL_PROVIDER', 'ollama') == 'openai':
            base = os.environ.get('LOCAL_API_BASE_URL', 'http://127.0.0.1:8000/v1').rstrip('/')
            headers = {}
            key = os.environ.get(os.environ.get('LOCAL_API_KEY_ENV', 'LOCAL_API_KEY'), '')
            if key:
                headers['Authorization'] = 'Bearer ' + key
            request = urllib.request.Request(base + '/models', headers=headers)
            with opener.open(request, timeout=3) as response:
                models = json.loads(response.read(500000)).get('data', [])
            return any(m.get('id') == LOCAL_MODEL for m in models)
        request = urllib.request.Request(OLLAMA_BASE_URL + '/api/tags')
        key = os.environ.get(os.environ.get('LOCAL_API_KEY_ENV', 'LOCAL_API_KEY'), '')
        if key:
            request.add_header('Authorization', 'Bearer ' + key)
        with opener.open(request, timeout=3) as response:
            models = json.loads(response.read(500000)).get('models', [])
        return any(m.get('name') == LOCAL_MODEL for m in models)
    except Exception:
        return False


def run_pipeline(body, provider, task, api_key, progress=None, runtime_models=False):
    """One dispatch point; production uses the same adapters as benchmarks."""
    if runtime_models or os.environ.get('CLAR_MODEL_RUNTIME') == '1':
        from dataclasses import replace
        from model_runtime import config_from_env
        from pipeline_runtime import analyze_with_config, precheck_with_config
        config = config_from_env(provider)
        if api_key and provider in ('gemini', 'vertex'):
            config = replace(config, api_key=api_key.strip())
        call = precheck_with_config if task == 'precheck' else analyze_with_config
        return call(body, config, progress=progress)
    # Preserve the historical preview entry point and its direct adapter API.
    if provider == 'local':
        import local_analysis
        call = local_analysis.precheck_local if task == 'precheck' else local_analysis.analyze_local
        kwargs = {'progress': progress} if progress is not None else {}
        return call(body, OLLAMA_BASE_URL, LOCAL_MODEL, **kwargs)
    import analysis
    call = analysis.precheck if task == 'precheck' else analysis.analyze
    kwargs = {'progress': progress} if progress is not None else {}
    if provider == 'vertex' or task == 'precheck':
        kwargs['provider'] = provider
    return call(body, api_key.strip(), VERTEX_MODEL if provider == 'vertex' else MODEL, **kwargs)


STATIC_ROUTES = frozenset(('/', '/index.html', '/styles.css', '/app.js', '/favicon.svg',
                           '/clar-extension.zip', '/results.js', '/results.css', '/client.js',
                           '/grounding.js', '/presentation.js'))


def allowed_host(headers):
    hosts = headers.get_all('Host', [])
    try:
        parsed = urlparse('//' + (hosts[0] if len(hosts) == 1 else ''))
        return bool(len(hosts) == 1 and parsed.hostname in ALLOWED_HOSTS
                    and not parsed.username and not parsed.password
                    and not parsed.path and not parsed.query and not parsed.fragment
                    and not any(character.isspace() for character in hosts[0])
                    and (parsed.port is None or 0 < parsed.port <= 65535))
    except ValueError:
        return False


class RequestService:
    """Transport-neutral HTTP decisions shared by ASGI and preview adapters."""
    runtime_models = False

    def extension_origin(self):
        headers = getattr(self, 'headers', None)
        return bool(headers and headers.get_all('Origin') == [EXTENSION_ORIGIN])

    def public_request(self):
        # A dedicated Funnel process sets PUBLIC_MODE=1. Enforce access even if
        # a client spoofs a private Host header through a reverse proxy.
        if PUBLIC_MODE:
            return True
        return bool(PUBLIC_HOST and urlparse('//' + self.headers['Host']).hostname == PUBLIC_HOST)

    def _public_store(self):
        try:
            return manage_invites.read_store(INVITES_PATH)
        except manage_invites.InviteStoreError:
            return None

    def _session_invite(self):
        cookies = self.headers.get_all('Cookie', [])
        if len(cookies) != 1:
            return None
        matches = []
        for item in cookies[0].split(';'):
            key, divider, value = item.strip().partition('=')
            if divider and key == 'clar_session':
                matches.append(value)
        if len(matches) != 1:
            return None
        store = self._public_store()
        return verify_session(matches[0], store) if store else None

    def same_web_origin(self, origin):
        try:
            parsed = urlparse(origin)
            return (
                parsed.scheme in ('http', 'https')
                and (
                    parsed.netloc == self.headers.get('Host')
                    or (self.public_request() and PUBLIC_HOST
                        and parsed.scheme == 'https' and parsed.netloc == PUBLIC_HOST)
                )
                and not parsed.path and not parsed.params
                and not parsed.query and not parsed.fragment
            )
        except ValueError:
            return False

    def authorize_request(self, method, path):
        self.invite_name = None
        origin = self.headers.get('Origin')
        marker = self.headers.get('X-CLAR-Extension')
        authorization = self.headers.get('Authorization')
        for header in ('Origin', 'X-CLAR-Extension', 'Authorization'):
            if len(self.headers.get_all(header, [])) > 1:
                self.send_json(403, {'error': 'That request origin is not allowed.'})
                return False
        is_extension = (
            (origin or '').startswith('chrome-extension:')
            or marker is not None or authorization is not None
        )
        if is_extension:
            if (
                (origin is not None and origin != EXTENSION_ORIGIN)
                or (marker is not None and marker != EXTENSION_ID)
                or (origin is None and marker != EXTENSION_ID)
                or api_method(path) != method
            ):
                self.send_json(403, {'error': 'That extension request is not allowed.'})
                return False
            if self.public_request():
                store = self._public_store()
                value = authorization[7:] if authorization and authorization.startswith('Bearer ') else ''
                invite = manage_invites.invite_for_extension_token(store, value) if store else None
                if not invite:
                    self.send_json(401, {'error': 'Connect the extension with your own CLAR pairing code.', 'code': 'extension_pairing_required'})
                    return False
                self.invite_name = invite[0]
            else:
                token = os.environ.get('EXTENSION_TOKEN', '')
                expected = 'Bearer ' + token
                if not token or not hmac.compare_digest(
                    (authorization or '').encode('utf-8'), expected.encode('utf-8')
                ):
                    self.send_json(401, {'error': 'Connect the extension using the pairing token.', 'code': 'extension_pairing_required'})
                    return False
        elif origin is not None and not self.same_web_origin(origin):
            self.send_json(403, {'error': 'Please use the app from this preview address.'})
            return False
        protected = path in ('/api/analyze', '/api/extension-setup', '/api/feedback', '/api/jobs') or bool(JOB_PATH.fullmatch(path))
        if self.public_request() and protected and not is_extension:
            invite = self._session_invite()
            if not invite:
                self.send_json(401, {'error': 'Enter your CLAR access code to continue.', 'code': 'access_required'})
                return False
            self.invite_name = invite[0]
        return True

    def end_headers(self):
        if self.extension_origin():
            self.send_header('Access-Control-Allow-Origin', EXTENSION_ORIGIN)
            self.send_header('Vary', 'Origin')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; connect-src 'self'; frame-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        self.finish_headers()

    def send_json(self, status, data, extra_headers=()):
        raw = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(raw)))
        for name, value in extra_headers:
            self.send_header(name, value)
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(raw)

    def do_OPTIONS(self):
        path = urlparse(self.path).path
        requested_method = self.headers.get('Access-Control-Request-Method')
        requested_headers = {
            header.strip().lower()
            for header in self.headers.get('Access-Control-Request-Headers', '').split(',')
            if header.strip()
        }
        if (
            not self.extension_origin() or not api_method(path)
            or requested_method != api_method(path)
            or not requested_headers.issubset(EXTENSION_HEADERS)
            or len(self.headers.get_all('Access-Control-Request-Method', [])) != 1
            or len(self.headers.get_all('Access-Control-Request-Headers', [])) > 1
        ):
            return self.send_json(403, {'error': 'That extension request is not allowed.'})
        self.send_response(204)
        self.send_header('Access-Control-Allow-Methods', api_method(path))
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, Authorization, X-CLAR-Extension')
        self.send_header('Content-Length', '0')
        self.end_headers()

    def do_GET(self):
        path = urlparse(self.path).path
        if not self.authorize_request('GET', path):
            return
        match = JOB_PATH.fullmatch(path)
        if match and not match.group(2):
            try:
                return self.send_json(200, JOBS.get(match.group(1), self._job_owner()))
            except JobError as exc:
                return self.send_json(exc.status, {'error': str(exc), 'code': exc.code})
        if path == '/api/extension-setup':
            # Browser same-origin fetches omit Origin, but supply Fetch Metadata.
            origin = self.headers.get('Origin')
            if (
                (origin is None and self.headers.get('Sec-Fetch-Site') != 'same-origin')
                or self.headers.get('Sec-Fetch-Site') in ('cross-site', 'same-site')
            ):
                return self.send_json(403, {'error': 'Open extension setup from the CLAR app.'})
            if self.public_request():
                store = self._public_store()
                entry = manage_invites.active_invite(store, self.invite_name) if store else None
                token = entry.get('extension_token', '') if entry else ''
            else:
                token = os.environ.get('EXTENSION_TOKEN', '')
            if not token:
                return self.send_json(503, {'error': 'Extension pairing is temporarily unavailable.'})
            return self.send_json(200, {
                'extension_id': EXTENSION_ID, 'token': token,
                'download_url': '/clar-extension.zip'
            })
        if path == '/api/health':
            public = self.public_request()
            access_granted = bool(self.invite_name or self._session_invite()) if public else True
            return self.send_json(200, {
                'configured': bool(os.environ.get('GEMINI_API_KEY') or os.environ.get('GOOGLE_API_KEY')),
                'model': MODEL, 'default_provider': DEFAULT_PROVIDER,
                'vertex_configured': bool(os.environ.get('VERTEX_API_KEY')), 'vertex_model': VERTEX_MODEL,
                'local_ready': local_status(), 'local_model': LOCAL_MODEL, 'local_location': LOCAL_LOCATION,
                'public_access_required': public, 'access_granted': access_granted,
                'analysis_version': ANALYSIS_VERSION,
            })
        if path == '/api/examples':
            try:
                entries = json.loads((ROOT / 'fixtures/analysis_cases.json').read_text())
                names = {'stopfals-democracy-181559': 'Democracy rankings', 'stopfals-gagauzia-181558': 'Gagauzia language requirement',
                         'stopfals-gas-181552': 'Gas price comparison', 'stopfals-otifonex-181556': 'Hearing-product claim', 'government-control': 'Official announcement control'}
                return self.send_json(200, [{**{k: e.get(k) for k in ('id', 'text', 'language', 'post_date', 'origin')}, 'title': names[e['id']]}
                                           for e in entries if e.get('id') in names])
            except (OSError, ValueError, TypeError):
                return self.send_json(200, [])
        if path not in STATIC_ROUTES:
            return self.send_json(404, {'error': 'Not found.'})
        return self.serve_static()

    def do_HEAD(self):
        path = urlparse(self.path).path
        if not self.authorize_request('HEAD', path):
            return
        if path not in STATIC_ROUTES:
            return self.send_json(404, {'error': 'Not found.'})
        return self.serve_static(head=True)

    def do_POST(self):
        path = urlparse(self.path).path
        if not self.authorize_request('POST', path):
            return
        if path == '/api/access':
            return self._grant_public_access()
        if path == '/api/feedback':
            return self._receive_feedback()
        if path == '/api/jobs':
            return self._start_job()
        match = JOB_PATH.fullmatch(path)
        if match and match.group(2):
            try:
                return self.send_json(200, JOBS.cancel(match.group(1), self._job_owner()))
            except JobError as exc:
                return self.send_json(exc.status, {'error': str(exc), 'code': exc.code})
        if path != '/api/analyze':
            return self.send_json(404, {'error': 'Not found.'})
        if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
            return self.send_json(415, {'error': 'Expected a JSON request.'})
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 8_000_000:
                return self.send_json(413, {'error': 'Please use a screenshot smaller than 5 MB.'})
            body = json.loads(self.rfile.read(length))
            if not isinstance(body, dict):
                raise ValueError('Expected an object.')
            provider = body.get('provider', DEFAULT_PROVIDER)
            if provider not in ('local', 'gemini', 'vertex'):
                return self.send_json(400, {'error': 'Choose Local model, Vertex AI, or Gemini.'})
            supplied_key = body.pop('api_key', '')
            api_key = os.environ.get('GEMINI_API_KEY') or os.environ.get('GOOGLE_API_KEY') or supplied_key
            if provider == 'gemini' and (not isinstance(api_key, str) or not api_key.strip()):
                return self.send_json(503, {'error': 'Connect a Gemini API key to analyze your own post.', 'code': 'missing_key'})
            if provider == 'vertex':
                api_key = os.environ.get('VERTEX_API_KEY', '')
                if not api_key:
                    return self.send_json(503, {'error': 'Vertex AI has not been configured on this server.', 'code': 'missing_key'})
            gate = LOCAL_GATE if provider == 'local' else GATE
            if not gate.acquire(blocking=False):
                return self.send_json(429, {'error': 'The model is checking another post. Please try again shortly.'})
            try:
                if self.public_request():
                    try:
                        limit = reserve_public_usage(self.invite_name)
                    except RuntimeError:
                        return self.send_json(503, {'error': 'Daily checking limits are temporarily unavailable. Please try again later.'})
                    if limit:
                        who = 'your invitation' if limit == 'invite' else 'all reviewers'
                        return self.send_json(429, {
                            'error': 'The daily check limit for {} has been reached. Please try again tomorrow (UTC).'.format(who),
                            'code': 'daily_limit_reached',
                        })
                from analysis import analyze, AnalysisError
                try:
                    started = time.monotonic()
                    result = run_pipeline(body, provider, 'analyze', api_key, runtime_models=self.runtime_models)
                    result['analysis_seconds'] = round(time.monotonic() - started, 1)
                except AnalysisError as exc:
                    return self.send_json(exc.status, {'error': str(exc), 'code': exc.code})
                return self.send_json(200, result)
            finally:
                gate.release()
        except (ValueError, TypeError):
            return self.send_json(400, {'error': 'That request could not be read. Please try again.'})
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception:
            return self.send_json(500, {'error': 'The check could not finish. Please try again.'})

    def _job_owner(self):
        if not self.public_request():
            return 'private-owner'
        store = self._public_store()
        entry = manage_invites.active_invite(store, self.invite_name) if store else None
        if not entry:
            raise JobError('Your invitation has expired.', 401, 'access_required')
        return self.invite_name + ':' + entry['id']

    def _start_job(self):
        if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
            return self.send_json(415, {'error': 'Expected a JSON request.'})
        from analysis import validated_input, AnalysisError
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 8_000_000:
                raise JobError('Use one post or a screenshot smaller than 5 MB.', 413, 'input')
            body = json.loads(self.rfile.read(length))
            if not isinstance(body, dict):
                raise JobError('Expected one post.', 400, 'input')
            validated_input(body)
            task = body.pop('task', 'analyze')
            force = body.pop('force', False)
            if task not in ('analyze', 'precheck') or not isinstance(force, bool):
                raise JobError('Choose a supported check.', 400, 'input')
            if task == 'precheck' and (body.get('image') or not body.get('text')):
                raise JobError('Automatic scanning checks visible text only.', 400, 'input')
            if body.get('origin') is not None and (
                not isinstance(body['origin'], dict) or len(json.dumps(body['origin'])) > 5000
            ):
                raise JobError('The post origin could not be read.', 400, 'input')
            provider = body.get('provider', DEFAULT_PROVIDER)
            if provider not in ('local', 'gemini', 'vertex'):
                raise JobError('Choose Local model, Vertex AI, or Gemini.', 400, 'input')
            supplied_key = body.pop('api_key', '')
            api_key = (os.environ.get('VERTEX_API_KEY', '') if provider == 'vertex' else
                       os.environ.get('GEMINI_API_KEY') or os.environ.get('GOOGLE_API_KEY') or supplied_key)
            if provider != 'local' and (not isinstance(api_key, str) or not api_key.strip()):
                raise JobError('The selected model is not configured.', 503, 'missing_key')
            body['provider'] = provider
            public, reviewer = self.public_request(), self.invite_name
            owner = self._job_owner()
            def reserve():
                if not public:
                    return
                try:
                    limit = reserve_public_usage(reviewer)
                except RuntimeError:
                    raise JobError('Daily checking limits are unavailable. Please retry later.', 503, 'usage_unavailable')
                if limit:
                    raise JobError('The daily check limit has been reached. Auto-scan is paused; retry tomorrow (UTC).', 429, 'daily_limit_reached')
            def run(progress):
                gate = LOCAL_GATE if provider == 'local' else GATE
                with gate:
                    started = time.monotonic()
                    progress('reading', 'running')
                    result = run_pipeline(body, provider, task, api_key, progress=progress, runtime_models=self.runtime_models)
                    result['analysis_seconds'] = round(time.monotonic()-started, 1)
                    if body.get('example_id') in ('stopfals-democracy-181559', 'stopfals-gagauzia-181558', 'stopfals-gas-181552', 'stopfals-otifonex-181556', 'government-control'):
                        result['example_input'] = True
                    return result
            fingerprint = {'task': task, 'input': body,
                           'model': LOCAL_MODEL if provider == 'local' else VERTEX_MODEL if provider == 'vertex' else MODEL,
                           'local_provider': os.environ.get('LOCAL_PROVIDER', 'ollama') if provider == 'local' else '',
                           'thinking': os.environ.get('LOCAL_THINKING' if provider == 'local' else 'MODEL_THINKING', 'default'),
                           'credential_scope': hashlib.sha256((api_key or '').encode()).hexdigest() if provider != 'local' else ''}
            view, reused = JOBS.create(owner, fingerprint, run, reserve=reserve, force=force)
            view['reused'] = reused
            return self.send_json(200 if reused else 202, view)
        except JobError as exc:
            return self.send_json(exc.status, {'error': str(exc), 'code': exc.code})
        except AnalysisError as exc:
            return self.send_json(exc.status, {'error': str(exc), 'code': exc.code})
        except (ValueError, TypeError):
            return self.send_json(400, {'error': 'That request could not be read. Please try again.', 'code': 'input'})
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception:
            return self.send_json(500, {'error': 'The check could not start. Please try again.', 'code': 'job_start_failed'})

    def _grant_public_access(self):
        if not self.public_request():
            return self.send_json(404, {'error': 'Not found.'})
        if self.headers.get('Sec-Fetch-Site') in ('cross-site', 'same-site'):
            return self.send_json(403, {'error': 'Open this page from CLAR.'})
        if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
            return self.send_json(415, {'error': 'Expected a JSON request.'})
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 1024:
                return self.send_json(413, {'error': 'Please enter a valid access code.'})
            body = json.loads(self.rfile.read(length))
        except (ValueError, TypeError):
            return self.send_json(400, {'error': 'Please enter a valid access code.'})
        store = self._public_store()
        if not store:
            return self.send_json(503, {'error': 'Reviewer access is temporarily unavailable.'})
        invite = manage_invites.invite_for_code(store, body.get('code')) if isinstance(body, dict) else None
        if not invite:
            return self.send_json(401, {'error': 'That access code was not recognized.', 'code': 'invalid_access_code'})
        name, entry = invite
        session = issue_session(name, entry, store)
        cookie = 'clar_session={}; Max-Age={}; Path=/; Secure; HttpOnly; SameSite=Lax'.format(session, SESSION_SECONDS)
        return self.send_json(200, {'ok': True, 'name': name}, [('Set-Cookie', cookie)])

    def _receive_feedback(self):
        if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
            return self.send_json(415, {'error': 'Expected a JSON request.'})
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 6_000:
                return self.send_json(413, {'error': 'Please keep feedback under 2,000 characters.'})
            body = json.loads(self.rfile.read(length))
            if not isinstance(body, dict) or set(body) - {'category', 'message', 'post_url', 'source'}:
                raise ValueError('Unexpected feedback fields.')
            category = body.get('category')
            message = body.get('message')
            source = body.get('source')
            post_url = body.get('post_url') or ''
            if (category not in {'accuracy', 'media_literacy', 'design', 'bug', 'suggestion'}
                or not isinstance(message, str) or not 1 <= len(message.strip()) <= 2_000
                or source not in {'web', 'extension'} or not isinstance(post_url, str)
                or len(post_url) > 2_048):
                raise ValueError('Invalid feedback fields.')
            if post_url:
                parsed = urlparse(post_url)
                if (parsed.scheme != 'https'
                    or parsed.hostname not in {'facebook.com', 'www.facebook.com', 'm.facebook.com'}
                    or parsed.username or parsed.password or parsed.port not in (None, 443)):
                    raise ValueError('Invalid post URL.')
            body = {'category': category, 'message': message.strip(),
                    'source': source, 'post_url': post_url}
        except (ValueError, TypeError):
            return self.send_json(400, {'error': 'Please enter a category and a message under 2,000 characters.'})
        reviewer = self.invite_name if self.public_request() else 'owner'
        try:
            status = save_feedback(reviewer, body)
        except RuntimeError:
            return self.send_json(503, {'error': 'Feedback could not be saved. Please try again later.'})
        if status == 'daily':
            return self.send_json(429, {'error': 'Your daily feedback limit has been reached. Please try again tomorrow (UTC).', 'code': 'feedback_daily_limit'})
        if status == 'full':
            return self.send_json(507, {'error': 'The feedback inbox is full. Please tell the team directly.'})
        return self.send_json(201, {'ok': True})


class Handler(RequestService, SimpleHTTPRequestHandler):
    """Compatibility development adapter; not the public deployment entrypoint."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT / 'public'), **kwargs)

    def log_message(self, format, *args):
        # Never log URLs, request bodies, posts, images, or credentials.
        pass

    def parse_request(self):
        if not super().parse_request():
            return False
        if not allowed_host(self.headers):
            self.send_json(403, {'error': 'This server address is not allowed.'})
            return False
        return True

    def finish_headers(self):
        SimpleHTTPRequestHandler.end_headers(self)

    def serve_static(self, head=False):
        if head:
            return SimpleHTTPRequestHandler.do_HEAD(self)
        return SimpleHTTPRequestHandler.do_GET(self)


if __name__ == '__main__':
    ensure_extension_token()
    host = os.environ.get('HOST', '127.0.0.1')
    port = int(os.environ.get('PORT', '8765'))
    print('CLAR preview listening on http://{}:{}'.format(host, port), flush=True)
    ThreadingHTTPServer((host, port), Handler).serve_forever()
