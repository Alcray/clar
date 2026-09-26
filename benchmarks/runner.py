"""Run the fixed task or deployed analysis function without application result caches."""
import argparse
import base64
import concurrent.futures
import datetime
import hashlib
import importlib
import json
import multiprocessing
import os
import platform
from pathlib import Path
import random
import re
import time
import urllib.parse
import uuid

from . import BENCHMARK_VERSION
from .contract import FIXED_SCHEMA, FIXED_SYSTEM, PROMPT_VERSION, OutputValidationError, validate_output, schema_for
from .dataset import DEFAULT_DATASET, digest, fixed_payload, load_dataset
from .metrics import paired_comparisons, safe_url, score_case, summarize_groups

ROOT = Path(__file__).resolve().parents[1]
CONFIG_FIELDS = {'provider', 'model', 'endpoint', 'api_key_env', 'thinking', 'timeout_seconds', 'max_output_tokens', 'context_tokens', 'temperature'}
MODEL_DEFAULTS = {'endpoint': '', 'api_key_env': '', 'thinking': 'default', 'timeout_seconds': 60,
                  'max_output_tokens': 4096, 'context_tokens': 8192, 'temperature': None}
CALL_FIELDS = {'provider', 'model', 'reported_model', 'duration_seconds', 'status', 'input_tokens', 'output_tokens',
               'thinking_tokens', 'cached_input_tokens', 'load_seconds', 'error_code'}
TOKEN_FIELDS = {'input_tokens', 'output_tokens', 'thinking_tokens', 'cached_input_tokens', 'requests', 'request_duration_seconds'}


def utcnow():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def load_matrix(path):
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    models = data.get('models')
    if not isinstance(models, list) or not models:
        raise ValueError('Matrix needs a nonempty models array.')
    seen = set()
    for item in models:
        if not isinstance(item, dict) or set(item) - (CONFIG_FIELDS | {'name'}):
            raise ValueError('Unknown matrix field; credentials must be supplied through api_key_env, never inline.')
        name = item.get('name')
        if not isinstance(name, str) or not re.fullmatch(r'[a-zA-Z0-9_.-]{1,100}', name) or name in seen:
            raise ValueError('Model names must be unique short identifiers.')
        seen.add(name)
        if item.get('provider') not in ('vertex', 'gemini', 'ollama', 'openai'):
            raise ValueError('Unsupported provider in ' + name)
        if not isinstance(item.get('model'), str) or not item['model'].strip() or len(item['model']) > 200:
            raise ValueError('Model ID is required for ' + name)
        if item.get('api_key_env') and not re.fullmatch(r'[A-Z][A-Z0-9_]{0,79}', item['api_key_env']):
            raise ValueError('api_key_env must be an environment variable name.')
        if item.get('endpoint'):
            parts = urllib.parse.urlsplit(item['endpoint'])
            if not safe_url(item['endpoint']) or parts.query or parts.fragment:
                raise ValueError('Endpoints must be HTTP(S) without credentials, query strings, or fragments.')
        temperature = item.get('temperature')
        if temperature is not None and (type(temperature) not in (int, float) or not 0 <= temperature <= 2):
            raise ValueError('temperature must be null or between 0 and 2.')
        if item.get('thinking', 'default') not in ('default', 'minimal', 'low', 'medium', 'high', 'none', 'off', 'on', 'false', 'true'):
            raise ValueError('Unsupported thinking configuration.')
        for field, lower, upper in [('timeout_seconds', 1, 600), ('max_output_tokens', 128, 65536), ('context_tokens', 1024, 262144)]:
            if field in item and (type(item[field]) not in (int, float) or not lower <= item[field] <= upper):
                raise ValueError(field + ' is outside the supported range.')
    return [dict(MODEL_DEFAULTS, **item) for item in models]


def _safe_telemetry(raw):
    result = {}
    for key in TOKEN_FIELDS:
        value = raw.get(key)
        if key in raw and (value is None or type(value) in (int, float)):
            result[key] = value
    calls = []
    for call in raw.get('calls', []):
        if not isinstance(call, dict):
            continue
        clean = {key: value for key, value in call.items() if key in CALL_FIELDS and isinstance(value, (str, int, float, bool))}
        calls.append(clean)
    result['calls'] = calls
    for key in ('retrieval_regime', 'cache_policy'):
        if isinstance(raw.get(key), str):
            result[key] = raw[key]
    return result


