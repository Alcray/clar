import copy
import dataclasses
import json
import multiprocessing
from pathlib import Path
import tempfile
import time
import types
import unittest
from unittest.mock import patch

from benchmarks.contract import FIXED_SCHEMA, OutputValidationError, validate_output
from benchmarks.dataset import DEFAULT_DATASET, fixed_payload, load_dataset
from benchmarks.metrics import paired_comparisons, score_case, summarize, summarize_groups
from benchmarks.runner import execute_case, isolated_case, load_matrix, main


def golden(case):
    result = {'statements': [dict(text=s['text'], kind=s['kind'], verdict=s['verdict'], evidence_ids=s['evidence_ids'], confidence=.9)
                           for s in case['expected']['statements']],
            'purpose': case['expected']['purpose'], 'techniques': case['expected']['techniques'],
            'fraud_signal': case['expected'].get('fraud_signal', False)}
    if case.get('modality') == 'image':
        result['original_text'] = case['text']
    return result


def row(case, result=None, name='model-a', seconds=1, repetition=0):
    record = {'model_name': name, 'track': case['track'], 'language': case['language'], 'category': case['category'],
              'case_id': case['id'], 'cluster_id': case['cluster_id'], 'status': 'ok', 'duration_seconds': seconds,
              'repetition': repetition, 'modality': case.get('modality', 'text'), 'telemetry': {}}
    record['scores'] = score_case(case, result or golden(case))
    return record


# Spawn-compatible workers: these never contact a provider.
def sleeping_worker(connection, model, case, save):
    connection.send({'event': 'started'})
    connection.send({'event': 'progress', 'progress': [{'stage': 'reading', 'state': 'done'}],
                     'telemetry': {'requests': 1, 'input_tokens': 10}})
    time.sleep(10)


def finishing_worker(connection, model, case, save):
    connection.send({'event': 'started'})
    connection.send({'event': 'result', 'result': {'status': 'ok', 'duration_seconds': .001, 'telemetry': {}, 'progress': []}})
    connection.close()


class DatasetTests(unittest.TestCase):
    def setUp(self):
        self.dataset, self.hash = load_dataset()
        self.fixed = [c for c in self.dataset['cases'] if c['track'] == 'fixed']

    def test_dataset_is_versioned_editorial_multilingual_and_live_marked_reused(self):
        self.assertEqual(len(self.fixed), 66)
        self.assertEqual({c['language'] for c in self.fixed}, {'en', 'ro', 'ru'})
        self.assertEqual(len({c['cluster_id'] for c in self.fixed}), 20)
        self.assertTrue(all(c['provenance']['label_status'] == 'author_proposed_not_human_validated' for c in self.fixed))
        for case in self.dataset['cases']:
            if case['track'] == 'live':
                self.assertEqual(case['provenance']['kind'], 'reused_existing_demo_fixture')
                self.assertTrue(case['provenance']['labels_as_of'])

    def test_every_fixed_gold_has_valid_contract_and_exact_quotes(self):
        for case in self.fixed:
            value = validate_output(golden(case), image=case.get('modality') == 'image')
            score = score_case(case, value)
            self.assertEqual(score['case_values']['kind_accuracy'], 1)
            self.assertIn(score['case_values']['verdict_accuracy'], (1, None))
            self.assertNotIn('expected', fixed_payload(case))
            self.assertNotIn('rationale', json.dumps(fixed_payload(case)))

    def test_unknown_evidence_and_noncontiguous_gold_quotes_rejected(self):
        for mutation in ('evidence', 'quote'):
            dataset = copy.deepcopy(self.dataset)
            target = dataset['cases'][0]['expected']['statements'][0]
            target['evidence_ids' if mutation == 'evidence' else 'text'] = ['INVENTED'] if mutation == 'evidence' else 'Not in the original post'
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / 'bad.json'
                path.write_text(json.dumps(dataset))
                with self.assertRaises(ValueError):
                    load_dataset(path)


