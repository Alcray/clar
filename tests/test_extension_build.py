"""Portable extension builds: origin validation, identity, and release contents."""
import base64
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from zipfile import ZipFile

from tools.build_extension import (ROOT, SHARED, build, build_metadata, extension_id,
                                   load_public_key, normalize_backend)


class ExtensionBuildTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        shutil.copytree(ROOT / 'extension', self.root / 'extension')
        shutil.copytree(ROOT / 'shared', self.root / 'shared')
        for name in ('LICENSE', 'NOTICE'):
            shutil.copyfile(ROOT / name, self.root / name)
        (self.root / 'public').mkdir()

    def test_defaults_are_local_and_id_is_stable(self):
        data = build_metadata(root=self.root)
        self.assertEqual(data['backends'], ['http://127.0.0.1:8765', 'http://localhost:8765'])
        self.assertEqual(data['default_provider'], 'local')
        self.assertEqual(data['identity']['id'], 'ajlgkaeeokegabffalnaoncikpgniaci')
        self.assertEqual(extension_id(data['manifest']['key']), data['identity']['id'])
        self.assertNotIn('tail14', json.dumps(data))

    def test_canonical_origins_and_duplicate_removal(self):
        data = build_metadata(['HTTPS://CLAR.EXAMPLE.ORG:443/', 'https://clar.example.org',
                               'http://localhost:09000'], root=self.root)
        self.assertEqual(data['backends'], ['https://clar.example.org', 'http://localhost:9000'])
        self.assertIn('https://clar.example.org:443/*', data['manifest']['host_permissions'])
        self.assertIn('http://localhost:9000/*', data['manifest']['host_permissions'])
        csp = data['manifest']['content_security_policy']['extension_pages']
        self.assertIn('connect-src https://clar.example.org http://localhost:9000 https://*.fbcdn.net;', csp)
        self.assertNotIn('127.0.0.1', csp)
        self.assertNotIn('<all_urls>', json.dumps(data))

    def test_unsafe_origins_rejected(self):
        invalid = ['http://clar.example.org', 'https://*.example.org', 'https://clar.example.org/path',
                   'https://user:pass@clar.example.org', 'https://clar.example.org?token=secret',
                   'https://clar.example.org#extension', 'https://clar.example.org?',
                   'ftp://localhost', 'file:///tmp', 'javascript:alert(1)', 'https://clar.example.org:0',
                   'https://clar.example.org:65536', 'https://clar.example.org:', 'https://clar.example.org\\other',
                   'https://clar.example.org\n', 'https://clar.example.org;script-src',
                   'https://127.1', 'https://2130706433', 'https://127.0.0.01', 'https://example.org.',
                   'http://[::1]:8765', 'https://exa%6dple.org', ' https://example.org']
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(ValueError):
                normalize_backend(value)

    def test_dry_run_writes_nothing(self):
        output, archive = self.root / 'dist/ext', self.root / 'dist/extension.zip'
        before = {str(p.relative_to(self.root)): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        report = build(['https://clar.example.org'], output_dir=output, archive=archive,
                       dry_run=True, root=self.root)
        after = {str(p.relative_to(self.root)): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        self.assertEqual(before, after)
        self.assertTrue(report['dry_run'])
        self.assertFalse(output.exists())

    def test_custom_build_is_complete_and_does_not_retarget_source(self):
        output, archive = self.root / 'dist/ext', self.root / 'dist/extension.zip'
        original = (self.root / 'extension/manifest.json').read_bytes()
        (self.root / 'extension/secret.pem').write_text('A private deployment file must not be packaged.')
        (self.root / 'extension/.env').write_text('SECRET=test-only')
        report = build(['https://clar.example.org:9443'], 'vertex', output_dir=output,
                       archive=archive, root=self.root)
        self.assertEqual((self.root / 'extension/manifest.json').read_bytes(), original)
        manifest = json.loads((output / 'manifest.json').read_text())
        self.assertIn('https://clar.example.org:9443/*', manifest['host_permissions'])
        self.assertEqual(report['default_provider'], 'vertex')
        self.assertIn('"vertex"', (output / 'build-config.js').read_text())
        with ZipFile(archive) as bundle:
            names = bundle.namelist()
            self.assertIn('build-config.js', names)
            self.assertIn('background.js', names)
            self.assertIn('icons/128.png', names)
            self.assertNotIn('.env', names)
            self.assertNotIn('secret.pem', names)
            for name in ('LICENSE', 'NOTICE'):
                self.assertIn(name, names)
                self.assertEqual(bundle.read(name), (ROOT / name).read_bytes())
            for name in names:
                self.assertEqual(bundle.read(name), (output / name).read_bytes())
        for name in SHARED:
            self.assertEqual((self.root / 'public' / name).read_bytes(), (self.root / 'shared' / name).read_bytes())

    def test_reproducible_zip(self):
        archive = self.root / 'extension.zip'
        build(archive=archive, root=self.root)
        first = hashlib.sha256(archive.read_bytes()).hexdigest()
        build(archive=archive, root=self.root)
        self.assertEqual(hashlib.sha256(archive.read_bytes()).hexdigest(), first)

    def test_public_key_pem_and_der_accepted_private_key_refused(self):
        key = json.loads((self.root / 'extension/manifest.json').read_text())['key']
        der = self.root / 'public.der'
        der.write_bytes(base64.b64decode(key))
        self.assertEqual(load_public_key(der), key)
        pem = self.root / 'public.pem'
        pem.write_text('-----BEGIN PUBLIC KEY-----\n' + key + '\n-----END PUBLIC KEY-----\n')
        self.assertEqual(load_public_key(pem), key)
        pem.write_text('-----BEGIN PRIVATE KEY-----\nnever publish\n-----END PRIVATE KEY-----')
        with self.assertRaisesRegex(ValueError, 'Never package a private key'):
            load_public_key(pem)
        der.write_bytes(b'\x30\x00')
        with self.assertRaises(ValueError):
            load_public_key(der)

    def test_symlink_asset_is_not_packaged(self):
        path = self.root / 'extension/logo.svg'
        path.unlink()
        path.symlink_to(ROOT / 'extension/logo.svg')
        with self.assertRaisesRegex(ValueError, 'unsafe package file'):
            build(root=self.root)

    def test_license_files_are_required_before_writing_a_package(self):
        (self.root / 'LICENSE').unlink()
        output, archive = self.root / 'dist/ext', self.root / 'dist/extension.zip'
        with self.assertRaisesRegex(ValueError, 'Missing or unsafe license file: LICENSE'):
            build(output_dir=output, archive=archive, root=self.root)
        self.assertFalse(output.exists())
        self.assertFalse(archive.exists())

    def test_unknown_provider_rejected(self):
        with self.assertRaises(ValueError):
            build_metadata(default_provider='made-up-provider', root=self.root)


if __name__ == '__main__':
    unittest.main()
