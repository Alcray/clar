"""Bounded, owner-scoped analysis jobs. Inputs/results live only in memory."""
import concurrent.futures
import hashlib
import json
import secrets
import threading
import time

ANALYSIS_VERSION = 'clar-0.4.1'
STAGES = ('reading', 'origin', 'sources', 'factchecks', 'formatting', 'done')


class JobError(Exception):
    def __init__(self, message, status=400, code='job_error'):
        super().__init__(message)
        self.status, self.code = status, code


class JobCancelled(Exception):
    pass


class JobManager:
    def __init__(self, workers=2, ttl=1800, maximum=32, per_owner=8):
        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=workers)
        self.ttl, self.maximum, self.per_owner = ttl, maximum, per_owner
        self.lock = threading.RLock()
        self.jobs = {}

    def _prune(self):
        now = time.time()
        for ident, job in list(self.jobs.items()):
            if not self._inflight(job) and now-job['updated_at'] > self.ttl:
                self.jobs.pop(ident)
        # Bound retained completed results independently of pending requests.
        finished = sorted((j for j in self.jobs.values() if not self._inflight(j)),
                          key=lambda j: j['updated_at'])
        for job in finished[:-100]:
            self.jobs.pop(job['id'], None)

    @staticmethod
    def _inflight(job):
        # Cancellation stops further pipeline stages, but an already-started
        # provider call can still be running. Keep counting it until it exits;
        # otherwise cancel/start loops bypass queue and per-owner limits.
        future = job.get('future')
        return job['status'] in ('queued', 'running') or (future is not None and not future.done())

    def create(self, owner, payload, runner, reserve=None, force=False):
        fingerprint = hashlib.sha256(json.dumps(
            [ANALYSIS_VERSION, payload], sort_keys=True, separators=(',', ':'), ensure_ascii=False
        ).encode()).hexdigest()
        with self.lock:
            self._prune()
            matching = [job for job in self.jobs.values()
                        if job['owner'] == owner and job['fingerprint'] == fingerprint]
            active_matches = [job for job in matching if job['status'] in ('queued', 'running')]
            if active_matches:
                return self._view(max(active_matches, key=lambda job: job['created_at'])), True
            completed_matches = [job for job in matching if job['status'] == 'complete']
            if completed_matches and not force:
                return self._view(max(completed_matches, key=lambda job: job['updated_at'])), True
            active = [j for j in self.jobs.values() if self._inflight(j)]
            if len(active) >= self.maximum or sum(j['owner'] == owner for j in active) >= self.per_owner:
                raise JobError('Too many checks are waiting. Please try again shortly.', 429, 'queue_full')
            if reserve:
                reserve()
            now = time.time()
            job = {'id': secrets.token_urlsafe(24), 'owner': owner, 'fingerprint': fingerprint,
                   'status': 'queued', 'created_at': now, 'updated_at': now,
                   'stages': {stage: 'pending' for stage in STAGES},
                   'result': None, 'error': None, 'cancelled': threading.Event()}
            self.jobs[job['id']] = job
            try:
                job['future'] = self.executor.submit(self._run, job, runner)
            except RuntimeError:
                self.jobs.pop(job['id'], None)
                raise JobError('The checking service is restarting. Please try again shortly.', 503, 'queue_unavailable')
            return self._view(job), False

    def _run(self, job, runner):
        def progress(stage, state='running'):
            if job['cancelled'].is_set():
                raise JobCancelled()
            if stage not in STAGES or state not in ('pending', 'running', 'done', 'skipped'):
                return
            with self.lock:
                if job['cancelled'].is_set():
                    raise JobCancelled()
                job['stages'][stage] = state
                job['updated_at'] = time.time()
        try:
            with self.lock:
                if job['cancelled'].is_set():
                    return
                job['status'] = 'running'
            result = runner(progress)
            with self.lock:
                # Serialize cancellation with publication of the result so a
                # cancelled check cannot race back into a complete state.
                if job['cancelled'].is_set():
                    raise JobCancelled()
                job['result'] = result
                job['status'] = 'complete'
                job['stages']['done'] = 'done'
                job['updated_at'] = time.time()
        except JobCancelled:
            with self.lock:
                job['status'] = 'cancelled'
                job['updated_at'] = time.time()
        except Exception as exc:
            with self.lock:
                # Expected analysis errors have public-safe messages. Never expose
                # arbitrary exceptions, provider bodies, credentials, or input.
                from analysis import AnalysisError
                safe = isinstance(exc, (AnalysisError, JobError))
                job['error'] = {
                    'error': str(exc) if safe else 'The check could not finish. Please try again.',
                    'code': getattr(exc, 'code', 'analysis_failed') if safe else 'analysis_failed',
                    'status': getattr(exc, 'status', 502) if safe else 502,
                }
                job['status'] = 'cancelled' if job['cancelled'].is_set() else 'failed'
                job['updated_at'] = time.time()

    def _owned(self, ident, owner):
        job = self.jobs.get(ident)
        if not job or job['owner'] != owner:
            raise JobError('That check is no longer available. Start a new check.', 404, 'job_not_found')
        return job

    @staticmethod
    def _view(job):
        view = {'job_id': job['id'], 'status': job['status'],
                'progress': {'stages': [{'id': stage, 'state': job['stages'][stage]} for stage in STAGES]},
                'analysis_version': ANALYSIS_VERSION}
        if job['status'] == 'complete':
            view['result'] = job['result']
        elif job['status'] == 'failed':
            view['error'] = job['error']
        return view

    def get(self, ident, owner):
        with self.lock:
            self._prune()
            return self._view(self._owned(ident, owner))

    def cancel(self, ident, owner):
        with self.lock:
            job = self._owned(ident, owner)
            if job['status'] in ('queued', 'running'):
                job['cancelled'].set()
                job['status'] = 'cancelled'
                job['updated_at'] = time.time()
                job['future'].cancel()
            return self._view(job)


JOBS = JobManager()
