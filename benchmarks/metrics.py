"""Deterministic diagnostics; failed requests never masquerade as zero-quality answers."""
import collections
import math
import random
import re
import statistics
import urllib.parse
import unicodedata

from .contract import KINDS, VERDICTS, TECHNIQUES

MISSING = '__missing__'
EXTRA = '__extra__'
HARMFUL = {'contradicted', 'misleading'}


def norm(text):
    return re.sub(r'\s+', ' ', str(text)).strip().casefold()


def safe_url(value):
    try:
        parts = urllib.parse.urlsplit(str(value))
        return bool(parts.scheme in ('https', 'http') and parts.hostname and not parts.username and not parts.password)
    except ValueError:
        return False


def _similarity(a, b):
    a, b = norm(a), norm(b)
    if a == b:
        return 1.0
    # Keep negation-bearing spans intact; lexical overlap only aligns claims, never labels.
    if a in b or b in a:
        return min(len(a), len(b)) / max(len(a), len(b))
    ta, tb = set(re.findall(r'\w+', a)), set(re.findall(r'\w+', b))
    return len(ta & tb) / len(ta | tb) if ta and tb else 0.0


def align_statements(expected, actual):
    """One-to-one span alignment, max overlap first; under-segmentation remains a miss."""
    candidates = sorted(((_similarity(e['text'], a.get('text', '')), ei, ai)
                         for ei, e in enumerate(expected) for ai, a in enumerate(actual)), reverse=True)
    used_expected, used_actual, matches = set(), set(), {}
    for similarity, ei, ai in candidates:
        if similarity < .45 or ei in used_expected or ai in used_actual:
            continue
        matches[ei] = ai
        used_expected.add(ei)
        used_actual.add(ai)
    return matches, [i for i in range(len(actual)) if i not in used_actual]


def _expected_variant(expected, actual):
    candidates = [expected['statements']] + expected.get('statement_variants', [])
    def alignment_quality(statements):
        matches, extras = align_statements(statements, actual)
        overlap = sum(_similarity(statements[ei]['text'], actual[ai].get('text', '')) for ei, ai in matches.items())
        return overlap - .75 * (len(statements) + len(actual) - 2 * len(matches))
    # Label correctness is not consulted when choosing an editorial segmentation.
    index = max(range(len(candidates)), key=lambda i: alignment_quality(candidates[i]))
    return candidates[index], index


def edit_distance(expected, actual):
    previous = list(range(len(actual) + 1))
    for i, left in enumerate(expected, 1):
        current = [i]
        for j, right in enumerate(actual, 1):
            current.append(min(current[-1] + 1, previous[j] + 1, previous[j - 1] + (left != right)))
        previous = current
    return previous[-1]


def ocr_normalize(value):
    return norm(unicodedata.normalize('NFC', str(value)))


def _pair_counts(pairs):
    return [{'expected': e, 'actual': a, 'count': n} for (e, a), n in sorted(collections.Counter(map(tuple, pairs)).items())]


def classification(pairs, labels):
    if not pairs:
        return {'accuracy': None, 'macro_f1': None, 'n': 0, 'per_label': {}, 'confusion': []}
    per_label = {}
    for label in labels:
        tp = sum(e == label and a == label for e, a in pairs)
        fp = sum(e != label and a == label for e, a in pairs)
        fn = sum(e == label and a != label for e, a in pairs)
        if not tp + fp + fn:
            continue
        per_label[label] = {'precision': tp / (tp + fp) if tp + fp else 0.0,
                            'recall': tp / (tp + fn) if tp + fn else 0.0,
                            'f1': 2 * tp / (2 * tp + fp + fn), 'support': tp + fn}
    return {'accuracy': sum(e == a for e, a in pairs) / len(pairs),
            'macro_f1': statistics.mean(v['f1'] for v in per_label.values()) if per_label else None,
            'n': len(pairs), 'per_label': per_label, 'confusion': _pair_counts(pairs)}


def _ratio(n, d):
    return n / d if d else None


