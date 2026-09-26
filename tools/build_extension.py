"""Build a Chrome package for an explicit set of CLAR server origins.

The default build is usable with a local CLAR server. Custom builds package
 their server list, Chrome host permissions, and CSP together. No credentials
 belong in this package. --dry-run validates and reports without writing files.
"""
import argparse
import base64
import copy
import hashlib
import ipaddress
import json
from pathlib import Path
import re
from urllib.parse import urlsplit
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BACKENDS = ('http://127.0.0.1:8765', 'http://localhost:8765')
SHARED = ('results.js', 'results.css', 'client.js', 'grounding.js', 'presentation.js')
LEGAL_FILES = ('LICENSE', 'NOTICE')
PACKAGE_FILES = ('background.js', 'cache.js', 'config.js', 'content.js',
                 'panel.html', 'panel.js', 'panel.css', 'selectors.js', 'logo.svg',
                 'README.md', 'icons/16.png', 'icons/32.png', 'icons/48.png', 'icons/128.png')
PROVIDERS = ('local', 'vertex', 'gemini')


def normalize_backend(value):
    """Accept a server origin, never a wildcard, credential, or URL prefix."""
    if (not isinstance(value, str) or not value or
            re.search(r'[\s\\?#%]', value) or not value.isascii()):
        raise ValueError('Use an ASCII HTTPS origin, or localhost/127.0.0.1 HTTP, without a path, query, or credentials.')
    try:
        parsed = urlsplit(value)
        host, port = parsed.hostname, parsed.port
    except ValueError as exc:
        raise ValueError('Invalid server URL or port.') from exc
    if (parsed.scheme not in ('http', 'https') or not host or
            parsed.username is not None or parsed.password is not None or
            parsed.path not in ('', '/') or parsed.netloc.endswith(':')):
        raise ValueError('Server must be an HTTPS origin or a localhost HTTP origin, with no path or credentials.')
    if not re.fullmatch(r'(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)*', host) or len(host) > 253:
        raise ValueError('Use an explicit DNS hostname or IPv4 address; wildcards are not supported.')
    if re.fullmatch(r'[0-9.]+', host):
        try:
            ipaddress.IPv4Address(host)
        except ipaddress.AddressValueError as exc:
            raise ValueError('Use a standard IPv4 address such as 127.0.0.1.') from exc
    if parsed.scheme == 'http' and host not in ('localhost', '127.0.0.1'):
        raise ValueError('HTTP is permitted only for localhost or 127.0.0.1. Use HTTPS for remote servers.')
    if port is not None and not 1 <= port <= 65535:
        raise ValueError('Server port must be between 1 and 65535.')
    suffix = ':' + str(port) if port and port != (443 if parsed.scheme == 'https' else 80) else ''
    return parsed.scheme + '://' + host + suffix


def _der_item(raw, offset=0):
    """Read a bounded DER value; enough to validate the public-key envelope."""
    if offset + 2 > len(raw):
        raise ValueError('Invalid public key DER.')
    tag, length, start = raw[offset], raw[offset + 1], offset + 2
    if length & 128:
        size = length & 127
        if not 1 <= size <= 4 or start + size > len(raw):
            raise ValueError('Invalid public key DER length.')
        length = int.from_bytes(raw[start:start + size], 'big')
        start += size
    end = start + length
    if end > len(raw):
        raise ValueError('Truncated public key DER.')
    return tag, raw[start:end], end


def validate_public_key(raw):
    """Require SubjectPublicKeyInfo, excluding private key PEM/DER formats."""
    tag, sequence, end = _der_item(raw)
    if tag != 0x30 or end != len(raw):
        raise ValueError('Use a DER or PEM SubjectPublicKeyInfo public key.')
    algorithm_tag, algorithm, offset = _der_item(sequence)
    key_tag, key, end = _der_item(sequence, offset)
    oid_tag, oid, _ = _der_item(algorithm)
    if (algorithm_tag != 0x30 or oid_tag != 0x06 or not oid or
            key_tag != 0x03 or len(key) < 32 or key[0] != 0 or end != len(sequence)):
        raise ValueError('Use a DER or PEM SubjectPublicKeyInfo public key, not a private key.')
    return base64.b64encode(raw).decode('ascii')


def load_public_key(path):
    raw = Path(path).read_bytes()
    if b'PRIVATE KEY' in raw:
        raise ValueError('Never package a private key. Supply a public key only.')
    if raw.startswith(b'-----BEGIN PUBLIC KEY-----'):
        match = re.fullmatch(rb'-----BEGIN PUBLIC KEY-----\s+([A-Za-z0-9+/=\s]+)-----END PUBLIC KEY-----\s*', raw)
        if not match:
            raise ValueError('Invalid public key PEM.')
        raw = base64.b64decode(re.sub(rb'\s', b'', match.group(1)), validate=True)
    return validate_public_key(raw)


