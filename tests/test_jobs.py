"""Concurrent jobs: ownership, cancellation, progress, dedupe and error privacy."""
import concurrent.futures
import json
import threading
import unittest
from unittest.mock import Mock, patch

from analysis import AnalysisError
from jobs import JobError, JobManager


class JobManagerTests(unittest.TestCase):
    def setUp(self):
        self.manager = JobManager(workers=2)
        self.addCleanup(self.manager.executor.shutdown, wait=True)
        self.release = threading.Event()
        self.addCleanup(self.release.set)

    def waiting_runner(self, started=None):
        def run(progress):
            progress('reading', 'running')
            if started:
                started.set()
            self.release.wait(3)
            progress('reading', 'done')
            return {'analysis': 'finished'}
        return run

    def finish(self, view):
        self.manager.jobs[view['job_id']]['future'].result(timeout=3)
        return self.manager.get(view['job_id'], 'alice')

    def test_concurrent_retries_reserve_quota_once_and_return_same_job(self):
        reserve = Mock()
        barrier = threading.Barrier(8)
        def create(_):
            barrier.wait(2)
            return self.manager.create('alice', {'text': 'one post', 'language': 'ro'}, self.waiting_runner(), reserve)
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            replies = list(executor.map(create, range(8)))
        self.assertEqual(len({view['job_id'] for view, _ in replies}), 1)
        self.assertEqual(sum(not reused for _, reused in replies), 1)
        reserve.assert_called_once()
        self.release.set()
        complete = self.finish(replies[0][0])
        reused, is_reused = self.manager.create('alice', {'language': 'ro', 'text': 'one post'}, self.waiting_runner(), reserve)
        self.assertEqual(reused['job_id'], complete['job_id'])
        self.assertTrue(is_reused)
        reserve.assert_called_once()
        forced, is_reused = self.manager.create('alice', {'text': 'one post', 'language': 'ro'}, self.waiting_runner(), reserve, force=True)
        self.assertFalse(is_reused)
        self.assertNotEqual(forced['job_id'], complete['job_id'])
        self.assertEqual(reserve.call_count, 2)

    def test_owner_isolation_and_payload_dimensions(self):
        first, _ = self.manager.create('alice', {'text': 'private post', 'task': 'analyze'}, self.waiting_runner())
        second, reused = self.manager.create('bob', {'text': 'private post', 'task': 'analyze'}, self.waiting_runner())
        self.assertFalse(reused)
        self.assertNotEqual(first['job_id'], second['job_id'])
        for action in (self.manager.get, self.manager.cancel):
            with self.assertRaises(JobError) as error:
                action(first['job_id'], 'bob')
            self.assertEqual(error.exception.status, 404)
        third, reused = self.manager.create('alice', {'text': 'private post', 'task': 'precheck'}, self.waiting_runner())
        self.assertFalse(reused)
        self.assertNotEqual(first['job_id'], third['job_id'])
        visible = json.dumps(self.manager.get(first['job_id'], 'alice'))
        self.assertNotIn('private post', visible)
        self.assertNotIn('fingerprint', visible)
        self.assertNotIn('alice', visible)

    def test_retry_joins_active_reanalysis_before_old_completed_result(self):
        reserve = Mock()
        initial, _ = self.manager.create('alice', {'text': 'same post'}, lambda progress: {'revision': 1}, reserve)
        self.finish(initial)
        started = threading.Event()
        def reanalyse(progress):
            started.set()
            self.release.wait(3)
            return {'revision': 2}
        fresh, _ = self.manager.create('alice', {'text': 'same post'}, reanalyse, reserve, force=True)
        self.assertTrue(started.wait(2))
        retried, reused = self.manager.create('alice', {'text': 'same post'}, reanalyse, reserve)
        self.assertTrue(reused)
        self.assertEqual(retried['job_id'], fresh['job_id'])
        self.assertNotEqual(retried['job_id'], initial['job_id'])
        self.assertEqual(reserve.call_count, 2)
        self.release.set()
        self.finish(fresh)
        newest, reused = self.manager.create('alice', {'text': 'same post'}, reanalyse, reserve)
        self.assertTrue(reused)
        self.assertEqual(newest['result'], {'revision': 2})
        self.assertEqual(newest['job_id'], fresh['job_id'])
        self.assertEqual(reserve.call_count, 2)

    def test_real_progress_is_visible_and_invalid_stages_are_ignored(self):
        started = threading.Event()
        def run(progress):
            progress('reading', 'done')
            progress('origin', 'done')
            progress('sources', 'running')
            progress('factchecks', 'skipped')
            progress('invented', 'done')
            progress('formatting', 'made-up')
            started.set()
            self.release.wait(3)
            progress('sources', 'done')
            progress('formatting', 'done')
            return {'ok': True}
        view, _ = self.manager.create('alice', {}, run)
        self.assertTrue(started.wait(2))
        current = self.manager.get(view['job_id'], 'alice')
        stages = {s['id']: s['state'] for s in current['progress']['stages']}
        self.assertEqual(stages['sources'], 'running')
        self.assertEqual(stages['factchecks'], 'skipped')
        self.assertEqual(stages['formatting'], 'pending')
        self.assertEqual(stages['done'], 'pending')
        self.assertNotIn('invented', stages)
        self.release.set()
        complete = self.finish(view)
        self.assertEqual(complete['status'], 'complete')
        self.assertEqual(complete['progress']['stages'][-1], {'id': 'done', 'state': 'done'})

    def test_cancelled_running_job_cannot_bypass_limit_or_publish_result(self):
        self.manager.per_owner = 1
        started = threading.Event()
        view, _ = self.manager.create('alice', {'text': 'first'}, self.waiting_runner(started))
        self.assertTrue(started.wait(2))
        self.assertEqual(self.manager.cancel(view['job_id'], 'alice')['status'], 'cancelled')
        reserve = Mock()
        with self.assertRaises(JobError) as error:
            self.manager.create('alice', {'text': 'second'}, self.waiting_runner(), reserve)
        self.assertEqual(error.exception.code, 'queue_full')
        reserve.assert_not_called()
        self.release.set()
        final = self.finish(view)
        self.assertEqual(final['status'], 'cancelled')
        self.assertNotIn('result', final)
        self.assertNotIn('error', final)
        fresh, _ = self.manager.create('alice', {'text': 'second'}, self.waiting_runner(), reserve)
        self.assertNotEqual(fresh['job_id'], view['job_id'])
        reserve.assert_called_once()

    def test_cancel_queued_job_never_runs_it(self):
        self.manager.executor.shutdown(wait=True)
        self.manager.executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        started = threading.Event()
        first, _ = self.manager.create('alice', {'text': 'first'}, self.waiting_runner(started))
        self.assertTrue(started.wait(2))
        runner = Mock(return_value={'should': 'not run'})
        second, _ = self.manager.create('alice', {'text': 'queued'}, runner)
        self.assertEqual(second['status'], 'queued')
        self.manager.cancel(second['job_id'], 'alice')
        self.release.set()
        self.finish(first)
        self.assertEqual(self.manager.get(second['job_id'], 'alice')['status'], 'cancelled')
        runner.assert_not_called()
        self.manager.executor.shutdown(wait=True)

    def test_expected_errors_are_safe_and_arbitrary_exceptions_are_redacted(self):
        class UnsafeError(Exception):
            code = 'secret-code'
            status = 400
        cases = [(AnalysisError('Try again later.', 429, 'api_quota'), 'Try again later.', 'api_quota'),
                 (UnsafeError('private-api-key'), 'The check could not finish. Please try again.', 'analysis_failed')]
        for index, (failure, message, code) in enumerate(cases):
            def run(progress, exc=failure):
                raise exc
            view, _ = self.manager.create('alice', {'i': index}, run)
            result = self.finish(view)
            self.assertEqual(result['status'], 'failed')
            self.assertEqual(result['error']['error'], message)
            self.assertEqual(result['error']['code'], code)
            self.assertNotIn('private-api-key', json.dumps(result))
            self.assertNotIn('result', result)

    def test_quota_rejection_creates_no_job_and_expiry_removes_result(self):
        def reject():
            raise JobError('Limit reached.', 429, 'daily_limit_reached')
        with self.assertRaises(JobError):
            self.manager.create('alice', {}, self.waiting_runner(), reject)
        self.assertFalse(self.manager.jobs)
        self.release.set()
        view, _ = self.manager.create('alice', {}, self.waiting_runner())
        self.finish(view)
        self.manager.jobs[view['job_id']]['updated_at'] = 0
        with self.assertRaises(JobError) as error:
            self.manager.get(view['job_id'], 'alice')
        self.assertEqual(error.exception.code, 'job_not_found')


if __name__ == '__main__':
    unittest.main()
