"""Visible provenance and a small, editorially verified Facebook URL registry.

Page names, politics, blue ticks and missing biographical data are not proof of
identity. Matching establishes only provenance, never the truth of a post.
"""
import json
from pathlib import Path
from urllib.parse import urlsplit, parse_qs


CONFIG_PATH = Path(__file__).parent / 'config' / 'sources.json'


def source_config():
    try:
        value = json.loads(CONFIG_PATH.read_text())
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def canonical_facebook(url):
    if not isinstance(url, str) or len(url) > 2048:
        return ''
    try:
        parsed = urlsplit(url)
        if (parsed.scheme != 'https' or parsed.hostname not in ('facebook.com', 'www.facebook.com', 'm.facebook.com')
                or parsed.username or parsed.password or parsed.port not in (None, 443)):
            return ''
        path = parsed.path.strip('/').lower()
        if path == 'profile.php':
            ident = parse_qs(parsed.query).get('id', [''])[0]
            return 'https://www.facebook.com/profile.php?id=' + ident if ident.isdigit() else ''
        if not path or '/' in path or path in ('watch', 'reel', 'stories', 'photo', 'groups', 'posts'):
            return ''
        return 'https://www.facebook.com/' + path
    except ValueError:
        return ''


def domain_in(url, domains):
    try:
        parsed = urlsplit(url)
        host = (parsed.hostname or '').lower()
        return (parsed.scheme == 'https' and not parsed.username and not parsed.password
                and parsed.port in (None, 443) and any(host == d or host.endswith('.' + d) for d in domains))
    except (TypeError, ValueError):
        return False


def assess_origin(value, language='en'):
    raw = value if isinstance(value, dict) else {}
    name = raw.get('poster_name', '')
    name = name.strip()[:180] if isinstance(name, str) else ''
    url = canonical_facebook(raw.get('poster_url', raw.get('url', '')))
    context = raw.get('context', 'unknown')
    kind = 'individual' if context == 'individual' else 'unknown_page'
    matched = None
    if raw.get('anonymous') is True and context == 'group':
        kind = 'anonymous_group'
    elif url:
        for record in source_config().get('facebook_pages', []):
            if (isinstance(record, dict) and canonical_facebook(record.get('url')) == url
                    and record.get('type') in ('official', 'known_media')
                    and record.get('verified_from') and record.get('verified_at')):
                matched = {k: record[k] for k in ('name', 'url', 'verified_from', 'verified_at')}
                kind = record['type']
                break
    notes = {
        'en': {'matched': 'The profile URL matches a page linked by its official publisher site. This identifies the source; each claim still needs evidence.', 'unknown': 'The visible profile has not been matched to the verified registry. Its name or subject matter does not establish credibility; account history was not checked.', 'individual': 'The page identifies an individual. Identity and account history have not been independently verified.', 'anonymous_group': 'Facebook displays this as an anonymous group post. The author cannot be identified from the visible post.'},
        'ro': {'matched': 'Adresa profilului corespunde paginii indicate pe site-ul oficial al instituției. Proveniența nu confirmă automat afirmațiile.', 'unknown': 'Profilul vizibil nu a fost identificat în registrul verificat. Numele și subiectele nu stabilesc credibilitatea; istoricul contului nu a fost verificat.', 'individual': 'Pagina identifică o persoană. Identitatea și istoricul contului nu au fost verificate independent.', 'anonymous_group': 'Facebook afișează o postare anonimă în grup. Autorul nu poate fi identificat din postarea vizibilă.'},
        'ru': {'matched': 'Адрес профиля совпадает со страницей, указанной на официальном сайте организации. Происхождение не подтверждает автоматически утверждения.', 'unknown': 'Видимый профиль не найден в проверенном реестре. Название и тематика не определяют достоверность; история аккаунта не проверялась.', 'individual': 'На странице указано физическое лицо. Личность и история аккаунта независимо не проверялись.', 'anonymous_group': 'Facebook показывает анонимную публикацию в группе. Автора нельзя установить по видимому сообщению.'}
    }
    return {'poster_name': name, 'type': kind, 'url': url,
            'note': notes[language]['matched' if matched else kind if kind in ('individual', 'anonymous_group') else 'unknown'],
            'matched_registry': matched}
