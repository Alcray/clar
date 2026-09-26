import json
import unittest
from unittest.mock import patch
import analysis
from media_literacy import MEDIA_SCHEMA


class GroundingTests(unittest.TestCase):
    def candidate(self, text='Dovadă: șapte deputați.', url='https://example.org/document'):
        return {'content': {'parts': [{'text': text}]}, 'groundingMetadata': {
            'groundingChunks': [{'web': {'uri': url, 'title': 'Document'}}],
            'groundingSupports': [{'segment': {'startIndex': 0, 'endIndex': len(text.encode()), 'text': text}, 'groundingChunkIndices': [0]}]
        }}

    def test_unicode_byte_offsets_and_specific_parts(self):
        c = self.candidate()
        c['content']['parts'].insert(0, {'thought': True, 'text': 'hidden'})
        c['groundingMetadata']['groundingSupports'][0]['segment']['partIndex'] = 1
        evidence = analysis.extract_grounding(c, 'C2')['sources']
        self.assertEqual(evidence[0]['id'], 'C2E1')
        self.assertEqual(evidence[0]['finding'], 'Dovadă: șapte deputați.')

    def test_unattributed_chunks_are_not_evidence(self):
        c = self.candidate()
        c['groundingMetadata']['groundingSupports'] = []
        self.assertEqual(analysis.extract_grounding(c, 'C1')['sources'], [])

    def test_fabricated_urls_and_invalid_chunks_rejected(self):
        c = self.candidate(url='javascript:alert(1)')
        self.assertEqual(analysis.extract_grounding(c, 'C1')['sources'], [])
        c = self.candidate()
        c['groundingMetadata']['groundingSupports'][0]['groundingChunkIndices'] = [-1, 400]
        self.assertEqual(analysis.extract_grounding(c, 'C1')['sources'], [])

    def test_later_supported_core_assertion_is_preserved_for_the_same_url(self):
        first = 'Comisia s-a întrunit la Chișinău.'
        second = 'Comisia a aprobat măsuri pentru continuitatea aprovizionării cu energie electrică și gaze.'
        full = first + '\n' + second
        candidate = self.candidate(full, 'https://gov.md/announcement')
        supports = [
            {'segment': {'startIndex': 0, 'endIndex': len(first.encode()), 'text': first}, 'groundingChunkIndices': [0]},
            {'segment': {'startIndex': len((first + '\n').encode()), 'endIndex': len(full.encode()), 'text': second}, 'groundingChunkIndices': [0]},
        ]
        candidate['groundingMetadata']['groundingSupports'] = supports + [supports[1]]
        sources = analysis.extract_grounding(candidate, 'C1')['sources']
        self.assertEqual(len(sources), 1)
        self.assertEqual(sources[0]['finding'], full)
        self.assertEqual(sources[0]['id'], 'C1E1')

    def test_aggregation_rejects_bad_offsets_fake_quotes_and_unattributed_text(self):
        full = 'Ședință publică. Măsurile au fost aprobate.'
        candidate = self.candidate(full)
        valid = {'segment': {'text': 'Ședință publică.'}, 'groundingChunkIndices': [0]}
        bad = [
            {'segment': {'startIndex': 1, 'endIndex': 3, 'text': ''}, 'groundingChunkIndices': [0]},
            {'segment': {'startIndex': -1, 'endIndex': 10, 'text': 'Măsurile au fost aprobate.'}, 'groundingChunkIndices': [0]},
            {'segment': {'startIndex': 0, 'endIndex': len(full.encode()), 'text': 'Invented claim.'}, 'groundingChunkIndices': [0]},
            {'segment': {'text': 'Măsurile au fost aprobate.'}, 'groundingChunkIndices': [42]},
        ]
        candidate['groundingMetadata']['groundingSupports'] = [valid] + bad
        self.assertEqual(analysis.extract_grounding(candidate, 'C1')['sources'][0]['finding'], 'Ședință publică.')

    def test_aggregated_evidence_has_bounded_segment_and_character_budgets(self):
        parts = ['Finding {}: '.format(i) + 'x' * 900 for i in range(12)]
        candidate = self.candidate('\n'.join(parts))
        candidate['groundingMetadata']['groundingSupports'] = [
            {'segment': {'text': text}, 'groundingChunkIndices': [0]} for text in parts]
        source = analysis.extract_grounding(candidate, 'C1')['sources'][0]
        self.assertLessEqual(len(source['finding']), 3600)
        self.assertTrue(source['finding_truncated'])
        candidate['content']['parts'][0]['text'] = '\n'.join(str(i) for i in range(12))
        candidate['groundingMetadata']['groundingSupports'] = [
            {'segment': {'text': str(i)}, 'groundingChunkIndices': [0]} for i in range(12)]
        source = analysis.extract_grounding(candidate, 'C1')['sources'][0]
        self.assertEqual(source['finding'].split('\n'), [str(i) for i in range(8)])

    def test_citation_cannot_cross_claim_boundaries(self):
        statements = [{'id': 'C1', 'kind': 'factual', 'text': 'A', 'verdict': 'insufficient', 'evidence': []}]
        researches = {'C1': {'sources': [{'id': 'C1E1', 'url': 'https://example.org'}]}}
        fabricated = {'findings': [{'id': 'C1', 'verdict': 'supported', 'explanation': 'Definitely true', 'evidence_ids': ['C2E1', 'https://invented.example']}]}
        analysis.apply_findings(statements, fabricated, researches, 'en')
        self.assertEqual(statements[0]['verdict'], 'insufficient')
        self.assertEqual(statements[0]['evidence'], [])
        self.assertNotIn('Definitely', statements[0]['explanation'])

    def test_claim_must_be_an_exact_original_span(self):
        with self.assertRaises(analysis.AnalysisError):
            analysis.normalize_statements({'statements': [{'text': 'Invented allegation', 'kind': 'factual'}]}, 'A different post')

    def test_reject_wrong_file_signature_and_two_inputs(self):
        with self.assertRaises(analysis.AnalysisError):
            analysis.validated_input({'image': {'mime_type': 'image/png', 'data': 'aGVsbG8='}})
        with self.assertRaises(analysis.AnalysisError):
            analysis.validated_input({'text': 'one', 'image': {'mime_type': 'video/mp4', 'data': 'AA=='}})

    @patch('analysis.generate')
    def test_complete_pipeline_no_evidence_cannot_become_supported(self, generate):
        def response(*args, **kwargs):
            if kwargs.get('schema') == analysis.EXTRACT_SCHEMA:
                return {'original_text': 'Uncertain claim.', 'statements': [{'text': 'Uncertain claim.', 'kind': 'factual', 'context': '', 'explanation': ''}]}
            if kwargs.get('schema') == MEDIA_SCHEMA:
                raise analysis.AnalysisError('Supplementary request failed.')
            if kwargs.get('search'):
                return {'content': {'parts': [{'text': 'No reliable evidence located.'}]}, 'groundingMetadata': {'groundingChunks': [{'web': {'uri': 'https://irrelevant.org'}}]}}
            return {'summary': 'Everything true', 'overview': 'Definitely supported', 'findings': [{'id': 'C1', 'verdict': 'supported', 'explanation': 'True.', 'evidence_ids': ['C1E1']}]}
        generate.side_effect = response
        result = analysis.analyze({'text': 'Uncertain claim.'}, 'test-key', 'test-model')
        self.assertEqual(result['statements'][0]['verdict'], 'insufficient')
        self.assertNotIn('Everything true', result['summary'])
        self.assertEqual(result['statements'][0]['evidence'], [])
        self.assertEqual(result['mode'], 'live')
        formatter = next(call for call in generate.call_args_list if call.kwargs.get('schema') == analysis.FORMAT_SCHEMA)
        formatter_payload = json.loads(formatter.args[3][0]['text'])
        self.assertNotIn('research', formatter_payload['research']['C1'])
        self.assertEqual(formatter_payload['research']['C1']['evidence'], [])
        self.assertEqual(result['media_literacy']['status'], 'unavailable')

    @patch('analysis.generate')
    def test_opinion_only_needs_no_search(self, generate):
        generate.return_value = {'original_text': 'I prefer transparency.', 'statements': [{'text': 'I prefer transparency.', 'kind': 'opinion', 'explanation': 'A preference.', 'context': ''}]}
        result = analysis.analyze({'text': 'I prefer transparency.'}, 'test-key', 'test-model')
        self.assertEqual(generate.call_count, 2)
        self.assertFalse(any(call.kwargs.get('search') for call in generate.call_args_list))
        self.assertEqual(result['queries'], [])
        self.assertEqual(result['statements'][0]['verdict'], 'not_applicable')

    def test_missing_post_date_stays_unknown(self):
        _, _, date, parts = analysis.validated_input({'text': 'Yesterday this happened.'})
        self.assertEqual(date, '')
        self.assertEqual(json.loads(parts[0]['text'])['post_date'], 'unknown')


if __name__ == '__main__':
    unittest.main()