def score_case(case, result):
    """Result is normalized to the benchmark shape before this function is called."""
    actual = result['statements']
    expected, variant_index = _expected_variant(case['expected'], actual)
    matches, extras = align_statements(expected, actual)
    kinds, verdicts, techniques = [], [], []
    counts = collections.Counter()
    counts['expected_statements'] = len(expected)
    counts['extracted_statements'] = len(actual)
    counts['matched_statements'] = len(matches)
    all_ids = {x['id'] for x in case.get('evidence', [])}
    for ei, exp in enumerate(expected):
        pred = actual[matches[ei]] if ei in matches else {}
        acceptable = exp.get('acceptable', [{'kind': exp['kind'], 'verdict': exp['verdict']}])
        choice = next((x for x in acceptable if x['kind'] == pred.get('kind') and x['verdict'] == pred.get('verdict')), acceptable[0])
        kinds.append((choice['kind'], pred.get('kind', MISSING)))
        if choice['kind'] == 'factual':
            verdicts.append((choice['verdict'], pred.get('verdict', MISSING)))
            counts['factual_expected'] += 1
            counts['factual_answered'] += bool(pred)
            counts['decisive_verdicts'] += pred.get('verdict') in ('supported', 'contradicted', 'misleading')
            counts['abstentions'] += pred.get('verdict') in ('insufficient', 'conflicting')
        innocent = all(x['verdict'] not in HARMFUL for x in acceptable)
        if innocent:
            counts['nonharmful_statements'] += 1
            counts['false_accusations'] += pred.get('verdict') in HARMFUL
        if case['track'] == 'fixed' and pred:
            ids = pred.get('evidence_ids', [])
            expected_ids = set(exp.get('evidence_ids', []))
            counts['relevant_citations'] += sum(x in expected_ids for x in ids)
        if case['track'] == 'fixed' and choice['kind'] == 'factual' and choice['verdict'] in ('supported', 'contradicted', 'misleading', 'conflicting'):
            counts['evidence_required_claims'] += 1
            counts['claims_with_relevant_citation'] += bool(set(exp.get('evidence_ids', [])) & set(pred.get('evidence_ids', [])))
    for ai in extras:
        pred = actual[ai]
        kinds.append((EXTRA, pred.get('kind', MISSING)))
        if pred.get('kind') == 'factual':
            verdicts.append((EXTRA, pred.get('verdict', MISSING)))
        counts['extra_harmful_claims'] += pred.get('verdict') in HARMFUL
    for pred in actual:
        counts['statement_quotes_total'] += 1
        counts['statement_quotes_exact'] += bool(pred.get('text')) and pred['text'] in case['text']
        if case['track'] == 'fixed':
            ids = pred.get('evidence_ids', [])
            counts['citations_total'] += len(ids)
            counts['citation_relevance_denominator'] += len(ids)
            counts['citations_valid'] += sum(x in all_ids for x in ids)
    for cue in result.get('techniques', []):
        counts['technique_quotes_total'] += 1
        counts['technique_quotes_exact'] += bool(cue.get('quote')) and cue['quote'] in case['text']
    media_scored = case['expected'].get('score_media', True)
    if media_scored:
        expected_types = {x['type'] for x in case['expected'].get('techniques', [])}
        actual_types = {x['type'] for x in result.get('techniques', [])}
        for label in TECHNIQUES:
            techniques.append((label, label in expected_types, label in actual_types))
        counts['purpose_total'] = 1
        counts['purpose_correct'] = result.get('purpose') == case['expected']['purpose']
        counts['fraud_total'] = 1
        counts['fraud_correct'] = result.get('fraud_signal') == case['expected'].get('fraud_signal', False)
        if not case['expected'].get('fraud_signal'):
            counts['nonfraud_cases'] = 1
            counts['false_fraud_accusations'] = result.get('fraud_signal') is True
    if case.get('modality') == 'image':
        gold, transcript = ocr_normalize(case['text']), ocr_normalize(result.get('original_text', ''))
        counts['ocr_character_edits'] = edit_distance(gold, transcript)
        counts['ocr_character_total'] = len(gold)
        counts['ocr_word_edits'] = edit_distance(gold.split(), transcript.split())
        counts['ocr_word_total'] = len(gold.split())
        counts['ocr_cases'] = 1
        counts['ocr_exact_cases'] = gold == transcript
    return {'kind_pairs': kinds, 'verdict_pairs': verdicts, 'technique_pairs': techniques, 'expected_variant_index': variant_index,
            'counts': dict(counts), 'case_values': {
                'kind_accuracy': _ratio(sum(e == a for e, a in kinds), len(kinds)),
                'verdict_accuracy': _ratio(sum(e == a for e, a in verdicts), len(verdicts)),
                'false_accusation_rate': _ratio(counts['false_accusations'], counts['nonharmful_statements']),
                'purpose_accuracy': _ratio(counts['purpose_correct'], counts['purpose_total'])}}


