"""Review the Malli (model) list against the committed catalogue shards.

Read-only: prints, for every (make, model) pair, the number of registered vehicles, the
number of aggregated configurations, the number of distinct variants, the first and the
newest first-registration year, the number of vehicle types and how the pair is
classified — least frequent first. Use it to tune ``MIN_MODEL_REGISTRATIONS``,
``MIN_MODEL_YEAR`` and ``HIDDEN_MODELS`` in ``tools/build_traficom_catalog.py``.

    python3 tools/report_models.py                    # every pair, least frequent first
    python3 tools/report_models.py --hidden           # only pairs kept out of the picker
    python3 tools/report_models.py --brand Toyota     # one make
    python3 tools/report_models.py --limit 200        # only the 200 least frequent pairs
    python3 tools/report_models.py --matrix           # tuning matrix instead of the table
    python3 tools/report_models.py --csv /tmp/models.csv
"""

import argparse
import csv
import gzip
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import build_traficom_catalog as base  # noqa: E402

BUCKETS = (1, 2, 5, 10, 25, 50, 100, 500)
COLUMNS = (
    'brand', 'model', 'registrations', 'configurations', 'variants',
    'first_year', 'newest_year', 'vehicle_types', 'status',
)


def bucket(total):
    for limit in BUCKETS:
        if total <= limit:
            return f'<={limit}'
    return f'>{BUCKETS[-1]}'


def decade(year):
    return 'unknown' if year is None else f'{year // 10 * 10}s'


def picker_pairs():
    """The (brand, model) pairs currently offered in the picker."""
    text = base.OUT_FILE.read_text(encoding='utf-8')
    match = re.search(r"json_decode\(\s*'(.*)'\s*,\s*true\s*\)", text, re.S)
    if not match:
        raise SystemExit(f'Could not parse {base.OUT_FILE}')
    payload = re.sub(r"\\([\\'])", r'\1', match.group(1))
    return {(entry['brand'], entry['model']) for entry in json.loads(payload)['models']}


def collect():
    registrations = Counter()
    brand_registrations = Counter()
    configurations = Counter()
    variants = defaultdict(set)
    types = defaultdict(set)
    designated = Counter()
    spans = defaultdict(list)
    for shard in sorted(base.OUT_SHARDS.glob('*.json.gz')):
        with gzip.open(shard, 'rt', encoding='utf-8') as source:
            for row in json.load(source):
                key = (row.get('brand') or '', row.get('model') or '')
                count = int(row.get('registered_count') or 0)
                registrations[key] += count
                brand_registrations[key[0]] += count
                configurations[key] += 1
                variants[key].add(row.get('variant'))
                types[key].add(row.get('vehicle_type'))
                if base.model_is_designation(key[1], row.get('variant') or ''):
                    designated[key] += 1
                start, end = base.model_year_span(row.get('years', ''))
                if start is not None:
                    spans[key].append((start, end))
    first = {key: min(start for start, _ in rows) for key, rows in spans.items()}
    newest = {key: max(end for _, end in rows) for key, rows in spans.items()}
    return registrations, brand_registrations, configurations, variants, types, designated, first, newest


def hide_reason(key, brand_registrations, total, newest, configurations, designated, include_rare_and_old=True):
    """Why the picker keeps this pair out, in the order ``selectable_models()`` applies."""
    brand, model = key
    reason = base.model_hide_reason(brand, model, brand_registrations[brand], total, newest)
    if reason == 'rare+old' and not include_rare_and_old:
        reason = ''
    if reason:
        return reason
    if configurations and designated >= configurations:
        return 'designation'
    return ''


def rows_for(args, in_picker, data):
    registrations, brand_registrations, configurations, variants, types, designated, first, newest = data
    rows = []
    for key in sorted(registrations, key=lambda pair: (registrations[pair], pair[0].casefold(), pair[1].casefold())):
        brand, model = key
        if args.brand and brand.casefold() != args.brand.casefold():
            continue
        total = registrations[key]
        reason = hide_reason(
            key, brand_registrations, total, newest.get(key), configurations[key], designated[key]
        )
        flags = []
        if reason:
            flags.append(f'hidden:{reason}')
        else:
            if base.model_is_rare(total):
                flags.append('rare')
            if base.model_is_obsolete(newest.get(key)):
                flags.append('old')
            if key not in in_picker:
                flags.append('not-in-picker')
        if args.hidden and not reason:
            continue
        rows.append({
            'key': key,
            'reason': reason,
            'registrations': total,
            'configurations': configurations[key],
            'variants': len(variants[key]),
            'first_year': first.get(key, ''),
            'newest_year': newest.get(key, ''),
            'vehicle_types': len(types[key]),
            'status': ','.join(flags),
        })
    return rows


