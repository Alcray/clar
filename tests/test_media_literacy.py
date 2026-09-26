import copy
import json
import threading
import unittest
from unittest.mock import patch

import analysis
import local_analysis
from media_literacy import COPY, MEDIA_SCHEMA, normalize_media, unavailable_media


def response(text='Only today: buy now!'):
    return {
        'purpose': {'category': 'sell', 'explanation': 'The explicit purchase request suggests a sales purpose.',
                    'quote': text},
        'desired_response': {'description': 'The wording invites the reader to buy immediately.', 'quote': text},
        'signals': [{'type': 'urgency', 'label': 'Time pressure', 'quote': text,
                     'explanation': 'The deadline may encourage a quick decision.',
                     'question': 'Can you verify the deadline and compare alternatives?'}],
        'reading_tip': 'Check the offer and price before deciding.',
    }


class MediaValidationTests(unittest.TestCase):
    def test_valid_quotes_preserve_unicode_and_output_is_bounded(self):
        post = 'Doar azi: cumpără acum! Только сегодня!'
        raw = response('Doar azi: cumpără acum!')
        raw['signals'] = [{**raw['signals'][0], 'type': kind}
                          for kind in ('urgency', 'commercial_pressure', 'loaded_framing', 'emotional_language', 'social_proof')]
        raw['score'] = 99
        result = normalize_media(raw, post, 'ro')
        self.assertEqual(result['status'], 'available')
        self.assertEqual(len(result['signals']), 4)
        self.assertNotIn('score', result)
        self.assertEqual(result['purpose']['quote'], 'Doar azi: cumpără acum!')
        self.assertIn('Acestea sunt interpretări', result['limitations'])
        for item in result['signals'] + [result['purpose'], result['desired_response']]:
            self.assertIn(item['quote'], post)

    def test_fabricated_purpose_reaction_and_signals_are_removed(self):
        result = normalize_media(response(), 'The meeting starts at 10.', 'en')
        self.assertEqual(result['status'], 'limited')
        self.assertEqual(result['purpose']['category'], 'unclear')
        self.assertEqual(result['purpose']['quote'], '')
        self.assertEqual(result['desired_response']['quote'], '')
        self.assertEqual(result['desired_response']['description'], COPY['en']['response'])
        self.assertEqual(result['signals'], [])
        self.assertNotIn('purchase', result['purpose']['explanation'])

    def test_rewritten_or_normalized_quotes_do_not_count(self):
        for quote in ('Only today: Buy now!', 'Only today: buy...', 'Only\u00a0today: buy now!', '!'):
            raw = response()
            raw['signals'][0]['quote'] = quote
            with self.subTest(quote=quote):
                result = normalize_media(raw, 'Only today: buy now!', 'en')
                self.assertEqual(result['signals'], [])
                self.assertEqual(result['status'], 'limited')

    def test_neutral_post_can_have_zero_signals_without_being_an_error(self):
        post = 'The meeting starts at 10.'
        raw = response(post)
        raw['purpose']['category'] = 'inform'
        raw['signals'] = []
        raw['desired_response'] = {'description': 'No specific response is apparent.', 'quote': ''}
        result = normalize_media(raw, post, 'en')
        self.assertEqual(result['status'], 'available')
        self.assertEqual(result['signals'], [])
        self.assertIn('no flagged cues does not establish reliability', result['limitations'])

    def test_malformed_payloads_never_raise_or_expose_raw_model_values(self):
        for raw in (None, [], 'invalid', {}, {'purpose': [], 'desired_response': {}, 'signals': []},
                    {'purpose': {}, 'desired_response': {}, 'signals': 'invalid'}):
            with self.subTest(raw=raw):
                result = normalize_media(raw, 'Only today: buy now!', 'en')
                self.assertEqual(result['status'], 'unavailable')
        raw = response()
        raw['purpose']['category'] = ['sell']
        raw['desired_response'] = {'quote': {}, 'description': ['unexpected']}
        raw['reading_tip'] = None
        raw['signals'] = [None, {}, {'type': ['urgency'], 'quote': 'buy now!'}, 'invalid']
        result = normalize_media(raw, 'Only today: buy now!', 'en')
        self.assertEqual(result['status'], 'limited')
        self.assertEqual(result['purpose']['category'], 'unclear')
        self.assertEqual(result['signals'], [])

    def test_unsupported_type_and_duplicate_signal_are_filtered(self):
        raw = response()
        valid = copy.deepcopy(raw['signals'][0])
        raw['signals'].extend([valid, {**valid, 'type': 'brainwashing'}])
        result = normalize_media(raw, 'Only today: buy now!', 'en')
        self.assertEqual(len(result['signals']), 1)
        self.assertEqual(result['status'], 'limited')

    def test_unavailable_copy_and_excerpt_limitations_are_localized(self):
        for language in ('en', 'ro', 'ru'):
            result = unavailable_media(language)
            self.assertEqual(result['purpose']['explanation'], COPY[language]['purpose'])
            self.assertIn(COPY[language]['unavailable'], result['limitations'])
            partial = normalize_media(response(), 'Only today: buy now!', language, excerpt=True)
            self.assertEqual(partial['status'], 'limited')
            self.assertIn(COPY[language]['excerpt'], partial['limitations'])


