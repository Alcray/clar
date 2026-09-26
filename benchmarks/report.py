"""Portable JSON and Markdown artifacts, with no composite leaderboard score."""
import json
from pathlib import Path


def pct(value):
    return '—' if value is None else '{:.1%}'.format(value)


def num(value):
    return '—' if value is None else '{:.2f}'.format(value)


def text(value):
    return str(value).replace('|', '\\|').replace('\n', ' ')


def write_report(directory, summary):
    directory = Path(directory)
    (directory / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n')
    plan = summary['manifest']
    lines = [
        '# CLAR model benchmark', '',
        'Run `{}`. Dataset `{}`. Benchmark `{}`.'.format(plan['run_id'], plan['dataset_version'], plan['benchmark_version']), '',
        '**Editorial development cases, not independently validated gold or an unbiased held-out evaluation.** '
        'Fixed and live tracks answer different questions and must be compared separately. Quality metrics below are conditional on successful responses; completion rates and failures stay visible.', '',
        '| Model / track | Completed | Kind macro F1 | Verdict macro F1 | False accusations | Decisive coverage | p50 s | p95 s |',
        '|---|---:|---:|---:|---:|---:|---:|---:|',
    ]
    for name, group in summary['groups'].items():
        lines.append('| {} | {}/{} | {} | {} | {} | {} | {} | {} |'.format(
            text(name), group['successful'], group['attempted'], pct(group['kind']['macro_f1']), pct(group['verdict']['macro_f1']),
            pct(group['false_accusation_rate']), pct(group['decisive_coverage']), num(group['latency_seconds']['p50']), num(group['latency_seconds']['p95'])))
    lines += ['', '## Reliability and source discipline', '',
              '| Model / track | Completion | Source ID validity | Relevant citations | Citation coverage | Statement quotes | Technique quotes | Purpose |',
              '|---|---:|---:|---:|---:|---:|---:|---:|']
    for name, group in summary['groups'].items():
        lines.append('| {} | {} | {} | {} | {} | {} | {} | {} |'.format(text(name), pct(group['completion_rate']), pct(group['citation_id_validity']),
                     pct(group['citation_relevance']), pct(group['citation_coverage']), pct(group['statement_quote_compliance']),
                     pct(group['technique_quote_compliance']), pct(group['purpose_accuracy'])))
        if group['failure_codes']:
            lines += ['', '{} failures: `{}`.'.format(text(name), json.dumps(group['failure_codes'], sort_keys=True)), '']
    lines += ['', '## By language', '', '| Model / track | Language | Completed | Kind macro F1 | Verdict macro F1 | p50 s | p95 s |',
              '|---|---|---:|---:|---:|---:|---:|']
    for name, group in summary['groups'].items():
        for lang, part in group['by_language'].items():
            lines.append('| {} | {} | {}/{} | {} | {} | {} | {} |'.format(text(name), lang, part['successful'], part['attempted'],
                         pct(part['kind']['macro_f1']), pct(part['verdict']['macro_f1']), num(part['latency_seconds']['p50']), num(part['latency_seconds']['p95'])))
    lines += ['', '## By category', '', '| Model / track | Category | Completed | Kind accuracy | Verdict accuracy | False accusations |',
              '|---|---|---:|---:|---:|---:|']
    for name, group in summary['groups'].items():
        for category, part in group['by_category'].items():
            lines.append('| {} | {} | {}/{} | {} | {} | {} |'.format(text(name), text(category), part['successful'], part['attempted'],
                         pct(part['kind']['accuracy']), pct(part['verdict']['accuracy']), pct(part['false_accusation_rate'])))
    lines += ['', '## Screenshot transcription', '', '| Model / track | Screenshot cases | Character error rate | Word error rate | Exact normalized text |',
              '|---|---:|---:|---:|---:|']
    for name, group in summary['groups'].items():
        ocr = group['ocr']
        lines.append('| {} | {} | {} | {} | {} |'.format(text(name), ocr['cases'], pct(ocr['character_error_rate']),
                     pct(ocr['word_error_rate']), pct(ocr['exact_normalized_transcription_rate'])))
    lines += ['', 'OCR uses Unicode NFC, case folding, and whitespace normalization. Screenshots share semantic clusters with their text originals. '
              'Character/word error rates may exceed 100% if a response invents substantial text. Images are six synthetic legible fixtures, not a real feed OCR benchmark.', '']
    comparisons = summary.get('paired_comparisons', [])
    if comparisons:
        lines += ['', '## Paired differences', '', 'Differences are **right minus left**, using successful paired cases. '
                  'Repetitions are averaged per case, then EN/RO/RU variants are grouped by semantic cluster before bootstrap resampling. '
                  'Lower latency and false-accusation rates are better. Intervals describe this small development set, not population performance.', '',
                  '| Track | Left | Right | Metric | Difference | 95% cluster interval | Clusters |',
                  '|---|---|---|---|---:|---|---:|']
        for row in comparisons:
            interval = row['bootstrap_95_interval']
            lines.append('| {} | {} | {} | {} | {} | {} | {} |'.format(row['track'], text(row['left']), text(row['right']), row['metric'],
                         num(row['difference_right_minus_left']), '—' if interval is None else '[{}, {}]'.format(num(interval[0]), num(interval[1])), row['semantic_clusters']))
    lines += ['', '## Interpretation', '',
              '- Full adapter duration includes pipeline extraction, retrieval, assessment, retries, and formatting. Process startup and benchmark queue waiting are recorded separately. No time-to-first-token number is inferred.',
              '- Unknown token usage remains unknown. Cost is not estimated without a pinned price sheet and provider billing information.',
              '- An existing evidence ID is not proof of entailment. Relevant-citation scores compare editorial claim/evidence associations; real entailment still needs human review.',
              '- Live cases expose retrieved URLs and dated labels. Search drift, different retrieval corpora, and publisher changes can explain score differences. Live media-purpose scores are disabled because those reused demo labels were not curated for that task.',
              '- Results contain a dataset hash, configuration hash, fixed prompt hash, and pipeline code hashes for reproducibility. Models can change behind aliases; provider-reported model IDs are retained when available.',
              '- Use separate manual review and held-out locally collected cases before making release claims. v1 includes text and six synthetic screenshots; photographic memes, mixed scripts, cropping, and low-quality screenshots need a larger independently reviewed corpus. Confidence calibration is not measured.', '',
              'Machine-readable records: `records.jsonl`. Warmups: `warmups.jsonl` (excluded). Full metrics and confusion matrices: `summary.json`.', '']
    (directory / 'report.md').write_text('\n'.join(lines), encoding='utf-8')