class ScoringTests(unittest.TestCase):
    def setUp(self):
        self.dataset, _ = load_dataset()
        self.cases = {c['id']: c for c in self.dataset['cases']}

    def test_citation_coverage_counts_missing_claim_and_relevance_counts_extra_citations(self):
        case = self.cases['calendar-en']
        result = golden(case)
        result['statements'] = [{'text': 'Unrelated fabricated assertion', 'kind': 'factual', 'verdict': 'supported', 'evidence_ids': ['E1'], 'confidence': .9}]
        summary = summarize([row(case, result)])
        self.assertEqual(summary['citation_coverage'], 0)
        self.assertEqual(summary['citation_relevance'], 0)
        self.assertEqual(summary['counts']['evidence_required_claims'], 1)

    def test_editorial_equivalent_atomic_segmentation_has_full_credit(self):
        case = self.cases['budget-scope-en']
        result = golden(case)
        result['statements'] = [dict(x, confidence=.9) for x in case['expected']['statement_variants'][0]]
        score = score_case(case, result)
        self.assertEqual(score['expected_variant_index'], 1)
        self.assertEqual(score['case_values']['kind_accuracy'], 1)
        self.assertEqual(score['case_values']['verdict_accuracy'], 1)

    def test_cite_everything_fails_relevance_on_every_fixed_case(self):
        for case in self.cases.values():
            if case['track'] != 'fixed':
                continue
            result = golden(case)
            result['statements'][0]['evidence_ids'] = [e['id'] for e in case['evidence']]
            self.assertLess(summarize([row(case, result)])['citation_relevance'], 1)

    def test_ocr_measures_errors_and_perfect_transcription(self):
        case = self.cases['calendar-ro-image']
        result = golden(case)
        self.assertEqual(summarize([row(case, result)])['ocr']['word_error_rate'], 0)
        result['original_text'] = ''
        self.assertEqual(summarize([row(case, result)])['ocr']['character_error_rate'], 1)
        self.assertEqual(summarize([row(case, result)])['ocr']['word_error_rate'], 1)

    def test_perfect_full_corpus_scores_and_absence_of_fake_usage(self):
        records = [row(c) for c in self.dataset['cases'] if c['track'] == 'fixed']
        summary = summarize(records)
        self.assertEqual(summary['kind']['macro_f1'], 1)
        self.assertEqual(summary['verdict']['macro_f1'], 1)
        self.assertEqual(summary['false_accusation_rate'], 0)
        self.assertEqual(summary['citation_id_validity'], 1)
        self.assertEqual(summary['citation_relevance'], 1)
        self.assertEqual(summary['statement_quote_compliance'], 1)
        self.assertIsNone(summary['usage']['input_tokens']['total_known'])
        self.assertEqual(len(summarize_groups(records)['model-a/fixed']['by_language']), 3)

    def test_failures_have_no_quality_score_and_latency_is_separate(self):
        case = self.cases['calendar-en']
        record = row(case)
        record.update(status='timeout', duration_seconds=180)
        record.pop('scores')
        summary = summarize([record])
        self.assertEqual(summary['completion_rate'], 0)
        self.assertIsNone(summary['kind']['accuracy'])
        self.assertIsNone(summary['latency_seconds']['p50'])
        self.assertEqual(summary['latency_seconds']['all_attempts_p50'], 180)

    def test_false_accusations_include_unsupported_attack_on_opinion(self):
        case = self.cases['harmless-opinion-en']
        result = golden(case)
        result['statements'][0]['verdict'] = 'contradicted'
        result['fraud_signal'] = True
        summary = summarize([row(case, result)])
        self.assertEqual(summary['false_accusation_rate'], 1)
        self.assertEqual(summary['false_fraud_accusation_rate'], 1)

    def test_missing_and_extra_claims_are_scored_not_silently_dropped(self):
        case = self.cases['mixed-post-en']
        result = golden(case)
        result['statements'].pop()
        result['statements'].append({'text': 'A completely fabricated unrelated accusation', 'kind': 'factual',
                                     'verdict': 'contradicted', 'confidence': .9, 'evidence_ids': []})
        summary = summarize([row(case, result)])
        self.assertAlmostEqual(summary['extraction']['recall'], 2 / 3)
        self.assertLess(summary['kind']['accuracy'], 1)
        self.assertEqual(summary['extra_harmful_claims'], 1)
        self.assertLess(summary['statement_quote_compliance'], 1)

    def test_invalid_and_irrelevant_citations_are_different_metrics(self):
        case = copy.deepcopy(self.cases['calendar-en'])
        case['evidence'].append({'id': 'E2', 'excerpt': 'Unrelated', 'title': 'Other', 'provenance': 'synthetic'})
        result = golden(case)
        result['statements'][0]['evidence_ids'] = ['E2', 'E999']
        summary = summarize([row(case, result)])
        self.assertEqual(summary['citation_id_validity'], .5)
        self.assertEqual(summary['citation_relevance'], 0)
        self.assertEqual(summary['citation_coverage'], 0)

    def test_abstention_does_not_imply_false_accusation(self):
        case = self.cases['calendar-en']
        result = golden(case)
        result['statements'][0]['verdict'] = 'insufficient'
        summary = summarize([row(case, result)])
        self.assertEqual(summary['abstention_rate'], 1)
        self.assertEqual(summary['decisive_coverage'], 0)
        self.assertEqual(summary['false_accusation_rate'], 0)

    def test_neutral_titles_false_positive_is_measured(self):
        case = self.cases['neutral-titles-en']
        result = golden(case)
        result['techniques'] = [{'type': 'authority_appeal', 'quote': 'Dr Ana Lupu'}]
        summary = summarize([row(case, result)])
        self.assertEqual(summary['techniques']['per_type']['authority_appeal']['fp'], 1)
        self.assertEqual(summary['techniques']['macro_f1'], 0)

    def test_alternative_editorial_labels_accept_the_pair(self):
        case = self.cases['live-stopfals-gagauzia-181558']
        result = golden(case)
        result['statements'][0].update(kind='factual', verdict='misleading')
        summary = summarize([row(case, result)])
        self.assertEqual(summary['kind']['accuracy'], 1)
        self.assertEqual(summary['verdict']['accuracy'], 1)
        self.assertEqual(summary['false_accusation_rate'], None)
        self.assertIsNone(summary['purpose_accuracy'])
        self.assertIsNone(summary['citation_id_validity'])

    def test_bootstrap_pairs_clusters_and_excludes_failed_cases(self):
        cases = [self.cases['calendar-' + lang] for lang in ('en', 'ro', 'ru')] + [self.cases['library-closed-en']]
        records = [row(c, name=model, seconds=duration, repetition=repeat) for c in cases
                   for model, duration in [('a', 2), ('b', 1)] for repeat in range(2)]
        comparisons = paired_comparisons(records, samples=100)
        latency = next(r for r in comparisons if r['metric'] == 'duration_seconds')
        self.assertEqual(latency['semantic_clusters'], 2)
        self.assertEqual(latency['paired_cases'], 4)
        self.assertEqual(latency['difference_right_minus_left'], -1)
        self.assertEqual(latency['bootstrap_95_interval'], [-1, -1])


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.dataset, _ = load_dataset()
        self.case = self.dataset['cases'][0]
        self.config = {'name': 'test', 'provider': 'ollama', 'model': 'test-model', 'api_key_env': 'TEST_BENCHMARK_KEY'}

    def fake_runtime(self, call):
        return types.SimpleNamespace(ModelConfig=lambda **kw: types.SimpleNamespace(**kw), call_model=call)

    def test_fixed_model_gets_only_input_and_equal_evidence_not_gold(self):
        calls = []
        def call(config, system, parts, **kwargs):
            calls.append((config, system, json.loads(parts[0]['text']), kwargs))
            kwargs['telemetry'].update(input_tokens=123, calls=[{'model': 'test-model', 'input_tokens': 123, 'api_key': 'SECRET'}])
            return golden(self.case)
        with patch('benchmarks.runner.importlib.import_module', return_value=self.fake_runtime(call)):
            result = execute_case(self.config, self.case, True)
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(calls[0][3]['schema'], FIXED_SCHEMA)
        self.assertIs(calls[0][3]['search'], False)
        self.assertNotIn('expected', calls[0][2])
        self.assertNotIn('SECRET', json.dumps(result))
        self.assertEqual(result['telemetry']['input_tokens'], 123)
        self.assertIn('response', result)

    def test_image_model_receives_pixels_and_evidence_without_plaintext_post(self):
        case = next(c for c in self.dataset['cases'] if c.get('modality') == 'image')
        observed = {}
        def call(config, system, parts, **kwargs):
            observed.update(parts=parts, schema=kwargs['schema'])
            return golden(case)
        with patch('benchmarks.runner.importlib.import_module', return_value=self.fake_runtime(call)):
            result = execute_case(self.config, case)
        self.assertEqual(result['status'], 'ok')
        payload = json.loads(observed['parts'][0]['text'])
        self.assertNotIn('post', payload)
        self.assertNotIn('expected', payload)
        self.assertEqual(observed['parts'][1]['inlineData']['mimeType'], 'image/png')
        self.assertIn('original_text', observed['schema']['required'])
        self.assertEqual(result['scores']['counts']['ocr_character_edits'], 0)

    def test_nonfactual_supported_verdict_is_invalid_not_perfect(self):
        result = golden(next(c for c in self.dataset['cases'] if c['id'] == 'harmless-opinion-en'))
        result['statements'][0]['verdict'] = 'supported'
        with self.assertRaises(OutputValidationError):
            validate_output(result)

    def test_provider_errors_do_not_leak_exception_text_or_become_quality_zero(self):
        def call(*args, **kwargs):
            raise RuntimeError('Authorization: Bearer SUPER_SECRET')
        with patch('benchmarks.runner.importlib.import_module', return_value=self.fake_runtime(call)):
            result = execute_case(self.config, self.case)
        self.assertEqual(result['status'], 'error')
        self.assertNotIn('scores', result)
        self.assertNotIn('SUPER_SECRET', json.dumps(result))

    def test_invalid_schema_is_reported_separately(self):
        with patch('benchmarks.runner.importlib.import_module', return_value=self.fake_runtime(lambda *a, **k: {'nonsense': True})):
            result = execute_case(self.config, self.case)
        self.assertEqual(result['status'], 'invalid_output')
        self.assertNotIn('scores', result)

    def test_live_pipeline_bypasses_cache_and_records_dated_sources(self):
        case = next(c for c in self.dataset['cases'] if c['track'] == 'live')
        observed = {}
        def live(body, config, **kwargs):
            observed.update(body=body, kwargs=kwargs)
            kwargs['progress']('reading', 'done')
            return {'retrieval_regime': 'mock_search', 'statements': [{'text': case['text'], 'kind': 'factual', 'verdict': 'misleading',
                                     'evidence': [{'id': 'E1', 'url': case['provenance']['reference_urls'][0]}]}]}
        runtime = self.fake_runtime(None)
        pipeline = types.SimpleNamespace(analyze_with_config=live)
        with patch('benchmarks.runner.importlib.import_module', side_effect=lambda name: runtime if name == 'model_runtime' else pipeline):
            result = execute_case(self.config, case)
        self.assertEqual(result['status'], 'ok')
        self.assertIs(observed['kwargs']['use_cache'], False)
        self.assertNotIn('expected', observed['body'])
        self.assertTrue(result['freshness']['labels_as_of'])
        self.assertTrue(result['freshness']['reference_url_overlap'])
        self.assertEqual(result['telemetry']['retrieval_regime'], 'mock_search')

    def test_worker_deadline_terminates_worker_and_preserves_partial_telemetry(self):
        before = {p.pid for p in multiprocessing.active_children()}
        with patch('benchmarks.runner._child', sleeping_worker):
            result = isolated_case(self.config, self.case, case_timeout=1)
        self.assertEqual(result['status'], 'timeout')
        self.assertNotIn('scores', result)
        self.assertEqual(result['telemetry']['input_tokens'], 10)
        self.assertEqual({p.pid for p in multiprocessing.active_children()}, before)

    def test_successful_worker_measures_startup_separately(self):
        with patch('benchmarks.runner._child', finishing_worker):
            result = isolated_case(self.config, self.case, case_timeout=5)
        self.assertEqual(result['status'], 'ok')
        self.assertGreater(result['turnaround_seconds'], result['duration_seconds'])
        self.assertGreaterEqual(result['worker_startup_seconds'], 0)

    def test_matrix_forbids_inline_credentials_and_credential_urls(self):
        for bad in [dict(self.config, api_key='SECRET'), dict(self.config, endpoint='https://user:SECRET@host/v1'),
                    dict(self.config, endpoint='https://host/v1?key=SECRET')]:
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / 'matrix.json'
                path.write_text(json.dumps({'models': [bad]}))
                with self.assertRaises(ValueError):
                    load_matrix(path)

    def test_cli_dry_run_makes_no_runtime_import(self):
        with tempfile.TemporaryDirectory() as tmp:
            matrix = Path(tmp) / 'matrix.json'
            matrix.write_text(json.dumps({'models': [self.config]}))
            out = Path(tmp) / 'run'
            with patch('benchmarks.runner.importlib.import_module', side_effect=AssertionError('No provider calls permitted')):
                self.assertEqual(main(['run', '--matrix', str(matrix), '--limit', '1', '--dry-run', '--out', str(out)]), 0)
            self.assertTrue((out / 'manifest.json').exists())
            self.assertFalse((out / 'records.jsonl').exists())

    def test_full_mock_run_produces_report_and_excludes_warmups(self):
        def fake(model, case, *args):
            result = row(case, name=model['name'])
            result['telemetry'] = {}
            return result
        with tempfile.TemporaryDirectory() as tmp:
            matrix = Path(tmp) / 'matrix.json'
            matrix.write_text(json.dumps({'models': [self.config]}))
            out = Path(tmp) / 'run'
            with patch('benchmarks.runner.isolated_case', side_effect=fake):
                status = main(['run', '--matrix', str(matrix), '--limit', '2', '--warmups', '1', '--repetitions', '2',
                               '--concurrency', '2', '--out', str(out)])
            self.assertEqual(status, 0)
            self.assertEqual(len((out / 'records.jsonl').read_text().splitlines()), 4)
            self.assertEqual(len((out / 'warmups.jsonl').read_text().splitlines()), 1)
            summary = json.loads((out / 'summary.json').read_text())
            self.assertEqual(summary['groups']['test/fixed']['attempted'], 4)
            self.assertIn('No time-to-first-token', (out / 'report.md').read_text())
            self.assertIn('not independently validated gold', (out / 'report.md').read_text())


if __name__ == '__main__':
    unittest.main()
