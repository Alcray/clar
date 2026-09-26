import json
import unittest
from unittest.mock import patch

import analysis


class VertexAdapterTests(unittest.TestCase):
    @patch('analysis.urllib.request.urlopen')
    def test_provider_endpoint_and_header_credentials(self, urlopen):
        candidate = {'content': {'parts': [{'text': 'Grounded response.'}]}, 'finishReason': 'STOP'}
        urlopen.return_value.__enter__.return_value.read.return_value = json.dumps({'candidates': [candidate]}).encode()
        key = 'fake-test-secret-not-for-production'
        endpoints = {
            'gemini': 'https://generativelanguage.googleapis.com/v1beta/models/gemini-test:generateContent',
            'vertex': 'https://aiplatform.googleapis.com/v1/publishers/google/models/gemini-test:generateContent'
        }
        for provider, expected in endpoints.items():
            with self.subTest(provider=provider):
                result = analysis.generate(key, 'gemini-test', 'Instructions.', [{'text': 'A claim.'}], search=True, provider=provider)
                request = urlopen.call_args.args[0]
                self.assertEqual(request.full_url, expected)
                self.assertNotIn(key, request.full_url)
                self.assertNotIn('?', request.full_url)
                self.assertEqual(request.get_header('X-goog-api-key'), key)
                self.assertEqual(json.loads(request.data)['tools'], [{'google_search': {}}])
                self.assertEqual(result, candidate)

    @patch('analysis.urllib.request.urlopen')
    def test_default_provider_preserves_gemini_and_json_schema(self, urlopen):
        candidate = {'content': {'parts': [{'text': '{"result":"ok"}'}]}, 'finishReason': 'STOP'}
        urlopen.return_value.__enter__.return_value.read.return_value = json.dumps({'candidates': [candidate]}).encode()
        schema = {'type': 'object', 'properties': {'result': {'type': 'string'}}}
        result = analysis.generate('fake-test-key', 'gemini-test', 'Instructions.', [{'text': 'A claim.'}], schema=schema)
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, 'https://generativelanguage.googleapis.com/v1beta/models/gemini-test:generateContent')
        self.assertEqual(json.loads(request.data)['generationConfig']['responseJsonSchema'], schema)
        self.assertEqual(result, {'result': 'ok'})


if __name__ == '__main__':
    unittest.main()
