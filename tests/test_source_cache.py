import concurrent.futures
import threading
import unittest
from unittest.mock import patch

import local_analysis as local


class SourceCacheTests(unittest.TestCase):
    def setUp(self):
        self.source = dict(local.SOURCES[0])
        self.document = {
            **self.source,
            'status': 'retrieved',
            'text': 'Official public document text.',
            'retrieved_at': '2026-09-25T12:00:00Z',
            'metadata': {'edition': 'original'},
        }
        self.enterContext(patch.dict(local._SOURCE_CACHE, {}, clear=True))
        self.enterContext(patch.object(local, 'SOURCES', (self.source,)))
        self.clock = self.enterContext(patch('local_analysis.time.monotonic', return_value=1000))
        self.fetch = self.enterContext(patch('local_analysis.fetch_source', return_value=self.document))

    def test_success_reused_until_ten_minutes_with_original_retrieval_time(self):
        first = local.retrieve_sources()[0]
        self.clock.return_value = 1599.99
        cached = local.retrieve_sources()[0]
        self.fetch.assert_called_once_with(self.source)
        self.assertEqual(cached, first)
        self.assertEqual(cached['retrieved_at'], '2026-09-25T12:00:00Z')

        self.clock.return_value = 1600
        self.fetch.return_value = {**self.document, 'retrieved_at': '2026-09-25T12:10:00Z'}
        refreshed = local.retrieve_sources()[0]
        self.assertEqual(self.fetch.call_count, 2)
        self.assertEqual(refreshed['retrieved_at'], '2026-09-25T12:10:00Z')

    def test_failed_fetch_retried_after_thirty_seconds(self):
        self.fetch.return_value = {**self.source, 'status': 'unavailable', 'error': 'Connection failed.'}
        first = local.retrieve_sources()[0]
        self.clock.return_value = 1029.99
        self.assertEqual(local.retrieve_sources()[0], first)
        self.fetch.assert_called_once_with(self.source)

        self.clock.return_value = 1030
        self.fetch.return_value = self.document
        self.assertEqual(local.retrieve_sources()[0]['status'], 'retrieved')
        self.assertEqual(self.fetch.call_count, 2)
        self.clock.return_value = 1060
        self.assertEqual(local.retrieve_sources()[0]['status'], 'retrieved')
        self.assertEqual(self.fetch.call_count, 2)

    def test_returned_documents_and_fetch_results_cannot_mutate_cache(self):
        first = local.retrieve_sources()[0]
        first['text'] = 'Changed by a caller.'
        first['metadata']['edition'] = 'Changed by a caller.'
        self.document['metadata']['edition'] = 'Changed by the fetch provider.'

        cached = local.retrieve_sources()[0]
        self.assertEqual(cached['text'], 'Official public document text.')
        self.assertEqual(cached['metadata']['edition'], 'original')
        cached['metadata']['edition'] = 'Changed after a cache hit.'
        self.assertEqual(local.retrieve_sources()[0]['metadata']['edition'], 'original')
        self.fetch.assert_called_once_with(self.source)

    def test_concurrent_checks_share_one_fetch(self):
        fetch_started = threading.Event()
        release_fetch = threading.Event()

        def fetch(source):
            fetch_started.set()
            if not release_fetch.wait(timeout=3):
                raise AssertionError('Test did not release the source fetch.')
            return self.document

        self.fetch.side_effect = fetch
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            pending = [executor.submit(local.retrieve_sources) for _ in range(4)]
            try:
                self.assertTrue(fetch_started.wait(timeout=3))
            finally:
                release_fetch.set()
            results = [future.result(timeout=3)[0] for future in pending]

        self.fetch.assert_called_once_with(self.source)
        self.assertTrue(all(result == self.document for result in results))
        self.assertEqual(len({id(result) for result in results}), 4)


if __name__ == '__main__':
    unittest.main()
