"""Create and revoke private CLAR reviewer invitations.

Run on the server that holds the private runtime directory. Access codes are
shown only when created; extension tokens are shown only at creation and to
their authenticated owner through /api/extension-setup.
"""

import argparse
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import stat
import tempfile
import time


ROOT = Path(__file__).resolve().parent
DEFAULT_PATH = ROOT / '.runtime' / 'invites.json'
NAME_PATTERN = re.compile(r'[a-z][a-z0-9-]{0,39}\Z')


class InviteStoreError(Exception):
    """The invitation file is absent, unreadable, or invalid."""


class InviteStoreNotConfigured(InviteStoreError):
    """No invitation file has been created yet."""


def store_path(path=None):
    return Path(path) if path is not None else Path(os.environ.get('CLAR_INVITES_FILE', DEFAULT_PATH))


def _new_store():
    return {'version': 1, 'signing_key': secrets.token_urlsafe(32), 'invites': {}}


def read_store(path=None):
    path = store_path(path)
    try:
        if path.is_symlink():
            raise InviteStoreError('Refusing a symlinked invitation file.')
        details = path.stat()
        if stat.S_IMODE(details.st_mode) & 0o077:
            raise InviteStoreError('The invitation file must be readable only by its owner.')
        if details.st_size > 1_000_000:
            raise InviteStoreError('The invitation file is too large.')
        raw = path.read_text(encoding='utf-8')
        data = json.loads(raw)
        if (
            not isinstance(data, dict) or data.get('version') != 1
            or not isinstance(data.get('signing_key'), str)
            or len(data['signing_key']) < 40
            or not isinstance(data.get('invites'), dict)
        ):
            raise InviteStoreError('The invitation file is invalid.')
        return data
    except FileNotFoundError as exc:
        raise InviteStoreNotConfigured('Reviewer access has not been configured.') from exc
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise InviteStoreError('The invitation file could not be read.') from exc


def _save_store(data, path=None):
    path = store_path(path)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.is_symlink():
        raise InviteStoreError('Refusing a symlinked invitation file.')
    temporary = None
    try:
        with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=path.parent,
                                         prefix='.invites-', delete=False) as output:
            temporary = Path(output.name)
            os.fchmod(output.fileno(), 0o600)
            json.dump(data, output, separators=(',', ':'), sort_keys=True)
            output.write('\n')
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        path.chmod(0o600)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _code_hash(code, salt):
    return hashlib.sha256((salt + ':' + code).encode('utf-8')).hexdigest()


def create_invite(name, path=None):
    if not isinstance(name, str) or not NAME_PATTERN.fullmatch(name):
        raise ValueError('Use a lowercase reviewer name with letters, numbers, or hyphens.')
    try:
        data = read_store(path)
    except InviteStoreNotConfigured:
        data = _new_store()
    if name in data['invites']:
        raise ValueError('That reviewer name already exists; use a new name.')
    access_code = secrets.token_urlsafe(24)
    extension_token = secrets.token_urlsafe(32)
    salt = secrets.token_hex(16)
    data['invites'][name] = {
        'id': secrets.token_urlsafe(16),
        'code_salt': salt,
        'code_hash': _code_hash(access_code, salt),
        'extension_token': extension_token,
        'created_at': int(time.time()),
        'revoked_at': None,
    }
    _save_store(data, path)
    return {'name': name, 'access_code': access_code, 'extension_token': extension_token}


def list_invites(path=None):
    data = read_store(path)
    return [
        {'name': name, 'status': 'revoked' if entry.get('revoked_at') else 'active',
         'created_at': entry.get('created_at'), 'revoked_at': entry.get('revoked_at')}
        for name, entry in sorted(data['invites'].items())
    ]


def revoke_invite(name, path=None):
    data = read_store(path)
    entry = data['invites'].get(name)
    if not isinstance(entry, dict):
        raise ValueError('That reviewer name was not found.')
    if entry.get('revoked_at'):
        return False
    entry['revoked_at'] = int(time.time())
    _save_store(data, path)
    return True


def active_invite(data, name, invite_id=None):
    entry = data['invites'].get(name)
    if not isinstance(entry, dict) or entry.get('revoked_at'):
        return None
    if invite_id is not None and not hmac.compare_digest(str(entry.get('id', '')), str(invite_id)):
        return None
    return entry


def invite_for_code(data, code):
    if not isinstance(code, str) or not 8 <= len(code) <= 256:
        return None
    for name, entry in data['invites'].items():
        if not isinstance(entry, dict) or entry.get('revoked_at'):
            continue
        salt, expected = entry.get('code_salt'), entry.get('code_hash')
        if isinstance(salt, str) and isinstance(expected, str) and hmac.compare_digest(
            _code_hash(code, salt), expected
        ):
            return name, entry
    return None


def invite_for_extension_token(data, token):
    if not isinstance(token, str) or not token:
        return None
    for name, entry in data['invites'].items():
        if isinstance(entry, dict) and not entry.get('revoked_at'):
            expected = entry.get('extension_token')
            if isinstance(expected, str) and hmac.compare_digest(token, expected):
                return name, entry
    return None


def main():
    parser = argparse.ArgumentParser(description='Manage CLAR public reviewer invitations.')
    actions = parser.add_subparsers(dest='action', required=True)
    create = actions.add_parser('create', help='Create a reviewer and print one-time credentials.')
    create.add_argument('name')
    actions.add_parser('list', help='List names and status without secrets.')
    revoke = actions.add_parser('revoke', help='Disable an invitation and its sessions immediately.')
    revoke.add_argument('name')
    args = parser.parse_args()
    try:
        if args.action == 'create':
            created = create_invite(args.name)
            print('Reviewer: ' + created['name'])
            print('Access code: ' + created['access_code'])
            print('Extension token: ' + created['extension_token'])
            print('Save these now; the access code cannot be displayed again.')
        elif args.action == 'list':
            for entry in list_invites():
                print('{}\t{}'.format(entry['name'], entry['status']))
        else:
            print('{}\t{}'.format(args.name, 'revoked' if revoke_invite(args.name) else 'already revoked'))
    except (ValueError, InviteStoreError) as exc:
        parser.exit(1, 'Error: {}\n'.format(exc))


if __name__ == '__main__':
    main()
