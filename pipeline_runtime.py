"""Run the application pipelines with an explicit model, safely in parallel."""
from dataclasses import replace
import concurrent.futures
import json

import analysis
import local_analysis
from model_runtime import call_model


def _call_with_retry(config, system, parts, schema, search, telemetry, output_limit):
    selected = replace(config, max_output_tokens=min(config.max_output_tokens, output_limit))
    for attempt in range(2):
        try:
            return call_model(selected, system, parts, schema=schema, search=search, telemetry=telemetry)
        except analysis.AnalysisError as error:
            if error.code != 'invalid_output' or not schema or attempt:
                raise
            system += '\nReturn complete valid JSON matching all required schema fields.'


def _cloud_caller(config, telemetry):
    def generate(key, model, system, parts, schema=None, search=False,
                 provider='gemini', timeout=25, max_output_tokens=8192):
        return _call_with_retry(config, system, parts, schema, search, telemetry, max_output_tokens)
    return generate


def _local_caller(config, telemetry, image_mime):
    def generate(endpoint, model, system, payload, schema, images=None,
                 timeout=180, max_output_tokens=1600):
        parts = [{'text': json.dumps(payload, ensure_ascii=False)}]
        parts.extend({'inlineData': {'mimeType': image_mime, 'data': image}} for image in (images or []))
        return _call_with_retry(config, system, parts, schema, False, telemetry, max_output_tokens)
    return generate


def _uncached_sources():
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        return list(pool.map(local_analysis.fetch_source, local_analysis.SOURCES))


def analyze_with_config(body, config, progress=None, telemetry=None, use_cache=True):
    if config.provider in ('vertex', 'gemini'):
        result = analysis.analyze(body, '', config.model, provider=config.provider, progress=progress,
                                  generate_fn=_cloud_caller(config, telemetry))
        result['retrieval_regime'] = 'google_search_and_verified_factchecks'
    else:
        mime = (body.get('image') or {}).get('mime_type', 'image/png')
        result = local_analysis.analyze_local(body, config.endpoint, config.model, progress=progress,
            generate_fn=_local_caller(config, telemetry, mime),
            retrieve_fn=None if use_cache else _uncached_sources)
        result['retrieval_regime'] = 'limited_official_corpus_and_verified_factchecks'
        result['local_provider'] = config.provider
    result['model'] = config.model
    return result


def precheck_with_config(body, config, progress=None, telemetry=None, use_cache=True):
    if config.provider in ('vertex', 'gemini'):
        return analysis.precheck(body, '', config.model, provider=config.provider, progress=progress,
                                 generate_fn=_cloud_caller(config, telemetry))
    mime = (body.get('image') or {}).get('mime_type', 'image/png')
    result = local_analysis.precheck_local(body, config.endpoint, config.model, progress=progress,
                                          generate_fn=_local_caller(config, telemetry, mime))
    result['local_provider'] = config.provider
    return result