def extension_id(key):
    public_key = base64.b64decode(key, validate=True)
    validate_public_key(public_key)
    digest = hashlib.sha256(public_key).hexdigest()[:32]
    return ''.join(chr(ord('a') + int(character, 16)) for character in digest)


def build_metadata(backends=None, default_provider='local', key=None, root=ROOT):
    if default_provider not in PROVIDERS:
        raise ValueError('Unknown default provider.')
    origins = list(dict.fromkeys(normalize_backend(value) for value in (backends or DEFAULT_BACKENDS)))
    manifest = copy.deepcopy(json.loads((root / 'extension/manifest.json').read_text()))
    if key is not None:
        manifest['key'] = key
    identifier = extension_id(manifest['key'])
    # An explicit port prevents a custom-port server from granting every port.
    patterns = []
    for origin in origins:
        parsed = urlsplit(origin)
        port = parsed.port or (443 if parsed.scheme == 'https' else 80)
        patterns.append(parsed.scheme + '://' + parsed.hostname + ':' + str(port) + '/*')
    manifest['host_permissions'] = patterns + ['https://*.fbcdn.net/*', 'https://www.facebook.com/*']
    manifest['content_security_policy']['extension_pages'] = (
        "script-src 'self'; object-src 'none'; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: blob: https://*.fbcdn.net https://www.gstatic.com; "
        'connect-src ' + ' '.join(origins) + " https://*.fbcdn.net; frame-src 'self'; base-uri 'none'")
    return {'manifest': manifest, 'identity': {'id': identifier, 'key': manifest['key']},
            'backends': origins, 'default_provider': default_provider}


def build(backends=None, default_provider='local', extension_key=None,
          output_dir=None, archive=None, dry_run=False, root=ROOT):
    root = Path(root).resolve()
    output = Path(output_dir or root / 'extension').resolve()
    bundle_path = Path(archive or root / 'public/clar-extension.zip').resolve()
    source = root / 'extension'
    if output != source and (output in (root, root / 'public', root / 'shared') or source in output.parents):
        raise ValueError('Use extension/ itself or a separate build directory, such as dist/extension.')
    metadata = build_metadata(backends, default_provider,
                              load_public_key(extension_key) if extension_key else None, root=root)
    files = {}
    for name in LEGAL_FILES:
        path = root / name
        if path.is_symlink() or not path.is_file():
            raise ValueError('Missing or unsafe license file: ' + name)
        files[name] = path.read_bytes()
    for name in PACKAGE_FILES:
        path = source / name
        if path.is_symlink() or not path.is_file():
            raise ValueError('Missing or unsafe package file: ' + name)
        files[name] = path.read_bytes()
    for name in SHARED:
        files[name] = (root / 'shared' / name).read_bytes()
    for name in ('manifest', 'identity'):
        files[name + '.json'] = (json.dumps(metadata[name], indent=2) + '\n').encode()
    files['build-config.js'] = (
        '// Generated by tools/build_extension.py. Rebuild to change permitted servers.\n'
        'export const BUILD_CONFIG = Object.freeze({\n'
        '  backends: Object.freeze(' + json.dumps(metadata['backends']) + '),\n'
        '  defaultProvider: ' + json.dumps(default_provider) + '\n});\n').encode()
    report = {'version': metadata['manifest']['version'], 'extension_id': metadata['identity']['id'],
              'backends': metadata['backends'], 'default_provider': default_provider,
              'output_dir': str(output), 'archive': str(bundle_path), 'dry_run': dry_run}
    if dry_run:
        return report
    output.mkdir(parents=True, exist_ok=True)
    for name, data in files.items():
        target = output / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    for name in SHARED:
        (root / 'public' / name).write_bytes(files[name])
    bundle_path.parent.mkdir(parents=True, exist_ok=True)
    # Stable metadata makes two builds from the same source byte-identical.
    with ZipFile(bundle_path, 'w', ZIP_DEFLATED) as bundle:
        for name, data in sorted(files.items()):
            info = ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            bundle.writestr(info, data)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backend', action='append', help='Allowed CLAR origin; repeat for more servers. First is default.')
    parser.add_argument('--default-provider', choices=PROVIDERS, default='local')
    parser.add_argument('--extension-key', help='Optional DER or PEM public key for a different stable extension ID.')
    parser.add_argument('--output-dir', type=Path, help='Unpacked package directory (default: extension/).')
    parser.add_argument('--archive', type=Path, help='ZIP path (default: public/clar-extension.zip).')
    parser.add_argument('--dry-run', action='store_true', help='Validate and print build settings without writing files.')
    args = parser.parse_args()
    try:
        report = build(args.backend, args.default_provider, args.extension_key,
                       args.output_dir, args.archive, args.dry_run)
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