def _error(exc):
    # Exception text/provider responses can contain keys, URLs, or headers. Never save them.
    code = getattr(exc, 'code', None)
    safe_code = code if isinstance(code, str) and re.fullmatch(r'[a-zA-Z0-9_:-]{1,80}', code) else type(exc).__name__
    return {'type': type(exc).__name__, 'code': safe_code}


def normalize_live(result):
    if not isinstance(result, dict) or not isinstance(result.get('statements'), list) or not result['statements']:
        raise OutputValidationError('Live pipeline returned no statements.')
    statements = []
    for item in result['statements']:
        if not isinstance(item, dict) or not isinstance(item.get('text'), str):
            raise OutputValidationError('Invalid live statement.')
        statements.append({'text': item['text'], 'kind': item.get('kind', 'unclear'),
                           'verdict': item.get('verdict', 'insufficient'),
                           'evidence_ids': [x.get('id', '') for x in item.get('evidence', []) if isinstance(x, dict)]})
    media = result.get('media_literacy', {})
    purpose = media.get('purpose', {}).get('category', 'unclear')
    # Live purpose/technique scores are intentionally off for reused demo fixtures.
    cues = result.get('techniques') or media.get('signals') or []
    aliases = {'conspiracy_appeal': 'conspiracy_framing', 'emotional_language': 'emotional_framing', 'us_versus_them': 'us_vs_them'}
    techniques = [{'type': aliases.get(cue.get('type'), cue.get('type', 'unknown')), 'quote': cue.get('quote', '')}
                  for cue in cues if isinstance(cue, dict)]
    return {'statements': statements, 'purpose': purpose, 'techniques': techniques, 'fraud_signal': None}


def _live_sources(result):
    sources = []
    seen = set()
    for item in result.get('statements', []):
        for source in item.get('evidence', []):
            url = source.get('url')
            if safe_url(url) and url not in seen:
                seen.add(url)
                sources.append({'url': url, 'retrieval': source.get('retrieval', ''), 'stance': source.get('stance', '')})
        matched = item.get('fact_check') or {}
        url = matched.get('url')
        if safe_url(url) and url not in seen:
            seen.add(url)
            sources.append({'url': url, 'retrieval': matched.get('retrieval', ''), 'stance': 'matched_factcheck'})
    return sources


def execute_case(model, case, save_responses=False, emit=None):
    """One scored invocation. Dependency imports are late so dry-run needs no models."""
    telemetry, progress = {'cache_policy': 'application_and_source_caches_bypassed'}, []
    started = time.perf_counter()
    row = {'status': 'error', 'started_at': utcnow()}
    try:
        runtime = importlib.import_module('model_runtime')
        config = runtime.ModelConfig(**{k: v for k, v in model.items() if k in CONFIG_FIELDS})
        if hasattr(config, 'public_dict'):
            row['effective_config'] = config.public_dict()
        if case['track'] == 'fixed':
            parts = [{'text': json.dumps(fixed_payload(case), ensure_ascii=False)}]
            if case.get('modality') == 'image':
                image_path = Path(case.get('_dataset_directory', DEFAULT_DATASET.parent)) / case['image_path']
                image_bytes = image_path.read_bytes()
                if hashlib.sha256(image_bytes).hexdigest() != case['image_sha256']:
                    raise ValueError('Screenshot changed after dataset validation.')
                parts.append({'inlineData': {'mimeType': 'image/png', 'data': base64.b64encode(image_bytes).decode('ascii')}})
            result = runtime.call_model(config, FIXED_SYSTEM, parts, schema=schema_for(case), search=False, telemetry=telemetry)
            normalized = validate_output(result, image=case.get('modality') == 'image')
            telemetry['retrieval_regime'] = 'fixed_supplied_excerpts_no_search'
        else:
            pipeline = importlib.import_module('pipeline_runtime')
            body = {'text': case['text'], 'language': case['language'], 'post_date': case.get('post_date', ''),
                    'origin': case.get('origin', {})}
            def on_progress(stage, state='running'):
                progress.append({'stage': stage, 'state': state, 'elapsed_seconds': time.perf_counter() - started})
                if emit:
                    emit({'event': 'progress', 'progress': list(progress), 'telemetry': _safe_telemetry(telemetry)})
            result = pipeline.analyze_with_config(body, config, progress=on_progress, telemetry=telemetry, use_cache=False)
            telemetry['retrieval_regime'] = result.get('retrieval_regime', 'unknown')
            normalized = normalize_live(result)
            row['retrieved_sources'] = _live_sources(result)
            references = case['provenance'].get('reference_urls', [])
            row['freshness'] = {'labels_as_of': case['provenance']['labels_as_of'], 'retrieved_at': utcnow(),
                                'expected_reference_urls': references,
                                'reference_url_overlap': sorted(set(references) & {s['url'] for s in row['retrieved_sources']}),
                                'notice': 'Label disagreement can reflect retrieval/time drift. Review evidence before editing labels.'}
        row['scores'] = score_case(case, normalized)
        row['status'] = 'ok'
        if save_responses:
            # Keep benchmark-normalized outputs only, never raw provider envelopes or headers.
            row['response'] = normalized
    except Exception as exc:
        row['status'] = 'invalid_output' if isinstance(exc, (OutputValidationError, json.JSONDecodeError)) or getattr(exc, 'code', '') in ('invalid_json', 'schema_validation', 'invalid_output', 'schema_invalid') else 'error'
        row['error'] = _error(exc)
    row['duration_seconds'] = time.perf_counter() - started
    row['telemetry'] = _safe_telemetry(telemetry)
    row['progress'] = progress
    return row


