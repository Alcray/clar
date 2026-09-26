"""Release smoke diagnostics and cleanup, with no Docker engine required."""
from contextlib import redirect_stderr, redirect_stdout
import io
import json
import subprocess
import unittest
from unittest.mock import patch

from tools import smoke_container as smoke


class ContainerSmokeTests(unittest.TestCase):
    def test_failed_command_exposes_bounded_redacted_stderr_never_stdout(self):
        result = subprocess.CompletedProcess(['docker'], 1, 'PRIVATE SEED STDOUT',
            'x' * 5000 + '\nAssertionError: quota failed; token=private-token')
        with patch.object(smoke.subprocess, 'run', return_value=result):
            with self.assertRaises(RuntimeError) as caught:
                smoke.docker('exec', '-i', redactions=('private-token',))
        message = str(caught.exception)
        self.assertIn('AssertionError: quota failed', message)
        self.assertIn('[redacted]', message)
        self.assertNotIn('private-token', message)
        self.assertNotIn('PRIVATE SEED STDOUT', message)
        self.assertLess(len(message), 4100)

    def test_timeout_diagnostic_does_not_expose_seed_stdout(self):
        error = subprocess.TimeoutExpired(['docker'], 45,
            output=b'PRIVATE SEED STDOUT', stderr=b'engine request timed out')
        with patch.object(smoke.subprocess, 'run', side_effect=error):
            with self.assertRaises(RuntimeError) as caught:
                smoke.docker('run', '--rm')
        self.assertIn('engine request timed out', str(caught.exception))
        self.assertNotIn('PRIVATE SEED STDOUT', str(caught.exception))

    def test_cleanup_tries_remaining_resources_after_errors(self):
        calls = []
        def docker(*args, **kwargs):
            calls.append(args)
            if args[0] == 'ps':
                return 'first-container\nsecond-container\n'
            if args[:2] == ('volume', 'ls'):
                return 'owned-volume\n'
            if args[-1] == 'first-container':
                raise subprocess.TimeoutExpired(['docker', 'rm'], 30)
            if args[-1] == 'owned-volume':
                raise RuntimeError('volume is still in use')
            return ''
        with patch.object(smoke, 'docker', side_effect=docker):
            errors = smoke.cleanup_resources('clar.smoke=only-this-run')
        self.assertEqual(len(errors), 2)
        self.assertIn(('rm', '-f', '-v', 'second-container'), calls)
        self.assertIn(('volume', 'rm', 'owned-volume'), calls)
        for command in calls:
            if command[0] == 'ps' or command[:2] == ('volume', 'ls'):
                self.assertIn('label=clar.smoke=only-this-run', command)

    def test_failed_creation_still_discovers_resources_and_preserves_error(self):
        calls = []
        def docker(*args, **kwargs):
            calls.append(args)
            if args[0] == 'run':
                raise RuntimeError('original creation timeout')
            if args[0] == 'ps':
                return 'created-before-timeout\n'
            if args[0] == 'rm':
                raise RuntimeError('cleanup also failed')
            return ''
        output = io.StringIO()
        with patch.object(smoke, 'docker', side_effect=docker), redirect_stderr(output):
            with self.assertRaisesRegex(RuntimeError, 'original creation timeout'):
                smoke.smoke('test-image', 'https://clar.example.test')
        label = calls[0][calls[0].index('--label') + 1]
        self.assertIn(('ps', '-aq', '--filter', 'label=' + label), calls)
        self.assertIn(('rm', '-f', '-v', 'created-before-timeout'), calls)
        self.assertIn(('volume', 'ls', '-q', '--filter', 'label=' + label), calls)
        self.assertIn('cleanup also failed', output.getvalue())

    def test_successful_checks_fail_when_cleanup_fails_and_label_the_seeder(self):
        calls = []
        def docker(*args, **kwargs):
            calls.append(args)
            if args[0] == 'wait':
                return '1'
            if args[0] == 'inspect':
                return json.dumps([{'Config': {'User': '10001:10001'},
                    'HostConfig': {'ReadonlyRootfs': True}, 'State': {'ExitCode': 0}}])
            if args[0] == 'run' and '--rm' in args:
                return json.dumps({'access_code': 'private-code', 'extension_token': 'private-token'})
            return ''
        logs = subprocess.CompletedProcess(['docker'], 0, '', 'Create a reviewer invitation')
        with patch.object(smoke, 'docker', side_effect=docker), \
                patch.object(smoke.subprocess, 'run', return_value=logs), \
                patch.object(smoke, 'cleanup_resources', return_value=['volume removal failed']), \
                redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(RuntimeError, 'volume removal failed'):
                smoke.smoke('test-image', 'https://clar.example.test')
        runs = [args for args in calls if args[0] == 'run']
        labels = {args[args.index('--label') + 1] for args in runs}
        self.assertEqual(len(runs), 3)
        self.assertEqual(len(labels), 1)
        seeder = next(args for args in runs if '--rm' in args)
        self.assertTrue(seeder[seeder.index('--name') + 1].endswith('-seed'))
        volume = next(args for args in calls if args[:2] == ('volume', 'create'))
        self.assertEqual(volume[volume.index('--label') + 1], labels.pop())


if __name__ == '__main__':
    unittest.main()