def print_matrix(registrations, brand_registrations, configurations, designated, newest):
    counts = Counter()
    hidden = Counter()
    for key in registrations:
        total = registrations[key]
        if hide_reason(
            key, brand_registrations, total, newest.get(key), configurations[key], designated[key],
            include_rare_and_old=False,
        ):
            continue
        cell = (bucket(total), decade(newest.get(key)))
        counts[cell] += 1
        if base.model_is_rare(total) and base.model_is_obsolete(newest.get(key)):
            hidden[cell] += 1
    columns = sorted({column for _, column in counts}, key=lambda name: (name == 'unknown', name))
    print('pairs with no other problem, "kept / hidden by rare+old":')
    print(f'{"regs":>8}  ' + ''.join(f'{name:>13}' for name in columns) + f'{"total":>13}')
    for row in [f'<={limit}' for limit in BUCKETS] + [f'>{BUCKETS[-1]}']:
        cells = [f'{counts.get((row, column), 0)} / {hidden.get((row, column), 0)}' for column in columns]
        total = sum(counts.get((row, column), 0) for column in columns)
        print(f'{row:>8}  ' + ''.join(f'{cell:>13}' for cell in cells) + f'{total:>13}')
    print(f'{"total":>8}  ' + ''.join(
        f'{sum(counts.get((row, column), 0) for row in [f"<={limit}" for limit in BUCKETS] + [f">{BUCKETS[-1]}"]):>13}'
        for column in columns
    ) + f'{sum(counts.values()):>13}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--hidden', action='store_true', help='only pairs kept out of the picker')
    parser.add_argument('--brand', help='only this make (case-insensitive)')
    parser.add_argument('--limit', type=int, help='only the N least frequent pairs')
    parser.add_argument('--matrix', action='store_true', help='the threshold-tuning matrix instead of the table')
    parser.add_argument('--csv', metavar='PATH', help='also write the table as CSV')
    args = parser.parse_args()

    in_picker = picker_pairs()
    data = collect()
    registrations, brand_registrations, configurations, designated, newest = (
        data[0], data[1], data[2], data[5], data[7]
    )

    if args.matrix:
        print_matrix(registrations, brand_registrations, configurations, designated, newest)
        print(
            f'\npairs: {len(registrations)} in shards, {len(in_picker)} in the picker index on disk, '
            f'MIN_MODEL_REGISTRATIONS={base.MIN_MODEL_REGISTRATIONS}, '
            f'MIN_MODEL_YEAR={base.MIN_MODEL_YEAR}, '
            f'MIN_BRAND_REGISTRATIONS={base.MIN_BRAND_REGISTRATIONS}, '
            f'curated models={len(base.HIDDEN_MODELS)}'
        )
        return

    rows = rows_for(args, in_picker, data)
    all_rows = rows_for(argparse.Namespace(brand=None, hidden=False), in_picker, data)
    if args.limit:
        rows = rows[:args.limit]

    print(f'{"regs":>10} {"configs":>8} {"variants":>8} {"first":>5} {"newest":>6} {"types":>5}  make / model  [status]')
    for row in rows:
        print(
            f'{row["registrations"]:10d} {row["configurations"]:8d} {row["variants"]:8d} '
            f'{str(row["first_year"]):>5} {str(row["newest_year"]):>6} {row["vehicle_types"]:5d}  '
            f'{row["key"][0]} / {row["key"][1]}  [{row["status"]}]'
        )

    reasons = Counter(row['reason'] for row in all_rows if row['reason'])
    print(
        f'\npairs: {len(registrations)} in shards, {len(in_picker)} in the picker index on disk, '
        f'{len(all_rows) - sum(reasons.values())} selectable with the current rules'
    )
    print('hidden reasons: ' + ', '.join(f'{name}={count}' for name, count in sorted(reasons.items())))
    print(
        f'thresholds: MIN_MODEL_REGISTRATIONS={base.MIN_MODEL_REGISTRATIONS}, '
        f'MIN_MODEL_YEAR={base.MIN_MODEL_YEAR}, curated models={len(base.HIDDEN_MODELS)}'
    )

    if args.csv:
        with open(args.csv, 'w', encoding='utf-8', newline='') as handle:
            writer = csv.writer(handle)
            writer.writerow(COLUMNS)
            for row in rows:
                writer.writerow([
                    row['key'][0], row['key'][1], row['registrations'], row['configurations'],
                    row['variants'], row['first_year'], row['newest_year'], row['vehicle_types'],
                    row['status'],
                ])
        print(f'Wrote {args.csv}')


if __name__ == '__main__':
    main()