class MediaPipelineTests(unittest.TestCase):
    @patch('analysis.generate')
    def test_opinion_only_still_gets_media_analysis_without_search(self, generate):
        post = 'Only today: buy now!'
        def answer(*args, **kwargs):
            if kwargs.get('schema') == analysis.EXTRACT_SCHEMA:
                return {'original_text': post, 'statements': [{'text': post, 'kind': 'opinion'}]}
            self.assertEqual(kwargs['schema'], MEDIA_SCHEMA)
            self.assertEqual(json.loads(args[3][0]['text'])['post_text'], post)
            self.assertNotIn('search', kwargs)
            return response(post)
        generate.side_effect = answer
        result = analysis.analyze({'text': post}, 'test-key', 'test-model', provider='vertex')
        self.assertEqual(result['statements'][0]['verdict'], 'not_applicable')
        self.assertEqual(result['media_literacy']['purpose']['category'], 'sell')
        self.assertEqual(generate.call_count, 2)
        self.assertTrue(all(call.kwargs['provider'] == 'vertex' for call in generate.call_args_list))

    @patch('analysis.generate')
    def test_media_failure_preserves_supported_factual_result(self, generate):
        post = 'The record states 101.'
        def answer(*args, **kwargs):
            schema = kwargs.get('schema')
            if schema == analysis.EXTRACT_SCHEMA:
                return {'original_text': post, 'statements': [{'text': post, 'kind': 'factual'}]}
            if schema == MEDIA_SCHEMA:
                raise analysis.AnalysisError('Supplementary request quota exceeded.', 429, 'api_quota')
            if kwargs.get('search'):
                return {'content': {'parts': [{'text': post}]}, 'groundingMetadata': {
                    'groundingChunks': [{'web': {'uri': 'https://example.org/original-record'}}],
                    'groundingSupports': [{'segment': {'text': post}, 'groundingChunkIndices': [0]}]}}
            return {'findings': [{'id': 'C1', 'verdict': 'supported', 'explanation': 'The record matches.',
                                  'evidence_ids': ['C1E1']}]}
        generate.side_effect = answer
        result = analysis.analyze({'text': post}, 'test-key', 'test-model')
        self.assertEqual(result['statements'][0]['verdict'], 'supported')
        self.assertEqual(result['statements'][0]['evidence'][0]['url'], 'https://example.org/original-record')
        self.assertEqual(result['media_literacy']['status'], 'unavailable')
        self.assertNotIn('quota', json.dumps(result['media_literacy']))

    @patch('analysis.generate')
    def test_media_runs_while_factual_research_and_formatting_complete(self, generate):
        post = 'Only today: buy now!'
        formatted = threading.Event()
        overlapped = []
        def answer(*args, **kwargs):
            schema = kwargs.get('schema')
            if schema == analysis.EXTRACT_SCHEMA:
                return {'original_text': post, 'statements': [{'text': post, 'kind': 'factual'}]}
            if schema == MEDIA_SCHEMA:
                overlapped.append(formatted.wait(2))
                return response(post)
            if kwargs.get('search'):
                return {'content': {'parts': [{'text': 'No evidence.'}]}}
            formatted.set()
            return {'findings': []}
        generate.side_effect = answer
        result = analysis.analyze({'text': post}, 'test-key', 'test-model')
        self.assertEqual(overlapped, [True])
        self.assertEqual(result['media_literacy']['status'], 'available')
        self.assertEqual(result['statements'][0]['verdict'], 'insufficient')

    @patch('local_analysis.retrieve_sources')
    @patch('local_analysis.generate_local')
    def test_local_opinion_analysis_uses_sequential_bounded_supplement(self, generate, retrieve):
        post = 'Only today: buy now!'
        generate.side_effect = [{'statements': [{'id': 'C1', 'kind': 'opinion'}]}, response(post)]
        result = local_analysis.analyze_local({'text': post}, 'http://localhost:11434', 'local-test')
        self.assertEqual(result['statements'][0]['verdict'], 'not_applicable')
        self.assertEqual(result['media_literacy']['status'], 'available')
        supplement = generate.call_args_list[1]
        self.assertEqual(supplement.args[4], MEDIA_SCHEMA)
        self.assertEqual(supplement.args[3]['post_text'], post)
        self.assertEqual(supplement.kwargs, {'timeout': 45, 'max_output_tokens': 1100})
        retrieve.assert_not_called()

    @patch('local_analysis.generate_local')
    def test_local_failure_is_isolated_and_long_text_is_explicitly_limited(self, generate):
        generate.side_effect = TimeoutError('internal response with private data')
        self.assertEqual(local_analysis.analyze_local_media('A post.', 'ru', 'http://localhost:11434', 'local-test'),
                         unavailable_media('ru'))
        generate.side_effect = None
        generate.return_value = response()
        post = 'Only today: buy now! ' + 'More context. ' * 300
        result = local_analysis.analyze_local_media(post, 'en', 'http://localhost:11434', 'local-test')
        self.assertEqual(result['status'], 'limited')
        self.assertEqual(len(generate.call_args.args[3]['post_text']), 3000)
        self.assertFalse(generate.call_args.args[3]['complete_post'])
        self.assertIn(COPY['en']['excerpt'], result['limitations'])


if __name__ == '__main__':
    unittest.main()
