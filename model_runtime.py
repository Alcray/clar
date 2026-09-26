"""Explicit, per-request model configuration shared by the app and benchmarks.

No process-global model switching, input logging, response caching, or implicit
fallback to another provider. Local endpoints are operator configuration.
"""
from dataclasses import dataclass, field
import json
import os
import re
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from analysis import AnalysisError, validate_schema

_LOCK = threading.Lock()
_MAX_BYTES = 8_000_000


@dataclass(frozen=True)
class ModelConfig:
    provider: str
    model: str
    endpoint: str = ''
    api_key_env: str = ''
    thinking: str = 'default'
    timeout_seconds: float = 60
    max_output_tokens: int = 4096
    context_tokens: int = 8192
    temperature: float = None
    api_key: str = field(default='', repr=False, compare=False)

    def __post_init__(self):
        if self.provider not in ('vertex', 'gemini', 'ollama', 'openai'):
            raise ValueError('Unsupported model provider.')
        if not isinstance(self.model, str) or not self.model.strip() or len(self.model) > 200:
            raise ValueError('Set a model identifier.')
        if not 1 <= float(self.timeout_seconds) <= 600:
            raise ValueError('Model timeout must be between 1 and 600 seconds.')
        if not 128 <= int(self.max_output_tokens) <= 65536 or not 1024 <= int(self.context_tokens) <= 262144:
            raise ValueError('Invalid model token budget.')
        if self.api_key_env and not re.fullmatch(r'[A-Z][A-Z0-9_]{0,79}', self.api_key_env):
            raise ValueError('Use an environment variable name for the API key.')
        if self.thinking not in ('default', 'minimal', 'low', 'medium', 'high', 'none', 'off', 'on', 'false', 'true'):
            raise ValueError('Unsupported thinking configuration.')
        if self.temperature is not None and (type(self.temperature) not in (int, float) or not 0 <= self.temperature <= 2):
            raise ValueError('Temperature must be between 0 and 2, or null for the provider default.')
        if self.endpoint:
            validate_endpoint(self.endpoint)

    def public_dict(self):
        return {key: getattr(self, key) for key in ('provider', 'model', 'endpoint',
                'api_key_env', 'thinking', 'timeout_seconds', 'max_output_tokens', 'context_tokens', 'temperature')}


def validate_endpoint(value):
    try:
        parsed = urllib.parse.urlsplit(value)
        if (parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username
                or parsed.password or parsed.query or parsed.fragment):
            raise ValueError()
        _ = parsed.port
    except (ValueError, TypeError):
        raise ValueError('Model endpoint must be an HTTP(S) URL without credentials, query or fragment.')
    return value.rstrip('/')


def config_from_env(provider=None):
    provider = provider or os.environ.get('DEFAULT_PROVIDER', 'local')
    if provider == 'local':
        provider = os.environ.get('LOCAL_PROVIDER', 'ollama')
    cloud = provider in ('vertex', 'gemini')
    model = os.environ.get({'vertex': 'VERTEX_MODEL', 'gemini': 'GEMINI_MODEL'}.get(provider, 'LOCAL_MODEL'),
                           'gemini-3.5-flash' if cloud else 'qwen2.5vl:3b')
    endpoint = (os.environ.get('OLLAMA_BASE_URL', 'http://127.0.0.1:11434') if provider == 'ollama' else
                os.environ.get('LOCAL_API_BASE_URL', 'http://127.0.0.1:8000/v1') if provider == 'openai' else '')
    key_env = {'vertex': 'VERTEX_API_KEY', 'gemini': 'GEMINI_API_KEY'}.get(provider,
               os.environ.get('LOCAL_API_KEY_ENV', 'LOCAL_API_KEY'))
    if provider == 'gemini' and not os.environ.get(key_env) and os.environ.get('GOOGLE_API_KEY'):
        key_env = 'GOOGLE_API_KEY'
    temperature = os.environ.get('MODEL_TEMPERATURE', '') if cloud else os.environ.get('LOCAL_TEMPERATURE', '0')
    return ModelConfig(provider=provider, model=model, endpoint=endpoint, api_key_env=key_env,
        thinking=os.environ.get('MODEL_THINKING', 'low') if cloud else os.environ.get('LOCAL_THINKING', 'default'),
        timeout_seconds=float(os.environ.get('MODEL_TIMEOUT_SECONDS', '60')),
        max_output_tokens=int(os.environ.get('MODEL_MAX_OUTPUT_TOKENS', '4096')),
        context_tokens=int(os.environ.get('LOCAL_CONTEXT_TOKENS', '8192')),
        temperature=float(temperature) if temperature else None)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def _post(url, body, headers, timeout):
    request = urllib.request.Request(url, data=json.dumps(body, ensure_ascii=False).encode(),
                                     headers={'Content-Type': 'application/json', **headers}, method='POST')
    try:
        with urllib.request.build_opener(_NoRedirect()).open(request, timeout=timeout) as response:
            raw = response.read(_MAX_BYTES + 1)
            if len(raw) > _MAX_BYTES:
                raise AnalysisError('The model response exceeded its size limit.', 502, 'response_size')
            data = json.loads(raw)
            if not isinstance(data, dict):
                raise ValueError()
            return data
    except urllib.error.HTTPError as error:
        code = 'api_auth' if error.code in (401, 403) else 'api_quota' if error.code == 429 else 'model_unavailable' if error.code == 404 else 'api_request'
        raise AnalysisError('The model endpoint rejected the request (HTTP {}).'.format(error.code),
                            error.code if error.code in (401, 403, 429) else 502, code) from None
    except (urllib.error.URLError, TimeoutError, socket.timeout):
        raise AnalysisError('The model request timed out or its endpoint is unavailable.', 504, 'api_timeout') from None
    except (ValueError, TypeError, UnicodeError):
        raise AnalysisError('The model endpoint returned invalid JSON.', 502, 'invalid_output') from None


