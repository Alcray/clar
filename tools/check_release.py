"""Scan the Git index that will be published, without printing matched secrets.

This is a targeted release gate, not a claim that every possible secret format
can be detected. Keep credentials and private runtime files out of the index.
"""
import argparse
import io
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import tempfile
import zipfile

PRIVATE_PARTS = {'.runtime', '.venv', 'node_modules', '__pycache__', '.ssh', '.aws', '.gcloud'}
PRIVATE_FILES = {
    'deploy/run-preview.sh', 'deploy/rtx3070.yaml', 'deploy/clar-gateway.service',
    'deploy/public_gateway.py', 'tools/export_feedback.py', 'tools/evaluate_live.py',
    'docs/CLAR-REVIEW-TRACKER.md', 'docs/CLAR-REVIEW-BRIEF.md',
}
PATTERNS = (
    ('Google API key', re.compile(rb'\bAIza[A-Za-z0-9_-]{35}(?![A-Za-z0-9_-])')),
    ('Vertex Express API key', re.compile(rb'\bAQ\.[A-Za-z0-9_-]{32,}(?![A-Za-z0-9_-])')),
    ('GitHub token', re.compile(rb'\b(?:gh[pousr]_[A-Za-z0-9]{20,255}|github_pat_[A-Za-z0-9_]{40,255})(?![A-Za-z0-9_])')),
    # Actual PEM line endings distinguish a key from negative-test source that
    # deliberately writes a short synthetic "BEGIN PRIVATE KEY\\n" fixture.
    ('PEM private key', re.compile(rb'-----BEGIN (?:[A-Z]+ )?PRIVATE KEY-----[ \t]*\r?\n')),
)
MAX_FILE_BYTES = 20_000_000


def private_path(name):
    path = PurePosixPath(name)
    return (any(part in PRIVATE_PARTS for part in path.parts)
            or name in PRIVATE_FILES or path.name == '.DS_Store'
            or path.name == '.env' or (path.name.startswith('.env.') and path.name != '.env.example')
            or path.name in ('invites.json', 'usage.json', 'feedback.jsonl', 'reviewer-links.md', 'owner.env'))


def inspect_bytes(name, raw, findings):
    for label, pattern in PATTERNS:
        match = pattern.search(raw)
        if match:
            line = raw.count(b'\n', 0, match.start()) + 1
            findings.add((name, line, label))


def inspect_zip(name, raw, findings):
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            total = 0
            for member in archive.infolist():
                if member.is_dir():
                    continue
                child = name + '!' + member.filename
                total += member.file_size
                if total > MAX_FILE_BYTES or member.file_size > MAX_FILE_BYTES:
                    findings.add((name, 0, 'Archive exceeds release scan size limit'))
                    return
                if private_path(member.filename) or '..' in PurePosixPath(member.filename).parts or member.filename.startswith('/'):
                    findings.add((child, 0, 'Private or unsafe archive path'))
                inspect_bytes(child, archive.read(member), findings)
    except (ValueError, OSError, zipfile.BadZipFile, RuntimeError):
        findings.add((name, 0, 'Archive could not be inspected'))


def scan(root):
    """Read staged/index blobs; untracked private files remain entirely unread."""
    result = subprocess.run(['git', '-C', str(root), 'ls-files', '--stage', '-z'],
                            check=True, capture_output=True)
    entries = result.stdout.split(b'\0')
    findings = set()
    count = 0
    for entry in entries:
        if not entry:
            continue
        prefix, path_bytes = entry.split(b'\t', 1)
        mode, object_id, stage = prefix.split()
        name = path_bytes.decode('utf-8', errors='surrogateescape')
        count += 1
        if private_path(name):
            findings.add((name, 0, 'Private file is in the Git index'))
        if stage != b'0':
            findings.add((name, 0, 'Unresolved merge entry'))
            continue
        if mode not in (b'100644', b'100755'):
            findings.add((name, 0, 'Symlinks and submodules require a separate release audit'))
            continue
        size = int(subprocess.run(['git', '-C', str(root), 'cat-file', '-s', object_id.decode('ascii')],
                                  check=True, capture_output=True).stdout)
        if size > MAX_FILE_BYTES:
            findings.add((name, 0, 'File exceeds release scan size limit'))
            continue
        raw = subprocess.run(['git', '-C', str(root), 'cat-file', 'blob', object_id.decode('ascii')],
                             check=True, capture_output=True).stdout
        inspect_bytes(name, raw, findings)
        if name.lower().endswith('.zip'):
            inspect_zip(name, raw, findings)
    if not count:
        findings.add(('<index>', 0, 'No indexed files found; stage the intended release files before checking'))
    return count, sorted(findings)


def self_test():
    """Synthetic positive and negative cases; no real credentials are needed."""
    with tempfile.TemporaryDirectory(prefix='clar-release-check-') as directory:
        root = Path(directory)
        subprocess.run(['git', 'init', '--quiet', directory], check=True)
        (root / '.env.example').write_text('GEMINI_API_KEY=\n')
        (root / 'safe.py').write_text("fixture = '-----BEGIN PRIVATE KEY-----\\nnever publish\\n-----END PRIVATE KEY-----'\n")
        (root / 'manifest.json').write_text('{"key":"MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8A"}')
        (root / '.runtime').mkdir()
        (root / '.runtime' / 'untracked').write_text('Private contents must never be read.')
        subprocess.run(['git', '-C', directory, 'add', '.env.example', 'safe.py', 'manifest.json'], check=True)
        assert not scan(root)[1], 'Synthetic fixtures/public key were flagged.'
        (root / 'bad.txt').write_text('A' + 'Iza' + 'x' * 35 + '\nA' + 'Q.' + 'x' * 40 + '\ngh' + 'p_' + 'x' * 36)
        (root / 'bad.pem').write_text('-----BEGIN ' + 'PRIVATE KEY-----\nnot-a-real-key\n-----END PRIVATE KEY-----\n')
        (root / '.env').write_text('TEST=synthetic-only\n')
        subprocess.run(['git', '-C', directory, 'add', 'bad.txt', 'bad.pem', '.env'], check=True)
        labels = {finding[2] for finding in scan(root)[1]}
        assert labels == {'Google API key', 'Vertex Express API key', 'GitHub token', 'PEM private key', 'Private file is in the Git index'}, labels
        # A benign working copy cannot conceal a secret already staged for release.
        (root / 'bad.txt').write_text('Safe working copy, bad staged copy.')
        assert 'Google API key' in {finding[2] for finding in scan(root)[1]}
        with zipfile.ZipFile(root / 'bundle.zip', 'w') as archive:
            archive.writestr('.env', 'PRIVATE=synthetic')
        subprocess.run(['git', '-C', directory, 'add', 'bundle.zip'], check=True)
        assert 'Private or unsafe archive path' in {finding[2] for finding in scan(root)[1]}
    print('Release scanner synthetic checks passed.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--self-test', action='store_true')
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    try:
        count, findings = scan(args.root)
    except (OSError, subprocess.CalledProcessError, ValueError):
        print('Release check failed: could not read the Git index.', file=sys.stderr)
        return 1
    if findings:
        print('Release check failed (secret values are not printed):', file=sys.stderr)
        for name, line, description in findings:
            print('{}{}: {}'.format(name, ':' + str(line) if line else '', description), file=sys.stderr)
        return 1
    print('Release check passed for {} indexed files.'.format(count))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
