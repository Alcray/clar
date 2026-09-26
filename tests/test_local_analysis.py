import base64
import json
import socket
import unittest
from unittest.mock import MagicMock, patch

import local_analysis as local
from media_literacy import unavailable_media


class LocalAnalysisTests(unittest.TestCase):
    def media(self):
        # Supplemental response used only after the existing evidence calls.
        return {key: value for key, value in unavailable_media('en').items()
                if key in ('purpose', 'desired_response', 'signals', 'reading_tip')}

    def source(self, text='On the 27th of August 1991, Republic of Moldova became an independent and sovereign State.'):
        return {**local.SOURCES[0], 'text': text, 'status': 'retrieved', 'retrieved_at': '2026-09-25T00:00:00Z'}

    def extracted(self, text, kind='factual'):
        return {'original_text': text, 'statements': [{'id': 'C1', 'text': text, 'kind': kind, 'context': '',
                'explanation': 'A statement.', 'retrieval_terms': ['independent', 'independență', '1991']}]}

    def test_model_transport_and_schema(self):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps({'message': {'content': '{"findings": []}'}, 'done_reason': 'stop'}).encode()
        with patch('local_analysis.urllib.request.urlopen', return_value=response) as request:
            answer = local.generate_local('http://127.0.0.1:11434', 'qwen3.5:4b', 'system', {'text': 'Știre'}, local.ASSESSMENT_SCHEMA, ['base64image'])
        sent = json.loads(request.call_args.args[0].data)
        self.assertEqual(answer, {'findings': []})
        self.assertEqual(request.call_args.kwargs['timeout'], 180)
        self.assertFalse(sent['stream'])
        self.assertFalse(sent['think'])
        self.assertEqual(sent['format'], local.ASSESSMENT_SCHEMA)
        self.assertEqual(sent['messages'][1]['images'], ['base64image'])
        self.assertEqual(sent['options'], {'num_ctx': 4096, 'num_predict': 1600, 'temperature': 0})

    def test_non_thinking_model_and_output_limit(self):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps({'message': {'content': '{}'}, 'done_reason': 'length'}).encode()
        with patch('local_analysis.urllib.request.urlopen', return_value=response) as request:
            with self.assertRaises(local.AnalysisError) as error:
                local.generate_local('http://localhost:11434', 'qwen2.5vl:3b', 'system', {}, {})
        self.assertNotIn('think', json.loads(request.call_args.args[0].data))
        self.assertEqual(error.exception.code, 'incomplete_output')

    def test_source_allowlist_rejects_post_url_before_dns(self):
        with patch('local_analysis.socket.getaddrinfo') as dns:
            for url in ('http://127.0.0.1/admin', 'https://example.org/', local.SOURCES[0]['url'] + '?redirect=127.0.0.1'):
                with self.assertRaises(ValueError):
                    local._check_source_url(url)
        dns.assert_not_called()

    def test_source_dns_cannot_point_at_private_address(self):
        for address in ('127.0.0.1', '10.0.0.3', '169.254.169.254', '::1'):
            with patch('local_analysis.socket.getaddrinfo', return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, '', (address, 443))]):
                with self.assertRaises(ValueError):
                    local._check_source_url(local.SOURCES[0]['url'])

    def test_unapproved_redirect_is_rejected(self):
        with self.assertRaises(ValueError):
            local._SourceRedirect().redirect_request(None, None, 302, '', {}, 'http://127.0.0.1/admin')

    def test_parser_excludes_navigation_and_scripts(self):
        parser = local._PageText('field-name-body')
        parser.feed('<nav>Fake claim.</nav><div class="field-name-body"><div><p>Verified <b>text</b>.</p><script>fake()</script></div></div><footer>Footer.</footer>')
        self.assertEqual(' '.join(''.join(parser.pieces).split()), 'Verified text.')

    def test_missing_pdf_dependency_is_explicit(self):
        with patch('local_analysis.shutil.which', return_value=None), patch.dict('sys.modules', {'pypdf': None}):
            with self.assertRaisesRegex(ValueError, 'PDF extraction unavailable'):
                local._pdf_text(b'%PDF-1.4')

    def test_real_citation_is_server_owned_and_exact(self):
        quote = self.source()['text']
        statements = local.normalize_statements(self.extracted('Moldova became independent in 1991.'), 'Moldova became independent in 1991.')
        passages = {'C1': [{'id': 'C1P1', 'text': quote, 'source': self.source()}]}
        formatted = {'findings': [{'id': 'C1', 'verdict': 'supported', 'explanation': 'Matches the historical date.',
                                  'citations': [{'passage_id': 'C1P1', 'quote': quote, 'url': 'https://fabricated.invalid'}]}]}
        local.apply_local_findings(statements, formatted, passages, 'en')
        self.assertEqual(statements[0]['verdict'], 'supported')
        self.assertEqual(statements[0]['evidence'][0]['url'], local.SOURCES[0]['url'])
        self.assertEqual(statements[0]['evidence'][0]['finding'], quote)

    def test_invented_quote_and_cross_claim_citation_cannot_set_verdict(self):
        for citation in ({'passage_id': 'C1P1', 'quote': 'The model made up this unsupported quote.'},
                         {'passage_id': 'C2P1', 'quote': self.source()['text']},
                         {'passage_id': ['C1P1'], 'quote': self.source()['text']}):
            statements = local.normalize_statements(self.extracted('A factual allegation.'), 'A factual allegation.')
            formatted = {'findings': [{'id': 'C1', 'verdict': 'supported', 'explanation': 'Definitely established.', 'citations': [citation]}]}
            local.apply_local_findings(statements, formatted, {'C1': [{'id': 'C1P1', 'text': self.source()['text'], 'source': self.source()}]}, 'en')
            self.assertEqual(statements[0]['verdict'], 'insufficient')
            self.assertEqual(statements[0]['evidence'], [])
            self.assertNotIn('Definitely', statements[0]['explanation'])

    def test_insufficient_never_preserves_decisive_model_explanation(self):
        statements = local.normalize_statements(self.extracted('An uncertain allegation.'), 'An uncertain allegation.')
        passages = {'C1': [{'id': 'C1P1', 'text': self.source()['text'], 'source': self.source()}]}
        formatted = {'findings': [{'id': 'C1', 'verdict': 'insufficient', 'explanation': 'The allegation is confirmed.',
                                  'citations': [{'passage_id': 'C1P1', 'quote': self.source()['text']}]}]}
        local.apply_local_findings(statements, formatted, passages, 'en')
        self.assertEqual(statements[0]['explanation'], local.UNRESOLVED['en'])
        self.assertEqual(len(statements[0]['evidence']), 1)

    def test_supported_numbers_require_quote_coverage(self):
        text = 'Independence occurred in 1992.'
        statements = local.normalize_statements(self.extracted(text), text)
        formatted = {'findings': [{'id': 'C1', 'verdict': 'supported', 'explanation': 'Confirmed.',
                                  'citations': [{'passage_id': 'C1P1', 'quote': self.source()['text']}]}]}
        passages = {'C1': [{'id': 'C1P1', 'text': self.source()['text'], 'source': self.source()}]}
        local.apply_local_findings(statements, formatted, passages, 'en')
        self.assertEqual(statements[0]['verdict'], 'insufficient')
        self.assertEqual(statements[0]['explanation'], local.UNRESOLVED['en'])

    def test_owned_spans_keep_unicode_year_sentences_and_remainder(self):
        text = 'Moldova a devenit independentă în 1991. Парламент состоит из 150 депутатов. Îmi place asta!'
        spans = local.sentence_spans(text)
        self.assertEqual(len(spans), 3)
        self.assertEqual(spans[0]['text'], 'Moldova a devenit independentă în 1991.')
        self.assertEqual(spans[1]['text'], 'Парламент состоит из 150 депутатов.')
        for span in spans:
            self.assertIn(span['text'], text)
        long_post = 'One sentence. ' * 8
        long_spans = local.sentence_spans(long_post)
        self.assertEqual(len(long_spans), 6)
        self.assertEqual(' '.join(item['text'] for item in long_spans), long_post.strip())

    def test_missing_ids_and_invalid_kinds_are_retained_as_unclear(self):
        spans = local.sentence_spans('Primul enunț. Второе утверждение. Third sentence.')
        reply = {'statements': [{'id': 'C2', 'kind': 'made-up-kind'}, {'id': 'C3', 'kind': 'opinion', 'text': 'Model rewrote this.'}]}
        statements, _ = local.classify_spans(spans, reply, 'ro')
        self.assertEqual([item['kind'] for item in statements], ['unclear', 'unclear', 'opinion'])
        self.assertEqual([item['text'] for item in statements], [item['text'] for item in spans])

    def test_literal_claim_outweighs_bad_expansions_in_article_retrieval(self):
        source = self.source('Bibliografie Legea nr. 52 din 16.03.23, MO97-99 art.150. '
                             'NOI reprezentanții poporului și deputați în Parlament declarăm dreptatea și libertatea. '
                             'Articolul 59 Avocatul Poporului este numit de Parlament pentru apărarea drepturilor. '
                             'Articolul 60 Parlamentul, organ reprezentativ suprem şi legislativ. '
                             '(1) Parlamentul este organul reprezentativ suprem al poporului. '
                             '(2) Parlamentul este compus din 101 deputaţi. '
                             'Articolul 61 Parlamentul este ales prin vot universal, egal, direct, secret și liber exprimat. '
                             'Articolul 62 Deputații reprezintă poporul în exercitarea mandatului lor.')
        source['id'] = 'S2'
        misleading_terms = ['poporului', 'reprezentanții', 'dreptate', 'libertate', 'avocatul', 'drepturilor']
        selected = local.select_passages({'id': 'C1', 'text': 'Parlamentul are 150 de deputați.'}, [source], misleading_terms)
        self.assertIn('Articolul 60', selected[0]['text'])
        self.assertIn('101 deputaţi', selected[0]['text'])

    @patch('local_analysis.retrieve_sources')
    @patch('local_analysis.generate_local')
    def test_empty_model_classification_still_returns_every_original_sentence(self, generate, retrieve):
        text = 'Prima afirmație. Второе утверждение. I prefer transparency.'
        generate.return_value = {'statements': []}
        result = local.analyze_local({'text': text}, 'http://localhost:11434', 'local')
        self.assertEqual(len(result['statements']), 3)
        self.assertTrue(all(item['kind'] == 'unclear' for item in result['statements']))
        self.assertEqual(' '.join(item['text'] for item in result['statements']), text)
        retrieve.assert_not_called()

    @patch('local_analysis.retrieve_sources')
    @patch('local_analysis.generate_local')
    def test_source_failure_remains_unresolved_without_formatter(self, generate, retrieve):
        text = 'В Молдове вчера произошло важное событие.'
        generate.return_value = self.extracted(text)
        retrieve.return_value = [{**local.SOURCES[0], 'status': 'unavailable', 'error': 'TLS verification failed.'}]
        result = local.analyze_local({'text': text, 'language': 'ru'}, 'http://localhost:11434', 'local')
        self.assertEqual(generate.call_count, 2)
        self.assertEqual(result['original_text'], text)
        self.assertEqual(result['statements'][0]['text'], text)
        self.assertEqual(result['statements'][0]['verdict'], 'insufficient')
        self.assertEqual(result['mode'], 'local')
        self.assertFalse(result['coverage']['web_search'])
        self.assertEqual(result['queries'], [])
        self.assertNotIn('text', result['coverage']['sources'][0])
        self.assertIn('0/1', result['notice'])

    @patch('local_analysis.retrieve_sources')
    @patch('local_analysis.generate_local')
    def test_pipeline_checks_arbitrary_romanian_text(self, generate, retrieve):
        text = 'Republica Moldova a devenit independentă în 1991.'
        quote = self.source()['text']
        generate.side_effect = [self.extracted(text), {'findings': [{'id': 'C1', 'verdict': 'supported',
                               'explanation': 'Sursa indică anul 1991.', 'citations': [{'passage_id': 'C1P1', 'quote': quote}]}]}, self.media()]
        retrieve.return_value = [self.source()]
        result = local.analyze_local({'text': text, 'language': 'ro'}, 'http://localhost:11434', 'local')
        self.assertEqual(generate.call_count, 3)
        self.assertEqual(result['statements'][0]['text'], text)
        self.assertEqual(result['statements'][0]['verdict'], 'supported')
        assessment_payload = generate.call_args_list[1].args[3]
        self.assertEqual(assessment_payload['post_date'], 'unknown')
        self.assertIn('passages', assessment_payload)
        self.assertEqual(assessment_payload['claim'], text)
        self.assertNotIn('https://', json.dumps(assessment_payload))
        extraction_payload = generate.call_args_list[0].args[3]
        self.assertEqual(extraction_payload['sentences'], [{'id': 'C1', 'text': text}])
        self.assertNotIn('original_text', generate.call_args_list[0].args[4]['properties'])

    @patch('local_analysis.retrieve_sources')
    @patch('local_analysis.generate_local')
    def test_factual_claims_are_verified_in_separate_calls(self, generate, retrieve):
        text = 'Moldova became independent in 1991. Moldova became sovereign in 1991.'
        classifications = {'statements': [dict(self.extracted('')['statements'][0], id='C1'),
                                          dict(self.extracted('')['statements'][0], id='C2')]}
        quote = self.source()['text']
        generate.side_effect = [classifications] + [{'findings': [{'id': ident, 'verdict': 'supported',
                               'explanation': 'The cited date matches.',
                               'citations': [{'passage_id': ident + 'P1', 'quote': quote}]}]} for ident in ('C1', 'C2')] + [self.media()]
        retrieve.return_value = [self.source()]
        result = local.analyze_local({'text': text}, 'http://localhost:11434', 'local')
        self.assertEqual(generate.call_count, 4)
        for index, ident in ((1, 'C1'), (2, 'C2')):
            payload = generate.call_args_list[index].args[3]
            self.assertEqual(payload['id'], ident)
            self.assertNotIn('claims', payload)
            self.assertTrue(all(passage['passage_id'].startswith(ident) for passage in payload['passages']))
        self.assertEqual([statement['verdict'] for statement in result['statements']], ['supported', 'supported'])

    @patch('local_analysis.retrieve_sources')
    @patch('local_analysis.generate_local')
    def test_opinion_and_screenshot_require_no_evidence_fetch(self, generate, retrieve):
        text = 'Îmi place orașul Chișinău.'
        generate.return_value = self.extracted(text, 'opinion')
        encoded = base64.b64encode(b'\x89PNG\r\n\x1a\n' + b'image-test').decode()
        result = local.analyze_local({'image': {'mime_type': 'image/png', 'data': encoded}}, 'http://localhost:11434', 'local')
        self.assertEqual(generate.call_args_list[0].args[5], [encoded])
        self.assertEqual(generate.call_count, 3)
        self.assertEqual(result['original_text'], text)
        self.assertEqual(result['statements'][0]['verdict'], 'not_applicable')
        retrieve.assert_not_called()

    @patch('local_analysis.retrieve_sources')
    @patch('local_analysis.generate_local')
    def test_only_three_factual_claims_researched(self, generate, retrieve):
        text = 'First assertion. Second assertion. Third assertion. Fourth assertion.'
        extracted = {'original_text': text, 'statements': [self.extracted(part)['statements'][0] for part in text.split('. ') if part]}
        for index, item in enumerate(extracted['statements']):
            item['id'] = 'C{}'.format(index + 1)
        generate.return_value = extracted
        retrieve.return_value = []
        result = local.analyze_local({'text': text}, 'http://localhost:11434', 'local')
        self.assertEqual(len(result['statements']), 4)
        self.assertEqual(result['statements'][3]['explanation'], local.NOT_CHECKED['en'])


if __name__ == '__main__':
    unittest.main()
