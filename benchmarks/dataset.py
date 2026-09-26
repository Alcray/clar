"""Read versioned editorial datasets and enforce their provenance/quote contracts."""
import hashlib
import json
from pathlib import Path

from .contract import KINDS, VERDICTS, PURPOSES, TECHNIQUES

DEFAULT_DATASET = Path(__file__).parent / 'data' / 'editorial-v1.json'


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


def load_dataset(path=DEFAULT_DATASET):
    path = Path(path).resolve()
    data = json.loads(path.read_text(encoding='utf-8'))
    if not data.get('version') or not isinstance(data.get('cases'), list) or not data['cases']:
        raise ValueError('Dataset needs a version and nonempty cases.')
    seen = set()
    for case in data['cases']:
        if case.get('id') in seen or not case.get('id'):
            raise ValueError('Case IDs must be nonempty and unique.')
        seen.add(case['id'])
        if case.get('language') not in ('en', 'ro', 'ru') or case.get('track') not in ('fixed', 'live'):
            raise ValueError('Invalid case language or track: ' + case['id'])
        if not case.get('text') or not case.get('category') or not case.get('cluster_id'):
            raise ValueError('Case text, category, and cluster_id are required.')
        provenance = case.get('provenance', {})
        if not provenance.get('kind') or not provenance.get('label_status') or not provenance.get('rationale'):
            raise ValueError('Every case needs explicit provenance and editorial rationale.')
        expected = case.get('expected', {})
        if not expected.get('statements'):
            raise ValueError('Every case needs expected statements.')
        ids = [s['id'] for s in case.get('evidence', [])]
        if len(ids) != len(set(ids)):
            raise ValueError('Evidence IDs must be unique per case.')
        for source in case.get('evidence', []):
            if not source.get('excerpt') or not source.get('provenance'):
                raise ValueError('Evidence needs an excerpt and provenance.')
        for statement in expected['statements'] + [s for variant in expected.get('statement_variants', []) for s in variant]:
            if statement.get('text') not in case['text'] or not statement.get('text'):
                raise ValueError('Expected quotes must be exact original spans: ' + case['id'])
            if statement.get('kind') not in KINDS or statement.get('verdict') not in VERDICTS:
                raise ValueError('Invalid expected statement classification.')
            if case['track'] == 'fixed' and any(x not in ids for x in statement.get('evidence_ids', [])):
                raise ValueError('Unknown expected evidence ID.')
        if case.get('modality', 'text') not in ('text', 'image'):
            raise ValueError('Invalid case modality.')
        if case.get('modality') == 'image':
            image = (path.parent / case.get('image_path', '')).resolve()
            if not image.is_relative_to(path.parent) or not image.is_file() or image.suffix != '.png':
                raise ValueError('Image must be an existing PNG within the dataset directory.')
            if hashlib.sha256(image.read_bytes()).hexdigest() != case.get('image_sha256'):
                raise ValueError('Screenshot hash changed; update the versioned dataset.')
        if expected.get('purpose') not in PURPOSES:
            raise ValueError('Invalid expected purpose.')
        for technique in expected.get('techniques', []):
            if technique['type'] not in TECHNIQUES or technique['quote'] not in case['text']:
                raise ValueError('Invalid expected technique quote.')
        if case['track'] == 'live' and not provenance.get('labels_as_of'):
            raise ValueError('Live cases need labels_as_of to expose staleness.')
    return data, digest(data)


def fixed_payload(case):
    # Expected labels and rationales NEVER enter model input.
    payload = {'language': case['language'], 'post_date': case.get('post_date', ''),
               'evidence': [{'id': x['id'], 'title': x['title'], 'excerpt': x['excerpt']} for x in case.get('evidence', [])]}
    if case.get('modality') == 'image':
        payload['post_image'] = 'Read the attached screenshot; transcribe its visible text into original_text.'
    else:
        payload['post'] = case['text']
    return payload