def percentile(values, q):
    values = sorted(values)
    if not values:
        return None
    index = (len(values) - 1) * q
    lo, hi = math.floor(index), math.ceil(index)
    return values[lo] + (values[hi] - values[lo]) * (index - lo)


def summarize(records):
    successful = [r for r in records if r['status'] == 'ok']
    scored = [r['scores'] for r in successful]
    kinds = [x for score in scored for x in score['kind_pairs']]
    verdicts = [x for score in scored for x in score['verdict_pairs']]
    counts = collections.Counter()
    for score in scored:
        counts.update(score['counts'])
    tech = collections.defaultdict(collections.Counter)
    for score in scored:
        for label, truth, predicted in score['technique_pairs']:
            tech[label]['tp' if truth and predicted else 'fn' if truth else 'fp' if predicted else 'tn'] += 1
    per_tech = {k: dict(v, f1=_ratio(2 * v['tp'], 2 * v['tp'] + v['fp'] + v['fn'])) for k, v in sorted(tech.items())}
    durations = [r['duration_seconds'] for r in records]
    ok_times = [r['duration_seconds'] for r in successful]
    fixed = any(r['track'] == 'fixed' for r in records)
    usage = collections.Counter()
    usage_known = collections.Counter()
    for row in records:
        for field in ('input_tokens', 'output_tokens', 'thinking_tokens', 'cached_input_tokens', 'requests'):
            value = row.get('telemetry', {}).get(field)
            if type(value) in (int, float):
                usage[field] += value
                usage_known[field] += 1
    return {
        'attempted': len(records), 'successful': len(successful),
        'completion_rate': _ratio(len(successful), len(records)),
        'status_counts': dict(collections.Counter(r['status'] for r in records)),
        'failure_codes': dict(collections.Counter(r.get('error', {}).get('code', 'unknown') for r in records if r['status'] != 'ok')),
        'kind': classification(kinds, KINDS), 'verdict': classification(verdicts, VERDICTS),
        'extraction': {'precision': _ratio(counts['matched_statements'], counts['extracted_statements']),
                       'recall': _ratio(counts['matched_statements'], counts['expected_statements'])},
        'factual_coverage': _ratio(counts['factual_answered'], counts['factual_expected']),
        'decisive_coverage': _ratio(counts['decisive_verdicts'], counts['factual_expected']),
        'abstention_rate': _ratio(counts['abstentions'], counts['factual_answered']),
        'false_accusation_rate': _ratio(counts['false_accusations'], counts['nonharmful_statements']),
        'extra_harmful_claims': counts['extra_harmful_claims'],
        'false_fraud_accusation_rate': _ratio(counts['false_fraud_accusations'], counts['nonfraud_cases']),
        'purpose_accuracy': _ratio(counts['purpose_correct'], counts['purpose_total']),
        'fraud_accuracy': _ratio(counts['fraud_correct'], counts['fraud_total']),
        'techniques': {'per_type': per_tech, 'macro_f1': statistics.mean([x['f1'] for x in per_tech.values() if x['f1'] is not None]) if any(x['f1'] is not None for x in per_tech.values()) else None},
        'ocr': {'character_error_rate': _ratio(counts['ocr_character_edits'], counts['ocr_character_total']),
                'word_error_rate': _ratio(counts['ocr_word_edits'], counts['ocr_word_total']),
                'exact_normalized_transcription_rate': _ratio(counts['ocr_exact_cases'], counts['ocr_cases']), 'cases': counts['ocr_cases']},
        'statement_quote_compliance': _ratio(counts['statement_quotes_exact'], counts['statement_quotes_total']),
        'technique_quote_compliance': _ratio(counts['technique_quotes_exact'], counts['technique_quotes_total']),
        'citation_id_validity': _ratio(counts['citations_valid'], counts['citations_total']) if fixed else None,
        'citation_relevance': _ratio(counts['relevant_citations'], counts['citation_relevance_denominator']) if fixed else None,
        'citation_coverage': _ratio(counts['claims_with_relevant_citation'], counts['evidence_required_claims']) if fixed else None,
        'latency_seconds': {'p50': percentile(ok_times, .5), 'p95': percentile(ok_times, .95),
                            'mean': statistics.mean(ok_times) if ok_times else None,
                            'min': min(ok_times) if ok_times else None, 'max': max(ok_times) if ok_times else None,
                            'all_attempts_p50': percentile(durations, .5), 'all_attempts_p95': percentile(durations, .95)},
        'usage': {key: {'total_known': usage[key] if usage_known[key] else None, 'records_with_usage': usage_known[key]}
                  for key in ('input_tokens', 'output_tokens', 'thinking_tokens', 'cached_input_tokens', 'requests')},
        'counts': dict(counts),
    }


