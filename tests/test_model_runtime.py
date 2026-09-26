import json
import os
import unittest
from unittest.mock import patch

from analysis import AnalysisError
from model_runtime import ModelConfig, call_model, config_from_env
import pipeline_runtime


SCHEMA = {'type': 'object', 'properties': {'answer': {'type': 'string'}}, 'required': ['answer']}


class RuntimeTests(unittest.TestCase):
    def test_config_redacts_keys_and_rejects_credential_urls(self):
        config = ModelConfig('vertex', 'test', api_key='private-fixture-credential')
        self.assertNotIn('private-fixture', repr(config))
        self.assertNotIn('api_key', config.public_dict())
        for endpoint in ('http://user:password@localhost:8000/v1', 'https://host/v1?key=secret', 'file:///tmp/model'):
            with self.assertRaises(ValueError):
                ModelConfig('openai', 'test', endpoint=endpoint)

    @patch('model_runtime._post')
    def test_google_thinking_usage_and_json_are_measured(self, post):
        post.return_value = {'modelVersion': 'returned-model-version', 'usageMetadata': {
            'promptTokenCount': 12, 'candidatesTokenCount': 8, 'thoughtsTokenCount': 0},
            'candidates': [{'finishReason': 'STOP', 'content': {'parts': [{'text': '{"answer":"ok"}'}]}}]}
        telemetry = {}
        config = ModelConfig('vertex', 'gemini-example', thinking='minimal', api_key='fake-key')
        self.assertEqual(call_model(config, 'Instruction', [{'text': 'Synthetic'}], schema=SCHEMA, telemetry=telemetry), {'answer': 'ok'})
        url, body, headers, timeout = post.call_args.args
        self.assertNotIn('fake-key', url)
        self.assertEqual(body['generationConfig']['thinkingConfig']['thinkingLevel'], 'MINIMAL')
        self.assertEqual(headers['x-goog-api-key'], 'fake-key')
        self.assertEqual(telemetry['requests'], 1)
        self.assertEqual(telemetry['input_tokens'], 12)
        self.assertIsNone(telemetry['cached_input_tokens'])
        self.assertNotIn('fake-key', json.dumps(telemetry))

    @patch('model_runtime._post')
    def test_fixed_track_does_not_retry_invalid_json(self, post):
        post.return_value = {'candidates': [{'content': {'parts': [{'text': 'not json'}]}}]}
        telemetry = {}
        with self.assertRaises(AnalysisError) as failed:
            call_model(ModelConfig('gemini', 'test', api_key='fake'), 'Read', [{'text': 'Data'}], schema=SCHEMA, telemetry=telemetry)
        self.assertEqual(failed.exception.code, 'invalid_output')
        self.assertEqual(post.call_count, 1)
        self.assertEqual(telemetry['calls'][0]['status'], 'error')

    @patch('model_runtime._post')
    def test_ollama_omits_unsupported_thinking_by_default(self, post):
        post.return_value = {'done': True, 'message': {'content': '{"answer":"ok"}'},
                             'prompt_eval_count': 5, 'eval_count': 4, 'load_duration': 1000000}
        telemetry = {}
        call_model(ModelConfig('ollama', 'qwen2.5vl:3b'), 'Read', [{'text': 'Data'}], schema=SCHEMA, telemetry=telemetry)
        body = post.call_args.args[1]
        self.assertNotIn('think', body)
        self.assertFalse(body['stream'])
        self.assertEqual(body['format'], SCHEMA)
        self.assertEqual(telemetry['calls'][0]['load_seconds'], .001)
        with self.assertRaises(AnalysisError):
            call_model(ModelConfig('ollama', 'test'), 'Read', [], search=True)

    @patch('model_runtime._post')
    def test_openai_compatible_vision_and_schema(self, post):
        post.return_value = {'choices': [{'finish_reason': 'stop', 'message': {'content': '{"answer":"ok"}'}}]}
        call_model(ModelConfig('openai', 'served-model', endpoint='http://localhost:8000/v1'), 'Read',
                   [{'text': 'Data'}, {'inlineData': {'mimeType': 'image/jpeg', 'data': 'abc'}}], schema=SCHEMA)
        url, body, _, _ = post.call_args.args
        self.assertEqual(url, 'http://localhost:8000/v1/chat/completions')
        self.assertEqual(body['messages'][1]['content'][1]['image_url']['url'], 'data:image/jpeg;base64,abc')
        self.assertEqual(body['response_format']['json_schema']['schema'], SCHEMA)

    @patch.dict(os.environ, {'DEFAULT_PROVIDER': 'local', 'LOCAL_PROVIDER': 'openai', 'LOCAL_MODEL': 'local-test',
                             'LOCAL_API_BASE_URL': 'http://localhost:9000/v1'}, clear=True)
    def test_local_provider_configuration(self):
        config = config_from_env()
        self.assertEqual((config.provider, config.model, config.endpoint), ('openai', 'local-test', 'http://localhost:9000/v1'))

    @patch('pipeline_runtime.call_model')
    def test_pipeline_retry_has_per_request_config_without_global_mutation(self, call):
        call.side_effect = [AnalysisError('Invalid', 502, 'invalid_output'), {'answer': 'ok'}, {'answer': 'other'}]
        first = ModelConfig('vertex', 'model-one', thinking='minimal')
        second = ModelConfig('ollama', 'model-two')
        one = pipeline_runtime._cloud_caller(first, {})
        two = pipeline_runtime._local_caller(second, {}, 'image/webp')
        self.assertEqual(one('', '', 'Read', [], schema=SCHEMA), {'answer': 'ok'})
        self.assertEqual(two('', '', 'Read', {}, SCHEMA, ['abc']), {'answer': 'other'})
        self.assertEqual([c.args[0].model for c in call.call_args_list], ['model-one', 'model-one', 'model-two'])
        self.assertEqual(call.call_args.args[2][1]['inlineData']['mimeType'], 'image/webp')

    @patch('pipeline_runtime.local_analysis.analyze_local')
    def test_live_no_cache_injects_uncached_retrieval(self, analyze):
        analyze.return_value = {}
        pipeline_runtime.analyze_with_config({'text': 'A post'}, ModelConfig('ollama', 'test'), use_cache=False)
        self.assertIs(analyze.call_args.kwargs['retrieve_fn'], pipeline_runtime._uncached_sources)


if __name__ == '__main__':
    unittest.main()