def _parts(parts):
    text, images = [], []
    for part in parts:
        if 'text' in part:
            text.append(str(part['text']))
        elif 'inlineData' in part:
            image = part['inlineData']
            if image.get('mimeType') not in ('image/png', 'image/jpeg', 'image/webp'):
                raise AnalysisError('Unsupported image format.', 400, 'input')
            images.append(image)
    return '\n'.join(text), images


def _record(telemetry, record):
    if telemetry is None:
        return
    with _LOCK:
        telemetry.setdefault('calls', []).append(record)
        telemetry['requests'] = len(telemetry['calls'])
        telemetry['request_duration_seconds'] = sum(item['duration_seconds'] for item in telemetry['calls'])
        for name in ('input_tokens', 'output_tokens', 'thinking_tokens', 'cached_input_tokens'):
            values = [item.get(name) for item in telemetry['calls']]
            telemetry[name] = sum(values) if values and all(isinstance(v, int) for v in values) else None


def call_model(config, system, parts, schema=None, search=False, telemetry=None):
    """One model request. Failures and malformed JSON are measured, not retried."""
    started = time.perf_counter()
    record = {'provider': config.provider, 'model': config.model, 'reported_model': None,
              'status': 'error', 'input_tokens': None, 'output_tokens': None,
              'thinking_tokens': None, 'cached_input_tokens': None}
    try:
        key = config.api_key or (os.environ.get(config.api_key_env, '') if config.api_key_env else '')
        if config.provider in ('vertex', 'gemini'):
            if not key:
                raise AnalysisError('Configure the provider API key environment variable.', 503, 'missing_key')
            if config.endpoint:
                raise AnalysisError('Google providers use their official API endpoint.', 400, 'api_configuration')
            prefix = ('https://aiplatform.googleapis.com/v1/publishers/google/models/' if config.provider == 'vertex'
                      else 'https://generativelanguage.googleapis.com/v1beta/models/')
            generation = {'maxOutputTokens': config.max_output_tokens}
            if config.temperature is not None:
                generation['temperature'] = config.temperature
            if config.thinking != 'default':
                if config.thinking.lower() not in ('minimal', 'low', 'medium', 'high'):
                    raise AnalysisError('Use minimal, low, medium, high or default thinking for Google.', 400, 'api_configuration')
                generation['thinkingConfig'] = {'thinkingLevel': config.thinking.upper()}
            if schema:
                generation.update(responseMimeType='application/json', responseJsonSchema=schema)
            body = {'systemInstruction': {'parts': [{'text': system}]},
                    'contents': [{'role': 'user', 'parts': parts}], 'generationConfig': generation}
            if search:
                body['tools'] = [{'google_search': {}}]
            raw = _post(prefix + urllib.parse.quote(config.model, safe='-._') + ':generateContent',
                        body, {'x-goog-api-key': key}, config.timeout_seconds)
            usage = raw.get('usageMetadata', {})
            for dest, source in [('input_tokens', 'promptTokenCount'), ('output_tokens', 'candidatesTokenCount'),
                                 ('thinking_tokens', 'thoughtsTokenCount'), ('cached_input_tokens', 'cachedContentTokenCount')]:
                record[dest] = usage.get(source)
            record['reported_model'] = raw.get('modelVersion')
            candidates = raw.get('candidates') or []
            if not candidates:
                raise AnalysisError('The model returned no analysis.', 422, 'no_output')
            candidate = candidates[0]
            if candidate.get('finishReason') not in (None, 'STOP'):
                raise AnalysisError('The model did not complete its response.', 422, 'incomplete_output')
            text = '\n'.join(part.get('text', '') for part in candidate.get('content', {}).get('parts', []) if not part.get('thought'))
            if not schema:
                if not text.strip():
                    raise AnalysisError('The model returned an empty response.', 422, 'no_output')
                record['status'] = 'ok'
                return candidate
        else:
            if search:
                raise AnalysisError('This local endpoint does not provide Google Search grounding.', 400, 'unsupported_capability')
            text_input, images = _parts(parts)
            headers = {'Authorization': 'Bearer ' + key} if key else {}
            if config.provider == 'ollama':
                endpoint = validate_endpoint(config.endpoint or 'http://127.0.0.1:11434')
                user = {'role': 'user', 'content': text_input}
                if images:
                    user['images'] = [image['data'] for image in images]
                body = {'model': config.model, 'stream': False, 'messages': [{'role': 'system', 'content': system}, user],
                        'options': {'num_ctx': config.context_tokens, 'num_predict': config.max_output_tokens}}
                if config.temperature is not None:
                    body['options']['temperature'] = config.temperature
                if schema:
                    body['format'] = schema
                if config.thinking != 'default':
                    body['think'] = False if config.thinking in ('none', 'off', 'false') else True if config.thinking in ('on', 'true') else config.thinking
                raw = _post(endpoint + '/api/chat', body, headers, config.timeout_seconds)
                if raw.get('error') or raw.get('done') is not True:
                    raise AnalysisError('The local model did not return a completed response.', 502, 'local_request')
                if raw.get('done_reason') == 'length':
                    raise AnalysisError('The model reached its output token limit.', 422, 'incomplete_output')
                text = raw.get('message', {}).get('content', '')
                record.update(reported_model=raw.get('model'), input_tokens=raw.get('prompt_eval_count'), output_tokens=raw.get('eval_count'))
                if isinstance(raw.get('load_duration'), (int, float)):
                    record['load_seconds'] = raw['load_duration'] / 1e9
                if isinstance(raw.get('eval_duration'), (int, float)):
                    record['generation_seconds'] = raw['eval_duration'] / 1e9
            else:
                endpoint = validate_endpoint(config.endpoint or 'http://127.0.0.1:8000/v1')
                content = [{'type': 'text', 'text': text_input}]
                content.extend({'type': 'image_url', 'image_url': {'url': 'data:{};base64,{}'.format(image['mimeType'], image['data'])}} for image in images)
                body = {'model': config.model, 'stream': False, 'messages': [{'role': 'system', 'content': system},
                        {'role': 'user', 'content': content if images else text_input}], 'max_tokens': config.max_output_tokens}
                if config.temperature is not None:
                    body['temperature'] = config.temperature
                if schema:
                    body['response_format'] = {'type': 'json_schema', 'json_schema': {'name': 'clar_response', 'strict': True, 'schema': schema}}
                if config.thinking != 'default':
                    body['reasoning_effort'] = config.thinking
                raw = _post(endpoint + '/chat/completions', body, headers, config.timeout_seconds)
                choices = raw.get('choices') or []
                if not choices or choices[0].get('finish_reason') not in ('stop', None):
                    raise AnalysisError('The model did not complete its response.', 422, 'incomplete_output')
                text = choices[0].get('message', {}).get('content', '')
                usage = raw.get('usage', {})
                record.update(reported_model=raw.get('model'), input_tokens=usage.get('prompt_tokens'), output_tokens=usage.get('completion_tokens'))
        if not isinstance(text, str) or not text.strip():
            raise AnalysisError('The model returned an empty response.', 422, 'no_output')
        if schema:
            # No stripping of malformed JSON in a model comparison: schema
            # compliance is one of the measured outcomes.
            try:
                parsed = json.loads(text)
            except ValueError:
                raise AnalysisError('The model returned invalid structured output.', 502, 'invalid_output') from None
            validate_schema(parsed, schema)
            record['status'] = 'ok'
            return parsed
        record['status'] = 'ok'
        return {'content': {'parts': [{'text': text}]}}
    except AnalysisError as error:
        record['error_code'] = error.code
        raise
    finally:
        record['duration_seconds'] = round(time.perf_counter() - started, 6)
        _record(telemetry, record)