def _child(connection, model, case, save_responses):
    try:
        connection.send({'event': 'started'})
        connection.send({'event': 'result', 'result': execute_case(model, case, save_responses, emit=connection.send)})
    finally:
        connection.close()


def isolated_case(model, case, save_responses=False, case_timeout=180):
    """A watchdog terminates only this local worker, never claims to cancel remote billing."""
    context = multiprocessing.get_context('spawn')
    parent, child = context.Pipe(duplex=False)
    process = context.Process(target=_child, args=(child, model, case, save_responses))
    submitted = time.perf_counter()
    process.start()
    child.close()
    adapter_start = None
    partial_telemetry, partial_progress, started_at = {}, [], utcnow()
    try:
        while True:
            now = time.perf_counter()
            if now - submitted >= case_timeout:
                process.terminate()
                process.join(timeout=2)
                if process.is_alive():
                    process.kill()
                    process.join(timeout=2)
                return {'status': 'timeout', 'error': {'type': 'CaseDeadline', 'code': 'case_timeout'},
                        'duration_seconds': now - (adapter_start or submitted),
                        'turnaround_seconds': now - submitted,
                        'worker_startup_seconds': adapter_start - submitted if adapter_start else None,
                        'telemetry': partial_telemetry, 'progress': partial_progress, 'started_at': started_at}
            if parent.poll(min(.1, max(.001, case_timeout - (now - submitted)))):
                try:
                    message = parent.recv()
                except EOFError:
                    raise RuntimeError('worker_exit')
                if message['event'] == 'started':
                    adapter_start = time.perf_counter()
                    started_at = utcnow()
                elif message['event'] == 'progress':
                    partial_telemetry, partial_progress = message['telemetry'], message['progress']
                elif message['event'] == 'result':
                    row = message['result']
                    row['turnaround_seconds'] = time.perf_counter() - submitted
                    row['worker_startup_seconds'] = (adapter_start or submitted) - submitted
                    return row
            elif not process.is_alive():
                raise RuntimeError('worker_exit')
    except Exception as exc:
        return {'status': 'error', 'error': _error(exc), 'duration_seconds': time.perf_counter() - (adapter_start or submitted),
                'turnaround_seconds': time.perf_counter() - submitted, 'telemetry': partial_telemetry, 'progress': partial_progress, 'started_at': started_at}
    finally:
        parent.close()
        process.join(timeout=2)
        if process.is_alive():
            process.terminate()
            process.join(timeout=2)


def _source_hash():
    names = ['analysis.py', 'local_analysis.py', 'media_literacy.py', 'factchecks.py', 'origins.py',
             'model_runtime.py', 'pipeline_runtime.py', 'config/sources.json', 'fixtures/known_debunks.json']
    values = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in names if (ROOT / name).exists()}
    return {'files': values, 'hash': digest(values)}