def summarize_groups(records):
    output = {}
    for record in records:
        key = record['model_name'] + '/' + record['track']
        output.setdefault(key, []).append(record)
    result = {}
    for key, rows in sorted(output.items()):
        result[key] = summarize(rows)
        for dimension in ('language', 'category', 'modality'):
            groups = collections.defaultdict(list)
            for row in rows:
                groups[row.get(dimension, 'text')].append(row)
            result[key]['by_' + dimension] = {label: summarize(items) for label, items in sorted(groups.items())}
    return result


def paired_comparisons(records, samples=2000, seed=1729):
    """Averages repetitions then resamples semantic clusters, not translated duplicates."""
    models = sorted({r['model_name'] for r in records})
    output = []
    for track in sorted({r['track'] for r in records}):
        for left_i, left in enumerate(models):
            for right in models[left_i + 1:]:
                for metric in ('kind_accuracy', 'verdict_accuracy', 'false_accusation_rate', 'purpose_accuracy', 'duration_seconds'):
                    per_model = {left: collections.defaultdict(list), right: collections.defaultdict(list)}
                    clusters = {}
                    for row in records:
                        if row['track'] != track or row['model_name'] not in per_model or row['status'] != 'ok':
                            continue
                        value = row.get('duration_seconds') if metric == 'duration_seconds' else row['scores']['case_values'].get(metric)
                        if value is not None:
                            per_model[row['model_name']][row['case_id']].append(value)
                            clusters[row['case_id']] = row['cluster_id']
                    paired = sorted(set(per_model[left]) & set(per_model[right]))
                    if not paired:
                        continue
                    cluster_deltas = collections.defaultdict(list)
                    for case_id in paired:
                        cluster_deltas[clusters[case_id]].append(statistics.mean(per_model[right][case_id]) - statistics.mean(per_model[left][case_id]))
                    values = [statistics.mean(x) for x in cluster_deltas.values()]
                    mean = statistics.mean(values)
                    randomizer = random.Random(seed)
                    draws = [statistics.mean(randomizer.choices(values, k=len(values))) for _ in range(samples)] if len(values) >= 2 and samples > 0 else []
                    output.append({'track': track, 'left': left, 'right': right, 'metric': metric,
                                   'difference_right_minus_left': mean,
                                   'paired_cases': len(paired), 'semantic_clusters': len(values),
                                   'bootstrap_95_interval': [percentile(draws, .025), percentile(draws, .975)] if draws else None,
                                   'bootstrap_samples': len(draws), 'unit': 'semantic_cluster',
                                   'conditioning': 'Only successful paired cases; consult completion rates separately. Development cases are not a random population sample.'})
    return output
