"""Review the Merkki (make) list against the committed catalogue shards.

Read-only: prints, for every make, the number of registered vehicles, the number
of aggregated configurations, the number of distinct models and the earliest
registration year, least frequent first. Use it to tune ``MIN_BRAND_REGISTRATIONS``
and ``HIDDEN_BRANDS`` in ``tools/build_traficom_catalog.py``.

    python3 tools/report_brands.py            # every make, least frequent first
    python3 tools/report_brands.py --rare     # only makes hidden from the picker
    python3 tools/report_brands.py --csv /tmp/brands.csv
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


def picker_brands():
    """Makes currently offered in the picker, read from the generated index."""
    text = base.OUT_FILE.read_text(encoding='utf-8')
    match = re.search(r"json_decode\(\s*'(.*)'\s*,\s*true\s*\)", text, re.S)
    if not match:
        raise SystemExit(f'Could not parse {base.OUT_FILE}')
    payload = re.sub(r"\\([\\'])", r'\1', match.group(1))
    return set(json.loads(payload)['brands'])


def collect():
    registrations = Counter()
    configurations = Counter()
    models = defaultdict(set)
    first_years = defaultdict(list)
    for shard in sorted(base.OUT_SHARDS.glob('*.json.gz')):
        with gzip.open(shard, 'rt', encoding='utf-8') as source:
            for row in json.load(source):
                brand = row.get('brand') or ''
                registrations[brand] += int(row.get('registered_count') or 0)
                configurations[brand] += 1
                models[brand].add(row.get('model'))
                start, _ = base.model_year_span(row.get('years') or '')
                if start is not None:
                    first_years[brand].append(start)
    return registrations, configurations, models, first_years


def status_of(brand, total, in_picker):
    flags = []
    if brand.casefold() in base.HIDDEN_BRANDS:
        flags.append('curated-hidden')
    if brand.casefold() in base.BRAND_PLACEHOLDERS:
        flags.append('placeholder')
    if base.MIN_BRAND_REGISTRATIONS and total < base.MIN_BRAND_REGISTRATIONS:
        flags.append('below-threshold')
    if not flags and brand not in in_picker:
        flags.append('not-in-picker')
    return flags


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rare', action='store_true', help='only makes hidden from the picker')
    parser.add_argument('--csv', metavar='PATH', help='also write the table as CSV')
    args = parser.parse_args()

    in_picker = picker_brands()
    registrations, configurations, models, first_years = collect()

    rows = []
    for brand in sorted(registrations, key=lambda name: (registrations[name], name.casefold())):
        flags = status_of(brand, registrations[brand], in_picker)
        if args.rare and not flags:
            continue
        rows.append({
            'brand': brand,
            'registrations': registrations[brand],
            'configurations': configurations[brand],
            'models': len(models[brand]),
            'first_year': min(first_years[brand]) if first_years[brand] else '',
            'status': ','.join(flags),
        })

    print(f'{"regs":>10} {"configs":>8} {"models":>6} {"first":>6}  make  [status]')
    for row in rows:
        print(
            f'{row["registrations"]:10d} {row["configurations"]:8d} {row["models"]:6d} '
            f'{str(row["first_year"]):>6}  {row["brand"]}  [{row["status"]}]'
        )

    print(
        f'\nmakes: {len(registrations)} in shards, {len(in_picker)} in picker, '
        f'threshold={base.MIN_BRAND_REGISTRATIONS}, curated-hidden={len(base.HIDDEN_BRANDS)}'
    )

    if args.csv:
        with open(args.csv, 'w', encoding='utf-8', newline='') as handle:
            writer = csv.DictWriter(handle, fieldnames=['brand', 'registrations', 'configurations', 'models', 'first_year', 'status'])
            writer.writeheader()
            writer.writerows(rows)
        print(f'Wrote {args.csv}')


if __name__ == '__main__':
    main()