def make_plan(models, dataset, dataset_hash, cases, args):
    return {'benchmark_version': BENCHMARK_VERSION, 'run_id': utcnow().replace(':', '') + '-' + uuid.uuid4().hex[:8],
            'created_at': utcnow(), 'client_environment': {'python': platform.python_version(), 'system': platform.system(), 'machine': platform.machine(), 'logical_cpus': os.cpu_count(), 'hardware_note': getattr(args, 'hardware_note', '')}, 'dataset_version': dataset['version'], 'dataset_hash': dataset_hash,
            'selection_hash': digest(cases), 'case_ids': [c['id'] for c in cases],
            'label_status': dataset.get('label_status'), 'model_matrix': models, 'config_hash': digest(models),
            'fixed_prompt_version': PROMPT_VERSION, 'fixed_prompt_hash': digest({'system': FIXED_SYSTEM, 'text_schema': FIXED_SCHEMA, 'image_schema': schema_for({'modality': 'image'})}),
            'pipeline_source': _source_hash(), 'repetitions': args.repetitions, 'warmups': args.warmups,
            'concurrency': args.concurrency, 'case_timeout_seconds': args.case_timeout, 'seed': args.seed,
            'cache_policy': 'Application result cache bypassed; fixed track has no retrieval. Live adapter must bypass source cache. Provider prompt caching may still apply; usage is recorded when reported.',
            'latency_definition': 'duration_seconds measures adapter execution including its retries/search, excluding harness queue/worker startup. Turnaround includes process startup; queue_wait_seconds is separate. No TTFT is measured.',
            'timeout_definition': 'Deadline includes worker startup. The local worker is terminated; a request already accepted by a remote provider may continue and be billed.',
            'dataset_warning': 'Transparent editorial development fixtures, not independently human-validated gold and not an unbiased held-out score.',
            'image_scope': 'Optional six synthetic screenshot variants, image pixels plus supplied evidence only; plaintext withheld from model input. OCR CER/WER use NFC/casefold/whitespace normalization. These do not measure real feed screenshot generalization.', 'save_responses': args.save_responses}


def run(args):
    models = load_matrix(args.matrix)
    dataset, dataset_hash = load_dataset(args.dataset)
    if args.models:
        models = [m for m in models if m['name'] in args.models.split(',')]
    cases = [c for c in dataset['cases'] if (args.track == 'both' or c['track'] == args.track)
             and (args.modality == 'all' or c.get('modality', 'text') == args.modality)
             and (not args.language or c['language'] == args.language)
             and (not args.category or c['category'] == args.category)
             and (not args.case_id or c['id'] in args.case_id)]
    if args.limit:
        cases = cases[:args.limit]
    if not cases or not models:
        raise ValueError('Selection contains no cases or models.')
    plan = make_plan(models, dataset, dataset_hash, cases, args)
    cases = [dict(case, _dataset_directory=str(Path(args.dataset).resolve().parent)) for case in cases]
    out = Path(args.out or ROOT / '.runtime' / 'benchmarks' / plan['run_id'])
    out.mkdir(parents=True, exist_ok=True)
    if any((out / name).exists() for name in ('manifest.json', 'records.jsonl', 'summary.json')):
        raise ValueError('Output directory already contains a run; choose a new directory.')
    (out / 'manifest.json').write_text(json.dumps(plan, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'output': str(out), 'models': [m['name'] for m in models], 'cases': len(cases),
                      'measured_cases': len(cases) * len(models) * args.repetitions, 'dry_run': args.dry_run}))
    if args.dry_run:
        return 0
    records = []
    def invoke(task, submitted):
        model, case, repetition = task
        queue_wait = time.perf_counter() - submitted
        row = isolated_case(model, case, args.save_responses, args.case_timeout)
        row.update({'run_id': plan['run_id'], 'model_name': model['name'], 'model_config_hash': digest(model),
                    'case_id': case['id'], 'cluster_id': case['cluster_id'], 'language': case['language'],
                    'category': case['category'], 'modality': case.get('modality', 'text'), 'track': case['track'], 'repetition': repetition,
                    'queue_wait_seconds': queue_wait, 'input_hash': digest({'payload': fixed_payload(case), 'image_sha256': case.get('image_sha256')} if case['track'] == 'fixed' else {'text': case['text'], 'language': case['language'], 'origin': case.get('origin', {}), 'post_date': case.get('post_date', '')}),
                    'dataset_hash': dataset_hash, 'prompt_hash': digest({'system': FIXED_SYSTEM, 'schema': schema_for(case)}) if case['track'] == 'fixed' else plan['pipeline_source']['hash']})
        return row
    warmup_tasks = [(model, next(c for c in cases if c['track'] == track), repetition)
                    for model in models for track in sorted({c['track'] for c in cases}) for repetition in range(args.warmups)]
    with (out / 'warmups.jsonl').open('w') as handle:
        for task in warmup_tasks:
            row = invoke(task, time.perf_counter())
            row['warmup'] = True
            handle.write(json.dumps(row, ensure_ascii=False) + '\n')
            handle.flush()
            print(json.dumps({'warmup': row['model_name'], 'track': row['track'], 'status': row['status']}))
    tasks = [(m, c, repeat) for repeat in range(args.repetitions) for c in cases for m in models]
    random.Random(args.seed).shuffle(tasks)
    with (out / 'records.jsonl').open('w') as handle, concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as executor:
        futures = [executor.submit(invoke, task, time.perf_counter()) for task in tasks]
        for future in concurrent.futures.as_completed(futures):
            row = future.result()
            records.append(row)
            handle.write(json.dumps(row, ensure_ascii=False) + '\n')
            handle.flush()
            print(json.dumps({'completed': len(records), 'of': len(tasks), 'model': row['model_name'],
                              'case': row['case_id'], 'status': row['status'], 'seconds': round(row['duration_seconds'], 3)}))
    from .report import write_report
    summary = {'manifest': plan, 'finished_at': utcnow(), 'groups': summarize_groups(records),
               'paired_comparisons': paired_comparisons(records, samples=args.bootstrap_samples, seed=args.seed)}
    write_report(out, summary)
    return 0 if all(row['status'] == 'ok' for row in records) else 2


