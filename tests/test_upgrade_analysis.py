"""Safety and contract checks; no model keys or live inference required."""
import copy
import json
import unittest
from pathlib import Path
from unittest.mock import patch

import analysis
import factchecks
import local_analysis
import origins
from media_literacy import normalize_media, unavailable_media


class UpgradeAnalysisTests(unittest.TestCase):
    def statement(self, text):
        return {'id': 'C1', 'text': text, 'kind': 'factual', 'context': '', 'explanation': '',
                'verdict': 'insufficient', 'evidence': []}

    def finding(self, record, evidence_id='C1F1'):
        return {'id': 'C1', 'verdict': {'FALSE': 'contradicted', 'MISLEADING': 'misleading'}[record['verdict']],
                'explanation': record['summary'], 'evidence_ids': [evidence_id],
                'source_stances': [{'evidence_id': evidence_id, 'stance': 'contradicts' if record['verdict'] == 'FALSE' else 'context'}],
                'fact_check_match': {'evidence_id': evidence_id, 'relation': 'same_claim', 'post_author_stance': 'adopts_claim',
                                     'same_scope': True, 'explanation': 'Same assertion and scope.'}}

    def test_four_verified_cases_supply_candidates_but_never_auto_verdict(self):
        records = factchecks.known_records()
        self.assertEqual(len(records), 4)
        for record in records:
            with self.subTest(record=record['id']):
                self.assertIn(record['id'], [r['id'] for r in factchecks.candidate_records(record['claim'])])
                statement = self.statement(record['claim'])
                source = factchecks.candidate_evidence(record, 'C1', 1)
                research = {'C1': {'sources': [source]}}
                bad_finding = self.finding(record)
                bad_finding.pop('fact_check_match')
                analysis.apply_findings([statement], {'findings': [bad_finding]}, research, 'en', record['claim'])
                self.assertEqual(statement['verdict'], 'insufficient')
                self.assertEqual(statement['fact_check']['relation'], 'related_context')
                self.assertEqual(statement['fact_check']['verdict'], '')
                analysis.apply_findings([statement], {'findings': [self.finding(record)]}, research, 'en', record['claim'])
                self.assertEqual(statement['fact_check']['url'], record['url'])
                result = {'original_text': record['claim'], 'summary': 'One claim.', 'statements': [statement]}
                analysis.enrich_result(result, {}, 'en')
                self.assertEqual(result['overall']['label'], record['verdict'])
                self.assertEqual(result['schema_version'], 2)
                self.assertEqual(result['analysis_version'], 'clar-0.4.1')

    def test_negations_satire_and_changed_dates_cannot_inherit_fixture_verdict(self):
        for record in factchecks.known_records():
            for text in ('It is not true that ' + record['claim'],
                         'Satire: ' + record['claim'],
                         'In 2030, ' + record['claim']):
                with self.subTest(text=text):
                    statement = self.statement(text)
                    research = {'C1': {'sources': [factchecks.candidate_evidence(record, 'C1', 1)]}}
                    # Even an overconfident semantic model must not bypass these vetoes.
                    analysis.apply_findings([statement], {'findings': [self.finding(record)]}, research, 'en', text)
                    self.assertEqual(statement['verdict'], 'insufficient')
                    self.assertFalse(statement['fact_check'])

    def test_related_topic_or_refutation_relation_cannot_supply_evidence(self):
        record = factchecks.known_records()[2]
        for modification in ({'relation': 'related_topic'}, {'post_author_stance': 'rejects_claim'}, {'same_scope': False}):
            finding = self.finding(record)
            finding['fact_check_match'].update(modification)
            statement = self.statement(record['claim'])
            analysis.apply_findings([statement], {'findings': [finding]},
                                    {'C1': {'sources': [factchecks.candidate_evidence(record, 'C1', 1)]}}, 'en')
            self.assertEqual(statement['evidence'], [])
            self.assertEqual(statement['verdict'], 'insufficient')

    def test_post_author_stance_is_distinct_from_factchecker_disagreement(self):
        record = factchecks.known_records()[2]
        source = factchecks.candidate_evidence(record, 'C1', 1)
        finding = self.finding(record)
        # A Facebook author adopts X while the fact-check source contradicts X.
        self.assertEqual(finding['fact_check_match']['post_author_stance'], 'adopts_claim')
        self.assertEqual(finding['source_stances'][0]['stance'], 'contradicts')
        statement = self.statement(record['claim'])
        analysis.apply_findings([statement], {'findings': [finding]}, {'C1': {'sources': [source]}}, 'en', record['claim'])
        self.assertEqual(statement['verdict'], 'contradicted')
        self.assertEqual(statement['fact_check']['verdict'], 'FALSE')
        # The old ambiguous field must not silently be coerced into adoption.
        ambiguous = copy.deepcopy(finding)
        ambiguous['fact_check_match'].pop('post_author_stance')
        ambiguous['fact_check_match']['stance'] = 'refutes'
        statement = self.statement(record['claim'])
        analysis.apply_findings([statement], {'findings': [ambiguous]}, {'C1': {'sources': [source]}}, 'en', record['claim'])
        self.assertEqual(statement['verdict'], 'insufficient')
        self.assertEqual(statement['fact_check']['relation'], 'related_context')
        self.assertEqual(statement['fact_check']['verdict'], '')

    def test_primary_search_error_cannot_overwrite_valid_factcheck_explanation(self):
        record = factchecks.known_records()[3]
        source = factchecks.candidate_evidence(record, 'C1', 1)
        statement = self.statement(record['claim'])
        finding = self.finding(record)
        analysis.apply_findings([statement], {'findings': [finding]},
                                {'C1': {'sources': [source], 'error': 'Provider timed out.'}}, 'en', record['claim'])
        self.assertEqual(statement['verdict'], 'contradicted')
        self.assertEqual(statement['explanation'], record['summary'])
        self.assertEqual(statement['fact_check']['verdict'], 'FALSE')
        self.assertIn('could not finish', statement['research_note'])
        self.assertNotIn('not return enough', statement['explanation'])

    def test_multilingual_candidates_and_unknown_topics(self):
        for text in ('În Moldova gazele sunt mai scumpe decât în majoritatea țărilor europene.',
                     'В Молдове газ дороже, чем в большинстве стран Европы.'):
            self.assertEqual(factchecks.candidate_records(text)[0]['id'], 'stopfals-gas-181552')
        self.assertEqual(factchecks.candidate_records('A new library opened yesterday.'), [])

    def test_vetted_article_summaries_and_scope_follow_output_language(self):
        for record in factchecks.known_records():
            for language in ('ro', 'ru'):
                source = factchecks.candidate_evidence(record, 'C1', 1, language)
                self.assertEqual(source['finding'], record['summary_translations'][language])
                self.assertEqual(source['scope'], record['scope_translations'][language])
                self.assertEqual(source['title'], record['title'])
                self.assertEqual(source['fact_check_record']['publisher_verdict'], record['publisher_verdict'])

    def test_research_language_is_explicit_in_system_instruction(self):
        for language, name in (('ro', 'Romanian'), ('ru', 'Russian')):
            with patch('analysis.generate', return_value={'content': {'parts': []}}) as generate:
                analysis.research_claim(self.statement('A claim.'), '', language, 'test', 'model')
                self.assertIn('in ' + name, generate.call_args.args[2])

    def test_known_context_does_not_convert_political_interpretation_into_falsehood(self):
        record = factchecks.known_records()[1]
        statement = self.statement(record['claim'])
        statement.update(kind='opinion', verdict='not_applicable', explanation='An interpretation of political purpose.')
        self.assertTrue(factchecks.attach_related_context(statement, record['claim'], 'en'))
        result = analysis.enrich_result({'original_text': record['claim'], 'statements': [statement]}, {}, 'en')
        self.assertEqual(result['overall']['label'], 'OPINION')
        self.assertEqual(statement['verdict'], 'not_applicable')
        self.assertEqual(statement['evidence'], [])
        self.assertEqual(statement['fact_check']['relation'], 'related_context')
        self.assertEqual(statement['fact_check']['verdict'], '')
        self.assertEqual(statement['fact_check']['publisher_verdict'], '')
        self.assertIn('does not establish or refute', statement['fact_check']['match_explanation'])
        self.assertTrue(statement['fact_check']['claim_assessment_unchanged'])

    def test_lookup_diagnostics_expose_only_bounded_identifiers_and_states(self):
        record = factchecks.known_records()[0]
        statement = self.statement(record['claim'])
        finding = self.finding(record)
        finding['fact_check_match'].update(relation='related_topic', same_scope=False)
        analysis.apply_findings([statement], {'findings': [finding]},
                                {'C1': {'sources': [factchecks.candidate_evidence(record, 'C1', 1)]}}, 'en', record['claim'])
        self.assertEqual(statement['verdict'], 'insufficient')
        lookup = statement['fact_check_lookup']
        self.assertEqual(lookup['candidate_ids'], ['C1F1'])
        self.assertEqual(lookup['referenced_evidence_id'], 'C1F1')
        self.assertEqual(lookup['relation'], 'related_topic')
        self.assertFalse(lookup['same_scope'])
        self.assertFalse(lookup['verdict_match_attached'])
        self.assertNotIn('summary', lookup)
        self.assertNotIn('explanation', lookup)

    def test_publisher_url_enforces_domains_before_network(self):
        with patch('factchecks.urllib.request.build_opener') as request:
            for url in ('http://stopfals.md/article/x', 'https://stopfals.md.evil.example/x',
                        'https://127.0.0.1/x', 'https://stopfals.md@localhost/x',
                        'https://vertexaisearch.cloud.google.com:6666/grounding-api-redirect/x'):
                self.assertEqual(factchecks.publisher_url(url), '')
        request.assert_not_called()
        self.assertEqual(factchecks.publisher_url('https://stopfals.md/ro/article/a'), 'https://stopfals.md/ro/article/a')

    def test_origin_exact_identity_and_anonymity_not_name_or_politics(self):
        known = origins.assess_origin({'poster_name': 'Anything', 'poster_url': 'https://www.facebook.com/GuvernulRepubliciiMoldova/?locale=ro_RO', 'context': 'page'})
        self.assertEqual(known['type'], 'official')
        self.assertEqual(known['matched_registry']['verified_from'], 'https://gov.md/ro')
        for url in ('https://facebook.com/GuvernulRepubliciiMoldova-fan', 'https://facebook.com.evil.test/GuvernulRepubliciiMoldova',
                    'https://www.facebook.com/GuvernulRepubliciiMoldova/posts/123'):
            unknown = origins.assess_origin({'poster_name': 'Guvernul Republicii Moldova', 'poster_url': url, 'context': 'page', 'visible_notes': ['New political page']})
            self.assertEqual(unknown['type'], 'unknown_page')
            self.assertIsNone(unknown['matched_registry'])
        self.assertEqual(origins.assess_origin({'context': 'group', 'anonymous': True})['type'], 'anonymous_group')
        self.assertEqual(origins.assess_origin({'context': 'page', 'anonymous': True})['type'], 'unknown_page')

    def test_primary_control_gets_evidence_based_label_without_fixture_override(self):
        case = next(c for c in json.loads((Path(__file__).parents[1] / 'fixtures/analysis_cases.json').read_text()) if c['id'] == 'government-control')
        self.assertEqual(factchecks.candidate_records(case['text']), [])
        statement = self.statement(case['text'])
        finding = {'id': 'C1', 'verdict': 'supported', 'explanation': 'The dated Government announcement reports this decision.',
                   'evidence_ids': ['C1E1'], 'source_stances': [{'evidence_id': 'C1E1', 'stance': 'confirms'}]}
        evidence = {'id': 'C1E1', 'url': case['source_url'], 'title': 'Government announcement', 'finding': case['text'], 'label': 'Google Search grounding'}
        analysis.apply_findings([statement], {'findings': [finding]}, {'C1': {'sources': [evidence]}}, 'ro')
        result = analysis.enrich_result({'original_text': case['text'], 'summary': 'O afirmație.', 'statements': [statement]}, {'origin': case['origin']}, 'ro')
        self.assertEqual(result['overall']['label'], 'VERIFIED_FACT')
        self.assertEqual(result['origin']['type'], 'official')
        self.assertEqual(result['overall']['confidence'], 'medium')
        self.assertIsNone(result['statements'][0]['fact_check'])

    def test_context_evidence_cannot_confirm_claim(self):
        statement = self.statement('A specific claim.')
        finding = {'id': 'C1', 'verdict': 'supported', 'explanation': 'Confirmed!', 'evidence_ids': ['C1E1'],
                   'source_stances': [{'evidence_id': 'C1E1', 'stance': 'context'}]}
        analysis.apply_findings([statement], {'findings': [finding]}, {'C1': {'sources': [{'id': 'C1E1', 'url': 'https://gov.md/'}]}}, 'en')
        self.assertEqual(statement['verdict'], 'insufficient')
        self.assertNotIn('Confirmed', statement['explanation'])

    def test_conflicting_assessment_and_singleton_mixed_have_safe_summaries(self):
        for language in ('en', 'ro', 'ru'):
            statement = self.statement('Sources disagree.')
            statement.update(verdict='conflicting', evidence=[{'url': 'https://gov.md/a'}, {'url': 'https://ipn.md/b'}])
            result = analysis.enrich_result({'original_text': statement['text'], 'statements': [copy.deepcopy(statement)]}, {}, language)
            self.assertEqual(result['overall']['label'], 'UNVERIFIED_CLAIM')
            self.assertEqual(result['overall']['confidence'], 'low')
            self.assertTrue(result['overall']['summary'])
            # Also protects integrations that map conflicting to the broader MIXED label.
            with patch.dict(analysis.LABELS, {'conflicting': 'MIXED'}):
                result = analysis.enrich_result({'original_text': statement['text'], 'statements': [copy.deepcopy(statement)]}, {}, language)
                self.assertEqual(result['overall']['label'], 'MIXED')
                self.assertTrue(result['overall']['summary'])

    def test_dynamic_factcheck_never_borrows_our_verdict_as_publisher_metadata(self):
        record = factchecks.known_records()[2]
        source = factchecks.candidate_evidence(record, 'C1', 1)
        source['retrieval'] = 'google_grounding_publisher_domain'
        source['fact_check_record'] = {'outlet': 'StopFals', 'url': source['url'], 'title': source['title'],
                                       'date': '', 'verdict': ''}
        statement = self.statement(record['claim'])
        analysis.apply_findings([statement], {'findings': [self.finding(record)]}, {'C1': {'sources': [source]}}, 'en', record['claim'])
        self.assertEqual(statement['verdict'], 'contradicted')
        fact_check = statement['fact_check']
        self.assertEqual(fact_check['verdict'], '')
        self.assertEqual(fact_check['publisher_verdict'], '')
        self.assertEqual(fact_check['date'], '')
        self.assertFalse(fact_check['verdict_verified'])
        self.assertFalse(fact_check['publisher_rating_verified'])
        self.assertFalse(fact_check['date_verified'])
        self.assertEqual(fact_check['match_explanation'], fact_check['match_note'])

    def test_editorial_normalization_is_distinguished_from_publisher_rating(self):
        for record in factchecks.known_records():
            source = factchecks.candidate_evidence(record, 'C1', 1)
            statement = self.statement(record['claim'])
            analysis.apply_findings([statement], {'findings': [self.finding(record)]}, {'C1': {'sources': [source]}}, 'en', record['claim'])
            fact_check = statement['fact_check']
            self.assertEqual(fact_check['publisher_rating_verified'], record['verdict'] == 'FALSE')
            self.assertTrue(fact_check['date_verified'])
            self.assertTrue(fact_check['rating_note'])

    def test_factcheck_metadata_localizes_explanation_but_preserves_publisher_rating(self):
        record = factchecks.known_records()[2]
        for language, marker in (('ro', 'publicației'), ('ru', 'издателя')):
            source = factchecks.candidate_evidence(record, 'C1', 1)
            statement = self.statement(record['claim'])
            analysis.apply_findings([statement], {'findings': [self.finding(record)]}, {'C1': {'sources': [source]}}, language, record['claim'])
            result = analysis.enrich_result({'original_text': record['claim'], 'statements': [statement]}, {}, language)
            claim = result['statements'][0]
            self.assertIn(marker, claim['fact_check']['rating_note'])
            self.assertEqual(claim['fact_check']['publisher_verdict'], 'FALS')
            self.assertNotIn('Manually verified', claim['evidence'][0]['label'])

    def test_core_json_is_validated_and_retried_exactly_once(self):
        valid = {'original_text': 'A claim.', 'statements': [{'text': 'A claim.', 'kind': 'factual', 'context': '', 'explanation': ''}]}
        invalid = {**valid, 'statements': 'not an array'}
        with patch('analysis._generate_once', side_effect=[invalid, valid]) as generate:
            result = analysis.generate('test', 'test', 'system', [], schema=analysis.EXTRACT_SCHEMA)
            self.assertEqual(result, valid)
            self.assertEqual(generate.call_count, 2)
        with patch('analysis._generate_once', return_value=invalid) as generate:
            with self.assertRaises(analysis.AnalysisError):
                analysis.generate('test', 'test', 'system', [], schema=analysis.EXTRACT_SCHEMA)
            self.assertEqual(generate.call_count, 2)
        with patch('analysis._generate_once', side_effect=analysis.AnalysisError('Quota', 429, 'api_quota')) as generate:
            with self.assertRaises(analysis.AnalysisError):
                analysis.generate('test', 'test', 'system', [], schema=analysis.EXTRACT_SCHEMA)
            self.assertEqual(generate.call_count, 1)

    def test_local_json_retry_has_same_contract(self):
        with patch('local_analysis._generate_local_once', side_effect=[{'findings': 'invalid'}, {'findings': []}]) as generate:
            self.assertEqual(local_analysis.generate_local('http://localhost:11434', 'model', 'system', {}, local_analysis.ASSESSMENT_SCHEMA), {'findings': []})
            self.assertEqual(generate.call_count, 2)

    def test_precheck_never_claims_to_verify_sources(self):
        text = 'Parliament has 150 members.'
        raw = {'original_text': text, 'statements': [{'text': text, 'kind': 'factual', 'context': '', 'explanation': 'A checkable assertion.'}],
               'media_literacy': {k: v for k, v in unavailable_media('en').items() if k in ('purpose', 'desired_response', 'signals', 'reading_tip')}}
        for module, method in ((analysis, 'precheck'), (local_analysis, 'precheck_local')):
            tool_name = 'generate' if module is analysis else 'generate_local'
            stages = []
            with patch.object(module, tool_name, return_value=copy.deepcopy(raw)) as generate:
                result = getattr(module, method)({'text': text}, 'test', 'test', progress=lambda stage, state: stages.append((stage, state)))
            self.assertEqual(result['overall']['label'], 'CHECKABLE_CLAIMS')
            self.assertTrue(result['overall']['is_preliminary'])
            self.assertEqual(result['original_text'], text)
            self.assertFalse(result['statements'][0]['sources'])
            self.assertIn(('sources', 'skipped'), stages)
            self.assertIn(('factchecks', 'skipped'), stages)
            self.assertEqual(stages[-1], ('done', 'done'))
            self.assertFalse(any(call.kwargs.get('search') for call in generate.call_args_list))

    def test_extended_techniques_require_exact_quotes(self):
        original = 'They do not want you to know. Buy now!'
        media = {k: v for k, v in unavailable_media('en').items() if k in ('purpose', 'desired_response', 'signals', 'reading_tip')}
        media['signals'] = [{'type': 'conspiracy_appeal', 'label': 'Appeal to hidden knowledge', 'quote': 'They do not want you to know.',
                             'explanation': 'Suggests unspecified people hide information.', 'question': 'Who is being referred to?'}]
        media['signals'].append({**media['signals'][0], 'quote': 'Fabricated quote.'})
        normalized = normalize_media(media, original, 'en')
        result = analysis.enrich_result({'original_text': original, 'statements': [], 'media_literacy': normalized}, {}, 'en')
        self.assertEqual(len(result['techniques']), 1)
        technique = result['techniques'][0]
        self.assertEqual(original[technique['start']:technique['end']], technique['quote'])


if __name__ == '__main__':
    unittest.main()