def positive(value):
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError('must be positive')
    return number


def nonnegative(value):
    number = int(value)
    if number < 0:
        raise argparse.ArgumentTypeError('must be zero or positive')
    return number


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    validate = sub.add_parser('validate', help='Check dataset provenance, exact spans, labels, and evidence IDs without network access.')
    validate.add_argument('--dataset', default=str(DEFAULT_DATASET))
    execute = sub.add_parser('run', help='Run a model matrix; use --dry-run to validate and write a plan without model calls.')
    execute.add_argument('--matrix', required=True)
    execute.add_argument('--dataset', default=str(DEFAULT_DATASET))
    execute.add_argument('--track', choices=('fixed', 'live', 'both'), default='fixed')
    execute.add_argument('--modality', choices=('text', 'image', 'all'), default='text')
    execute.add_argument('--models', help='Comma-separated matrix names.')
    execute.add_argument('--language', choices=('en', 'ro', 'ru'))
    execute.add_argument('--category')
    execute.add_argument('--case-id', action='append')
    execute.add_argument('--limit', type=positive)
    execute.add_argument('--repetitions', type=positive, default=1)
    execute.add_argument('--warmups', type=nonnegative, default=0)
    execute.add_argument('--concurrency', type=positive, default=1)
    execute.add_argument('--case-timeout', type=positive, default=180)
    execute.add_argument('--seed', type=int, default=1729)
    execute.add_argument('--bootstrap-samples', type=nonnegative, default=2000)
    execute.add_argument('--hardware-note', default='', help='Describe inference hardware/quantization or managed API region; never include secrets.')
    execute.add_argument('--save-responses', action='store_true')
    execute.add_argument('--dry-run', action='store_true')
    execute.add_argument('--out')
    args = parser.parse_args(argv)
    try:
        if args.command == 'validate':
            data, hash_value = load_dataset(args.dataset)
            print(json.dumps({'version': data['version'], 'cases': len(data['cases']), 'dataset_hash': hash_value, 'valid': True}))
            return 0
        if args.concurrency > 32 or args.case_timeout > 3600 or args.repetitions > 100 or args.warmups > 20:
            raise ValueError('Limits: concurrency 32, case timeout 3600s, repetitions 100, warmups 20.')
        return run(args)
    except (ValueError, OSError) as exc:
        parser.error(str(exc))


if __name__ == '__main__':
    raise SystemExit(main())
